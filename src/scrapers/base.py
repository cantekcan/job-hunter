"""Scraper base class with a polite HTTP helper."""
from __future__ import annotations

import logging
import random
import re
from datetime import date
from pathlib import Path
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Iterable, Optional

import requests
from http.cookiejar import DefaultCookiePolicy

from ..models import Job

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
}
RETRY_STATUS = {429, 500, 502, 503, 504}
TIMEOUT_RETRIES = 2  # a timing-out site rarely recovers within seconds
MAX_CONSECUTIVE_FAILURES = 3  # circuit breaker: this many failed requests in a row -> source skipped
DEFAULT_SOURCE_BUDGET_S = 360.0  # per-source wall-clock budget for list pages


class SourceBlocked(RuntimeError):
    """The site refused us (429/999/403, captcha, authwall). The source is skipped for this run."""


class BaseScraper(ABC):
    """Subclasses set ``name`` and implement :meth:`fetch` (and ideally :meth:`parse_html`)."""

    name: str = "base"
    accept_cookies: bool = True  # False -> the session jar rejects every cookie (LinkedIn guest)

    def __init__(self, session: Optional[requests.Session] = None,
                 delay_range: tuple[float, float] = (2.0, 5.0), timeout: float = 20.0,
                 retries: int = 3, sleep: Callable[[float], None] = time.sleep):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.delay_range = delay_range
        self.timeout = timeout
        self.retries = retries
        self._sleep = sleep
        self._last_request: Optional[float] = None
        self.today: Optional[date] = None  # the run's day; set by main so relative ages match it
        self.raw_dir: Optional[Path] = None  # if set, list pages are saved here for debugging
        self.cfg: Any = None  # set by configure()
        self.blocked = False  # set when the site blocks us; remaining queries are skipped
        self.max_consecutive_failures = MAX_CONSECUTIVE_FAILURES
        self._refusal_logged = False
        self._n_requests = 0
        self._last_status = ""
        self.consecutive_failures = 0
        self.time_budget_s = DEFAULT_SOURCE_BUDGET_S
        self.deadline: Optional[float] = None  # global scrape deadline (time.monotonic()), set by main
        self._budget_end: Optional[float] = None
        self._clock: Callable[[], float] = time.monotonic
        if not self.accept_cookies:
            jar = getattr(self.session, "cookies", None)
            if hasattr(jar, "set_policy"):
                jar.set_policy(DefaultCookiePolicy(allowed_domains=[]))  # reject every Set-Cookie
            self._clear_cookies()

    def configure(self, cfg: Any) -> None:
        """Hook called by main before fetching; scrapers read their own settings from ``cfg``."""
        self.cfg = cfg
        budget = getattr(cfg, "source_time_budget_s", None)
        if isinstance(budget, (int, float)) and budget > 0:
            self.time_budget_s = float(budget)

    def _check_budget(self) -> None:
        """Raise SourceBlocked when the breaker tripped or a time budget/deadline is exhausted."""
        if self.consecutive_failures >= self.max_consecutive_failures:
            raise SourceBlocked(f"{self.consecutive_failures} consecutive failed requests")
        now = self._clock()
        if self.deadline is not None and now >= self.deadline:
            raise SourceBlocked("global scrape deadline reached")
        if self._budget_end is not None and now >= self._budget_end:
            raise SourceBlocked(f"time budget of {self.time_budget_s:.0f}s used up")

    def _clear_cookies(self) -> None:
        jar = getattr(self.session, "cookies", None)
        if jar is not None and hasattr(jar, "clear"):
            jar.clear()

    def _record(self, ok: bool) -> None:
        self.consecutive_failures = 0 if ok else self.consecutive_failures + 1

    def queries(self) -> list[str]:
        """Queries this source runs. Default: the shared ``search_queries`` (Kariyer.net slugs)."""
        return list(getattr(self.cfg, "search_queries", []) or [])

    def sniff(self, html: str) -> bool:
        """True if a saved page (``--sample-html``) looks like it came from this site."""
        return False

    def fetch_all(self, cfg: Any = None) -> list[Job]:
        """Run every configured query; one failing query never stops the others."""
        if cfg is not None:
            self.configure(cfg)
        max_pages = int(getattr(self.cfg, "max_pages", 1) or 1)
        jobs: list[Job] = []
        self._budget_end = self._clock() + self.time_budget_s
        try:
            for query in self.queries():
                if self.blocked:
                    log.info("[%s] skipped earlier in this run; skipping query %r", self.name, query)
                    continue
                try:
                    self._check_budget()
                    jobs += self.fetch(query, max_pages=max_pages)
                except SourceBlocked as exc:
                    self.blocked = True
                    log.warning("[%s] blocked (%s); skipping this source for the rest of the run",
                                self.name, exc)
                except Exception:  # noqa: BLE001 - one failing query must not stop the run
                    log.exception("[%s] query %r failed", self.name, query)
        finally:
            self._budget_end = None  # detail pages only obey the global deadline
        seen: set[str] = set()
        result = []
        for job in jobs:  # the same ad often shows up under several queries
            if job.uid not in seen:
                seen.add(job.uid)
                result.append(job)
        log.info("[%s] %d cards", self.name, len(result))
        if not result and not self.blocked:
            log.warning("[%s] 0 cards from %d requests (last: %s) - empty results, layout change or soft block?",
                        self.name, self._n_requests, self._last_status or "no response")
        return result

    def get_or_block(self, url: str, block_status: Iterable[int] = (403, 429, 999),
                     **kwargs: Any) -> requests.Response:
        """Single polite GET for sites that block scrapers: a blocking status raises SourceBlocked
        instead of being retried (retrying a 429/999 only makes the block longer)."""
        self._check_budget()
        self._polite_wait()
        if not self.accept_cookies:
            self._clear_cookies()
        try:
            resp = self.session.get(url, timeout=self.timeout, **kwargs)
        except requests.RequestException:
            self._record(False)
            raise
        self._record(resp.status_code < 500)
        if resp.status_code in set(block_status):
            raise SourceBlocked(f"HTTP {resp.status_code} for {url.split('?')[0]}")
        resp.raise_for_status()
        return resp

    def save_raw(self, html: str, stem: str) -> None:
        if self.raw_dir is None:
            return
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in stem)[:80] or "page"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / f"{safe}.html").write_text(html, encoding="utf-8")

    @abstractmethod
    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        """Return jobs for a search query (already limited to recent ads via URL params if possible)."""

    def parse_html(self, html: str, today: Optional[date] = None) -> list[Job]:
        """Parse a saved listing page (used by ``--sample-html`` for offline runs)."""
        raise NotImplementedError(f"{self.name} does not support parsing saved HTML")

    def _polite_wait(self) -> None:
        if self._last_request is not None:
            self._sleep(random.uniform(*self.delay_range))
        self._last_request = time.monotonic()

    def _save_raw(self, resp: requests.Response) -> None:
        """Keep the first few responses of each source in the output artifact for debugging."""
        if self.raw_dir is None or self._n_requests > 3:
            return
        try:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            (self.raw_dir / f"resp-{self._n_requests}-{resp.status_code}.html").write_text(
                (resp.text or "")[:500000], encoding="utf-8")
        except (OSError, AttributeError, TypeError):
            pass

    def _log_refusal(self, url: str, resp: requests.Response) -> None:
        """Once per run: say who refused us (Cloudflare challenge, WAF ...) so the cause is visible."""
        if self._refusal_logged:
            return
        self._refusal_logged = True
        text = resp.text or ""
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip()[:80] if m else ""
        server = resp.headers.get("server", "")
        hints = [h for h in ("cf-ray", "cf-mitigated", "x-akamai", "x-amz-cf-id", "x-iinfo") if h in resp.headers]
        log.warning("[%s] HTTP %s refused %s (server=%r, page title=%r, headers=%s)",
                    self.name, resp.status_code, url, server, title, ",".join(hints) or "-")
        if self.raw_dir is not None:
            self.raw_dir.mkdir(parents=True, exist_ok=True)
            (self.raw_dir / f"refused-{resp.status_code}.html").write_text(text[:200000], encoding="utf-8")

    def get(self, url: str, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> requests.Response:
        """GET with a random 2-5s delay between requests, timeout and retries with backoff."""
        last_exc: Optional[BaseException] = None
        attempts = self.retries
        attempt = 0
        while attempt < attempts:
            attempt += 1
            self._check_budget()
            self._polite_wait()
            if not self.accept_cookies:
                self._clear_cookies()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout, **kwargs)
                self._n_requests += 1
                self._last_status = f"HTTP {resp.status_code}, {len(getattr(resp, 'text', '') or '')} chars"
                self._save_raw(resp)
            except requests.RequestException as exc:
                last_exc = exc
                self._record(False)
                if isinstance(exc, requests.Timeout):
                    attempts = min(attempts, TIMEOUT_RETRIES)
                log.warning("[%s] GET %s failed (attempt %d/%d): %s", self.name, url, attempt, attempts, exc)
            else:
                if resp.status_code not in RETRY_STATUS:
                    self._record(resp.status_code < 400)
                    if resp.status_code in (401, 403):
                        self._log_refusal(url, resp)
                    resp.raise_for_status()
                    return resp
                self._record(False)
                last_exc = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                log.warning("[%s] GET %s -> HTTP %d (attempt %d/%d)",
                            self.name, url, resp.status_code, attempt, attempts)
            if attempt < attempts:
                self._sleep(5.0 * attempt)  # extra backoff on top of the polite delay
        assert last_exc is not None
        raise last_exc
