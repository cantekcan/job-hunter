import pytest
import requests

from src.scrapers.base import BaseScraper, SourceBlocked
from tests.conftest import FakeResponse


class Session:
    def __init__(self, behaviour):
        self.behaviour, self.urls, self.headers = behaviour, [], {}

    def get(self, url, params=None, timeout=None, **kw):
        self.urls.append(url)
        return self.behaviour(url)


class S(BaseScraper):
    name = "s"

    def fetch(self, query, max_pages=1):
        self.get(f"https://example.com/{query}")
        return []


class Cfg:
    search_queries = ["a", "b", "c", "d"]
    max_pages = 1
    source_time_budget_s = 100


def _timeout(url):
    raise requests.Timeout("read timeout")


def test_timeouts_retried_twice_then_breaker_trips():
    s = S(session=Session(_timeout), sleep=lambda _: None)
    s.fetch_all(Cfg())
    assert len(s.session.urls) == 3 and s.blocked  # 2 attempts for "a", 1 for "b", then skipped


def test_success_resets_breaker():
    calls = iter([FakeResponse(500), FakeResponse(500), FakeResponse(200, text="ok")] * 3)
    s = S(session=Session(lambda u: next(calls)), sleep=lambda _: None)
    s.fetch_all(Cfg())
    assert not s.blocked and s.consecutive_failures == 0


def test_time_budget_and_deadline():
    now = [0.0]
    s = S(session=Session(lambda u: (now.__setitem__(0, now[0] + 60), FakeResponse(200, text=""))[1]),
          sleep=lambda _: None)
    s._clock = lambda: now[0]
    s.fetch_all(Cfg())  # budget 100s, each request "takes" 60s -> 2 queries, rest skipped
    assert len(s.session.urls) == 2 and s.blocked

    late = S(session=Session(lambda u: FakeResponse(200)), sleep=lambda _: None)
    late.deadline = -1.0
    with pytest.raises(SourceBlocked):
        late.get("https://example.com/x")
    assert late.session.urls == []
