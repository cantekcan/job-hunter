"""Secretcv (www.secretcv.com). Low value for .NET roles; kept cheap and fail-soft.

- No free-text keyword URL exists, so we scan list paths (default /is-ilanlari/istanbul-is-ilanlari),
  pages via ?sf=N, and let the title pre-filter in main drop irrelevant ads.
- Detail URL: https://www.secretcv.com/{company-slug}/{title-slug}-is-ilanlari-{id}
- Card text: title · company ("Firma Adı Gizli") · location · "İlan Tarihi: 3 gün önce"
  (sponsored cards have no date).
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..cover_letter import detect_language
from ..dateparse import parse_relative_date
from ..models import Job
from ..textutil import fold
from .base import BaseScraper
from .htmlcards import by_hint, card_container, normalize_url, page_text, tokens_of

log = logging.getLogger(__name__)

BASE_URL = "https://www.secretcv.com"
LINK_RE = re.compile(r"^(?:https?://[^/]*secretcv\.com)?/[^/?#]+/[^/?#]+-is-ilanlari-(\d+)/?(?:[?#].*)?$")
_AGE_RE = re.compile(r"\d+\s*(dakika|saat|gun|hafta|ay)\s*once|bugun|dun|\d{1,2}[-./]\d{1,2}[-./]\d{4}")
_DATE_PREFIX_RE = re.compile(r"^ilan tarihi\s*:?\s*", re.I)
_NO_RESULTS_RE = re.compile(r"ilan bulunamadi")
_NOISE_RE = re.compile(r"^(sponsorlu|one cikan|acil|hemen basvur|basvur|kaydet|yeni)$")
_LOCATION_RE = re.compile(r"(istanbul|ankara|izmir|anadolu|avrupa|turkiye|remote|uzaktan|[a-z]+ - [a-z]+)$")
_DETAIL_DATE_RE = re.compile(r"ilan tarihi\s*:?\s*(\d{1,2}[-./]\d{1,2}[-./]\d{4})", re.I)
_SECTIONS = ("is aciklamasi", "istenen yetenek ve uzmanliklar", "aranan nitelikler", "genel nitelikler")
_STOP = ("firma hakkinda", "benzer ilanlar", "diger ilanlar")


def extract_id(href: str) -> Optional[str]:
    m = LINK_RE.match(href.strip())
    return m.group(1) if m else None


def list_url(path: str, page: int = 1) -> str:
    url = f"{BASE_URL}/is-ilanlari/{path.strip('/')}"
    return f"{url}?sf={page}" if page > 1 else url


def _parse_card(card: Tag, anchor: Tag, ext_id: str, today: date) -> Optional[Job]:
    title = by_hint(card, ("title", "position", "job-name")) or (anchor.get("title") or "").strip()
    company = by_hint(card, ("company", "firm"))
    location = by_hint(card, ("location", "city"))
    date_text = by_hint(card, ("date", "ilan-tarihi"))
    rest = []
    for tok in tokens_of(card):
        f = fold(tok)
        if _NOISE_RE.match(f):
            continue
        if f.startswith("ilan tarihi") or _AGE_RE.fullmatch(f):
            date_text = date_text or tok
            continue
        rest.append(tok)
    rest = [t for t in rest if t not in (title, company, location)]
    title = title or (rest.pop(0) if rest else "")
    company = company or (rest.pop(0) if rest else "")
    if not location:
        location = next((t for t in rest if _LOCATION_RE.search(fold(t))), "")
    date_text = _DATE_PREFIX_RE.sub("", date_text).strip()
    if not title:
        return None
    return Job(source=SecretcvScraper.name, external_id=ext_id, title=title, company=company,
               location=location, url=normalize_url(anchor["href"], BASE_URL, "www.secretcv.com"),
               posted_text=date_text,
               posted_date=parse_relative_date(date_text, today) if date_text else None)


def parse_cards(html: str, today: date) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    if _NO_RESULTS_RE.search(page_text(soup)) and not soup.find("a", href=LINK_RE):
        return []
    jobs: dict[str, Job] = {}
    seen_cards: set[int] = set()
    for anchor in soup.find_all("a", href=LINK_RE):
        ext_id = extract_id(anchor["href"])
        if not ext_id or ext_id in jobs:
            continue
        card = card_container(anchor, extract_id, ext_id, LINK_RE)
        if id(card) in seen_cards:
            continue
        seen_cards.add(id(card))
        job = _parse_card(card, anchor, ext_id, today)
        if job:
            jobs[ext_id] = job
    return list(jobs.values())


def parse_detail(html: str, job: Job) -> Job:
    soup = BeautifulSoup(html, "lxml")
    m = _DETAIL_DATE_RE.search(soup.get_text(" ", strip=True))
    if m:
        job.posted_date = parse_relative_date(m.group(1)) or job.posted_date
    for tag in soup(["script", "style", "nav", "header", "footer"]):
        tag.decompose()
    lines = tokens_of(soup)
    start = next((i for i, ln in enumerate(lines) if fold(ln).rstrip(":").strip() in _SECTIONS), None)
    if start is not None:
        end = next((i for i in range(start + 1, len(lines)) if any(fold(lines[i]).startswith(s) for s in _STOP)),
                   len(lines))
        job.description = "\n".join(lines[start:end])[:8000]
        job.language = detect_language(f"{job.title}\n{job.description}")
    return job


class SecretcvScraper(BaseScraper):
    name = "secretcv"

    def sniff(self, html: str) -> bool:
        return "secretcv" in html.lower()

    def queries(self) -> list[str]:
        return list(getattr(self.cfg, "secretcv_paths", []) or ["istanbul-is-ilanlari"])

    def parse_html(self, html: str, today: Optional[date] = None) -> list[Job]:
        return parse_cards(html, today or self.today or date.today())

    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        """``query`` is a list path such as "istanbul-is-ilanlari"."""
        today = self.today or date.today()
        jobs: list[Job] = []
        for page in range(1, max(max_pages, 1) + 1):
            html = self.get(list_url(query, page)).text
            self.save_raw(html, f"{query}-p{page}")
            page_jobs = parse_cards(html, today)
            log.info("[secretcv] %r page %d: %d cards", query, page, len(page_jobs))
            if not page_jobs:
                break
            jobs += page_jobs
        return jobs

    def fetch_detail(self, job: Job) -> Job:
        return parse_detail(self.get(job.url).text, job)
