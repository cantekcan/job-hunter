"""Indeed Türkiye (tr.indeed.com).

- list: https://tr.indeed.com/jobs?q={q}&l={loc}&fromage=3&sort=date&start={0,10}
- id:   jobkey / data-jk; canonical URL https://tr.indeed.com/viewjob?jk={jk}
- parse order: embedded JSON (window.mosaic.providerData["mosaic-provider-jobcards"]) first,
  then HTML cards ([data-jk]). Selectors are second-hand (docs/sources_more.md).

Cloudflare / captcha pages or HTTP 403/429 skip Indeed for the rest of the run.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup, Tag

from ..cover_letter import detect_language
from ..dateparse import parse_relative_date
from ..models import Job
from ..scorer import extract_json
from ..textutil import fold
from .base import BaseScraper, SourceBlocked
from .htmlcards import text_of

log = logging.getLogger(__name__)

BASE_URL = "https://tr.indeed.com"
FROMAGE_DAYS = 3  # fromage=1 returned 0 even for broad queries; 3 days + DB dedupe is safer
MAX_PAGES = 2
TR_TZ = timezone(timedelta(hours=3))  # Türkiye has no DST

_MOSAIC_RE = re.compile(r'window\.mosaic\.providerData\[\s*["\']mosaic-provider-jobcards["\']\s*\]\s*=\s*')
_CHALLENGE_RE = re.compile(r"just a moment|cf-challenge|challenge-platform|hcaptcha|h-captcha|"
                           r"cf-turnstile|captcha-delivery|verify you are human|insan oldugunuzu", re.I)
_NO_RESULTS_RE = re.compile(r"eslesmedi|eslesen .*bulunamadi|did not match any jobs|sonuc bulunamadi")


def search_url(query: str, location: str, start: int = 0) -> str:
    params = {"q": query, "l": location, "fromage": FROMAGE_DAYS, "sort": "date", "start": start}
    return f"{BASE_URL}/jobs?{urlencode(params)}"


def job_url(jk: str) -> str:
    return f"{BASE_URL}/viewjob?jk={jk}"


def is_challenge(html: str) -> bool:
    return bool(_CHALLENGE_RE.search(fold(html[:50000])))


def is_no_results(soup: BeautifulSoup) -> bool:
    return bool(_NO_RESULTS_RE.search(fold(soup.get_text(" ", strip=True))))


def _from_epoch_ms(value: Any) -> Optional[date]:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=TR_TZ).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _work_model(*texts: str) -> str:
    joined = fold(" ".join(t for t in texts if t))
    if re.search(r"\b(uzaktan|remote|evden)\b", joined):
        return "uzaktan"
    if re.search(r"\b(hibrit|hybrid)\b", joined):
        return "hibrit"
    return ""


def parse_mosaic(html: str, today: date) -> list[Job]:
    m = _MOSAIC_RE.search(html)
    if not m:
        return []
    data = extract_json(html[m.end():])
    try:
        results = data["metaData"]["mosaicProviderJobCardsModel"]["results"]  # type: ignore[index]
    except (KeyError, TypeError):
        return []
    jobs: list[Job] = []
    for r in results if isinstance(results, list) else []:
        jk = str(r.get("jobkey") or "").strip()
        title = str(r.get("displayTitle") or r.get("title") or "").strip()
        if not jk or not title:
            continue
        rel = str(r.get("formattedRelativeTime") or "")
        posted = _from_epoch_ms(r.get("pubDate")) or (parse_relative_date(rel, today) if rel else None)
        location = str(r.get("formattedLocation") or "")
        remote = "uzaktan" if r.get("remoteLocation") else ""
        snippet = BeautifulSoup(str(r.get("snippet") or ""), "lxml").get_text(" ", strip=True)
        jobs.append(Job(source=IndeedScraper.name, external_id=jk, title=title,
                        company=str(r.get("company") or "").strip(), location=location,
                        work_model=remote or _work_model(location, snippet), url=job_url(jk),
                        posted_text=rel, posted_date=posted))
    return jobs


def _card_date_text(card: Tag) -> str:
    el = card.select_one("[data-testid=myJobsStateDate]") or card.select_one("span.date")
    if el is None:
        return ""
    for hidden in el.select(".visually-hidden, .screen-reader-only"):
        hidden.decompose()  # "Yayınlandı" / "Posted" prefix
    return text_of(el)


def parse_cards(soup: BeautifulSoup, today: date) -> list[Job]:
    jobs: list[Job] = []
    for card in soup.select("[data-jk]"):
        jk = str(card.get("data-jk") or "").strip()
        title_el = card.select_one("h2.jobTitle span[title]") or card.select_one("h2.jobTitle")
        title = (title_el.get("title") or text_of(title_el)) if title_el is not None else ""
        if not jk or not title:
            continue
        holder = card
        for parent in card.parents:  # data-jk often sits on the <a>; fields live in the card around it
            classes = parent.get("class") or []
            if parent.name == "li" or "job_seen_beacon" in classes or "cardOutline" in classes:
                holder = parent
                break
        posted_text = _card_date_text(holder)
        location = text_of(holder.select_one("[data-testid=text-location]"))
        jobs.append(Job(source=IndeedScraper.name, external_id=jk, title=str(title).strip(),
                        company=text_of(holder.select_one("[data-testid=company-name]")),
                        location=location, work_model=_work_model(location), url=job_url(jk),
                        posted_text=posted_text,
                        posted_date=parse_relative_date(posted_text, today) if posted_text else None))
    return jobs


def parse_detail(html: str, job: Job) -> Job:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#jobDescriptionText") or soup.select_one("[data-testid=jobsearch-JobComponent-description]")
    if body is not None:
        job.description = body.get_text("\n", strip=True)[:8000]
        job.language = detect_language(f"{job.title}\n{job.description}")
    return job


def _dedupe(jobs: list[Job]) -> list[Job]:
    seen: dict[str, Job] = {}
    for job in jobs:
        seen.setdefault(job.external_id, job)
    return list(seen.values())


class IndeedScraper(BaseScraper):
    name = "indeed"

    def sniff(self, html: str) -> bool:
        return "indeed" in html.lower() or "data-jk=" in html or "mosaic-provider-jobcards" in html

    def queries(self) -> list[str]:
        return list(getattr(self.cfg, "indeed_queries", []) or [])

    def _locations(self) -> list[str]:
        return list(getattr(self.cfg, "indeed_locations", []) or ["Türkiye"])

    def parse_html(self, html: str, today: Optional[date] = None) -> list[Job]:
        """Parse a result page. Raises SourceBlocked on a Cloudflare/captcha page."""
        today = today or self.today or date.today()
        soup = BeautifulSoup(html, "lxml")
        jobs = parse_mosaic(html, today) or parse_cards(soup, today)
        if jobs:
            return _dedupe(jobs)
        if is_challenge(html):
            raise SourceBlocked("Cloudflare/captcha challenge page")
        if not is_no_results(soup):
            log.warning("[indeed] page has no job cards and no 'no results' text - layout change or soft block?")
        return []

    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        today = self.today or date.today()
        jobs: list[Job] = []
        for location in self._locations():
            for page in range(min(max(max_pages, 1), MAX_PAGES)):
                resp = self.get_or_block(search_url(query, location, page * 10))
                self.save_raw(resp.text, f"{query}-{location}-p{page + 1}")
                page_jobs = self.parse_html(resp.text, today)
                log.info("[indeed] %r @ %r page %d: %d cards", query, location, page + 1, len(page_jobs))
                jobs += page_jobs
                if len(page_jobs) < 10:
                    break
        return _dedupe(jobs)

    def fetch_detail(self, job: Job) -> Job:
        if self.blocked:
            return job
        try:
            resp = self.get_or_block(job.url)
        except SourceBlocked as exc:
            self.blocked = True
            log.warning("[indeed] blocked while fetching details (%s); skipping the rest", exc)
            return job
        if is_challenge(resp.text):
            self.blocked = True
            log.warning("[indeed] challenge page on detail; skipping the rest")
            return job
        return parse_detail(resp.text, job)
