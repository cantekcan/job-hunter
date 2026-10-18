"""Scraper base class with a polite HTTP helper."""
from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional

import requests

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


class BaseScraper(ABC):
    """Subclasses set ``name`` and implement :meth:`fetch` (and ideally :meth:`parse_html`)."""

    name: str = "base"

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

    @abstractmethod
    def fetch(self, query: str, max_pages: int = 1) -> list[Job]:
        """Return jobs for a search query (already limited to recent ads via URL params if possible)."""

    def parse_html(self, html: str) -> list[Job]:
        """Parse a saved listing page (used by ``--sample-html`` for offline runs)."""
        raise NotImplementedError(f"{self.name} does not support parsing saved HTML")

    def _polite_wait(self) -> None:
        if self._last_request is not None:
            self._sleep(random.uniform(*self.delay_range))
        self._last_request = time.monotonic()

    def get(self, url: str, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> requests.Response:
        """GET with a random 2-5s delay between requests, timeout and retries with backoff."""
        last_exc: Optional[BaseException] = None
        for attempt in range(1, self.retries + 1):
            self._polite_wait()
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout, **kwargs)
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("[%s] GET %s failed (attempt %d/%d): %s", self.name, url, attempt, self.retries, exc)
            else:
                if resp.status_code not in RETRY_STATUS:
                    resp.raise_for_status()
                    return resp
                last_exc = requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                log.warning("[%s] GET %s -> HTTP %d (attempt %d/%d)",
                            self.name, url, resp.status_code, attempt, self.retries)
            if attempt < self.retries:
                self._sleep(5.0 * attempt)  # extra backoff on top of the polite delay
        assert last_exc is not None
        raise last_exc
