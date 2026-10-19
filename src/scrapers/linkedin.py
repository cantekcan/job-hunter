"""LinkedIn **guest** job search (no login, no cookies, ever).

Endpoints (see docs/sources_more.md, second-hand from JobSpy; not verified from the build box):

- list:   https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
          ?keywords={q}&location={loc}&f_TPR=r86400&sortBy=DD&start={0,10,...}
          -> bare <li> fragments, 10 cards per page
- detail: https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}

Any 429 / 999 / 403 or an authwall/login page stops LinkedIn for the rest of the run.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional
from urllib.parse import urlencode, urlsplit

from bs4 import BeautifulSoup, Tag

from ..cover_letter import detect_language
from ..dateparse import parse_relative_date
from ..models import Job
from .base import BaseScraper, SourceBlocked
from .htmlcards import normalize_url, text_of

log = logging.getLogger(__name__)

BASE_URL = "https://www.linkedin.com"
LIST_URL = BASE_URL + "/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = BASE_URL + "/jobs-guest/jobs/api/jobPosting/{id}"
PAGE_SIZE = 10
MAX_REQUESTS = 30  # per run, list + detail together

_URN_RE = re.compile(r"urn:li:jobPosting:(\d+)")
_VIEW_ID_RE = re.compile(r"/jobs/view/(?:[^/?#]*?-)?(\d+)(?=[/?#]|$)")
_AUTHWALL_URL_RE = re.compile(r"/(authwall|signup|login|uas/login|checkpoint)", re.I)
_AUTHWALL_HTML_RE = re.compile(r'authwall|id="join-form"|class="[^"]*\bsign-in-form\b', re.I)


def search_url(query: str, location: str, start: int = 0) -> str:
    """``location`` may carry extra params after a "|": "Türkiye|f_WT=2" (remote)."""
    loc, _, extra = location.partition("|")
    params = {"keywords": query, "location": loc.strip(), "f_TPR": "r86400", "sortBy": "DD", "start": start}
    for pair in filter(None, (p.strip() for p in extra.split("&"))):
        key, _, value = pair.partition("=")
        params[key.strip()] = value.strip()
    return f"{LIST_URL}?{urlencode(params)}"


def is_authwall(html: str, final_url: str = "") -> bool:
    if final_url and _AUTHWALL_URL_RE.search(urlsplit(final_url).path):
        return True
    return bool(_AUTHWALL_HTML_RE.search(html[:20000]))


def _work_model(location_param: str, location_text: str) -> str:
    if "f_WT=2" in location_param or re.search(r"\b(remote|uzaktan)\b", location_text, re.I):
        return "uzaktan"
    if "f_WT=3" in location_param or re.search(r"\b(hybrid|hibrit)\b", location_text, re.I):
        return "hibrit"
    return ""


def _job_id(card: Tag) -> Optional[str]:
    for el in [card, *card.find_all(attrs={"data-entity-urn": True})]:
        m = _URN_RE.search(str(el.get("data-entity-urn") or ""))
        if m:
            return m.group(1)
    link = card.find("a", href=_VIEW_ID_RE)
    if link:
        m = _VIEW_ID_RE.search(link["href"])
        return m.group(1) if m else None
    return None


def _parse_card(card: Tag, today: date) -> Optional[Job]:
    ext_id = _job_id(card)
    title = text_of(card.select_one(".base-search-card__title"))
    if not ext_id or not title:
        return None
    company = text_of(card.select_one(".base-search-card__subtitle"))
    location = text_of(card.select_one(".job-search-card__location"))
    time_el = card.find("time")
    posted_date: Optional[date] = None
    posted_text = text_of(time_el)
    if time_el is not None and time_el.get("datetime"):
        try:
            posted_date = date.fromisoformat(str(time_el["datetime"])[:10])
        except ValueError:
            posted_date = None
    if posted_date is None and posted_text:
        posted_date = parse_relative_date(posted_text, today)
    link = card.select_one("a.base-card__full-link") or card.find("a", href=_VIEW_ID_RE)
    url = normalize_url(link["href"], BASE_URL, "www.linkedin.com") if link and link.get("href") \
        else f"{BASE_URL}/jobs/view/{ext_id}"
    return Job(source=LinkedInScraper.name, external_id=ext_id, title=title, company=company,
               location=location, work_model=_work_model("", location), url=url,
               posted_text=posted_text, posted_date=posted_date)


def parse_cards(html: str, today: date) -> list[Job]:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.base-search-card") or soup.select("[data-entity-urn*=jobPosting]") or soup.find_all("li")
    jobs: dict[str, Job] = {}
    for card in cards:
        job = _parse_card(card, today)
        if job and job.external_id not in jobs:
            jobs[job.external_id] = job
    return list(jobs.values())


def parse_detail(html: str, job: Job) -> Job:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("div.show-more-less-html__markup") or soup.select_one(".description__text")
    parts = [body.get_text("\n", strip=True)] if body else []
    criteria = [text_of(c) for c in soup.select("span.description__job-criteria-text")]
    if criteria:
        parts.append("Kriterler: " + " · ".join(c for c in criteria if c))
    if parts:
        job.description = "\n".join(parts)[:8000]
        job.language = detect_language(f"{job.title}\n{job.description}")
    return job


class LinkedInScraper(BaseScraper):
    name = "linkedin"
    accept_cookies = False  # guest means no cookies at all: the jar rejects JSESSIONID/bcookie/lidc

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("delay_range", (3.0, 7.0))
        super().__init__(*args, **kwargs)
        self.requests_made = 0
        self.max_requests = MAX_REQUESTS
        # guest endpoints serve English UI; that's fine for parsing
        self.session.headers.update({"Accept-Language": "en-US,en;q=0.9,tr-TR;q=0.8"})

    def sniff(self, html: str) -> bool:
        return "base-search-card" in html or "linkedin.com/jobs" in html or "urn:li:jobPosting" in html

    def queries(self) -> list[str]:
        return list(getattr(self.cfg, "linkedin_queries", []) or [])

    def _locations(self) -> list[str]:
        return list(getattr(self.cfg, "linkedin_locations", []) or ["Türkiye"])

    def _get(self, url: str) -> str:
        if self.requests_made >= self.max_requests:
            raise SourceBlocked(f"request cap of {self.max_requests} reached")
        self.requests_made += 1
        resp = self.get_or_block(url)
        final_url = str(getattr(resp, "url", "") or "")
        if final_url and _AUTHWALL_URL_RE.search(urlsplit(final_url).path):
            raise SourceBlocked("redirected to authwall/login")
        return resp.text

    def parse_html(self, html: str, today: Optional[date] = None) -> list[Job]:
        if is_authwall(html):
            log.warning("[linkedin] authwall page in sample; no cards")
            return []
        return parse_cards(html, today or self.today or date.today())

    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        today = self.today or date.today()
        jobs: list[Job] = []
        for location in self._locations():
            for page in range(max(max_pages, 1)):
                html = self._get(search_url(query, location, page * PAGE_SIZE))
                self.save_raw(html, f"{query}-{location}-p{page + 1}")
                page_jobs = parse_cards(html, today)
                if not page_jobs and is_authwall(html):
                    raise SourceBlocked("authwall/login page")
                for job in page_jobs:
                    # an explicit f_WT search filter is authoritative over the card text
                    job.work_model = _work_model(location, "") or job.work_model
                jobs += page_jobs
                log.info("[linkedin] %r @ %r page %d: %d cards", query, location, page + 1, len(page_jobs))
                if len(page_jobs) < PAGE_SIZE:
                    break
        return jobs

    def fetch_detail(self, job: Job) -> Job:
        if self.blocked:
            return job
        try:
            html = self._get(DETAIL_URL.format(id=job.external_id))
            if is_authwall(html) and "show-more-less-html" not in html:
                raise SourceBlocked("authwall/login page")
            return parse_detail(html, job)
        except SourceBlocked as exc:
            self.blocked = True
            log.warning("[linkedin] blocked while fetching details (%s); skipping the rest", exc)
            return job
