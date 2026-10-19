from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src import main as M
from src.config import load_config
from src.scrapers import SCRAPERS, BaseScraper
from src.scrapers import linkedin as L
from src.scrapers.base import SourceBlocked
from tests.conftest import FakeResponse

FIX = Path(__file__).parent / "fixtures"
T = date(2026, 10, 19)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


class Session:
    """Routes GETs by URL prefix; records every request (no network)."""

    def __init__(self, routes):
        self.routes, self.urls, self.headers, self.cookies = routes, [], {}, {}

    def get(self, url, timeout=None, **kw):
        self.urls.append(url)
        for prefix, resp in self.routes:
            if url.startswith(prefix):
                return resp(url) if callable(resp) else resp
        return FakeResponse(200, text="")


def scraper(routes, **cfg_overrides):
    s = L.LinkedInScraper(session=Session(routes), sleep=lambda _: None)
    s.today = T
    cfg = load_config(root=Path("/nonexistent"), env={})
    cfg.linkedin_queries = [".NET Developer"]
    cfg.linkedin_locations = ["Istanbul, Türkiye"]
    for k, v in cfg_overrides.items():
        setattr(cfg, k, v)
    cfg.max_pages = 2
    s.configure(cfg)
    return s


def test_registered():
    assert SCRAPERS["linkedin"] is L.LinkedInScraper


def test_parse_cards_ids_dates_urls():
    jobs = L.parse_cards(load("linkedin_list.html"), T)
    assert [j.external_id for j in jobs] == ["4012345678", "4012345679", "4012345680", "4012345681"]  # dupe dropped
    first = jobs[0]
    assert (first.title, first.company, first.location) == ("Senior .NET Developer", "XYZ Fintech",
                                                          "Istanbul, İstanbul, Türkiye")
    assert first.posted_date == T and first.uid == "linkedin:4012345678"
    assert first.url == "https://www.linkedin.com/jobs/view/senior-net-developer-at-xyz-fintech-4012345678"
    assert all("?" not in j.url and j.url.startswith("https://www.linkedin.com/jobs/view/") for j in jobs)
    assert jobs[1].work_model == "uzaktan" and jobs[3].work_model == "hibrit"
    assert jobs[2].external_id == "4012345680"  # id from href when there is no data-entity-urn
    assert jobs[3].posted_date == date(2026, 10, 16)


def test_bare_li_fragment_parses():
    li = load("linkedin_list.html").split('<ul class="jobs-search__results-list">')[1].split("</ul>")[0]
    assert len(L.parse_cards(li, T)) == 4


def test_search_url_params():
    q = parse_qs(urlsplit(L.search_url(".NET Developer", "Türkiye|f_WT=2", 10)).query)
    assert q["keywords"] == [".NET Developer"] and q["location"] == ["Türkiye"]
    assert q["f_TPR"] == ["r86400"] and q["sortBy"] == ["DD"] and q["start"] == ["10"] and q["f_WT"] == ["2"]
    assert L.search_url("x", "Istanbul, Türkiye").startswith(L.LIST_URL)


def test_fetch_pages_and_remote_location():
    page = FakeResponse(200, text=load("linkedin_list.html"))
    s = scraper([(L.LIST_URL, page)], linkedin_locations=["Türkiye|f_WT=2"])
    jobs = s.fetch_all()
    assert len(jobs) == 4 and all(j.work_model == "uzaktan" for j in jobs)
    assert len(s.session.urls) == 1  # 4 < 10 cards -> no second page
    assert "cookie" not in {k.lower() for k in s.session.headers}


@pytest.mark.parametrize("resp", [FakeResponse(429, text="slow"), FakeResponse(999, text=""),
                                  FakeResponse(200, text=load("linkedin_authwall.html"))])
def test_block_stops_linkedin(resp):
    s = scraper([(L.LIST_URL, resp)], linkedin_queries=["a", "b", "c"])
    assert s.fetch_all() == []
    assert s.blocked and len(s.session.urls) == 1  # remaining queries skipped


def test_redirect_to_authwall_blocks():
    resp = FakeResponse(200, text="<html></html>")
    resp.url = "https://www.linkedin.com/authwall?trk=x"
    with pytest.raises(SourceBlocked):
        scraper([(L.LIST_URL, resp)])._get(L.search_url("a", "b"))


def test_request_cap():
    s = scraper([(L.LIST_URL, FakeResponse(200, text="<ul></ul>"))], linkedin_queries=[str(i) for i in range(50)])
    s.fetch_all()
    assert len(s.session.urls) == L.MAX_REQUESTS and s.blocked


def test_fetch_detail():
    s = scraper([(L.BASE_URL + "/jobs-guest/jobs/api/jobPosting/", FakeResponse(200, text=load("linkedin_detail.html")))])
    job = L.parse_cards(load("linkedin_list.html"), T)[0]
    s.fetch_detail(job)
    assert "payments team" in job.description and "Mid-Senior level" in job.description
    assert job.language == "en"
    assert s.session.urls == [L.BASE_URL + "/jobs-guest/jobs/api/jobPosting/4012345678"]


def test_fetch_detail_blocked_is_soft():
    s = scraper([(L.BASE_URL, FakeResponse(429))])
    job = L.parse_cards(load("linkedin_list.html"), T)[0]
    assert s.fetch_detail(job) is job and job.description == "" and s.blocked


class _Blocked(BaseScraper):
    name = "blocked"

    def fetch(self, query, max_pages=1):
        raise SourceBlocked("HTTP 999")


class _Boom(BaseScraper):
    name = "boom"

    def fetch(self, query, max_pages=1):
        return []

    def fetch_all(self, cfg=None):
        raise RuntimeError("parser exploded")


class _Ok(BaseScraper):
    name = "ok"

    def fetch(self, query, max_pages=1):
        return L.parse_cards(load("linkedin_list.html"), T)


def test_blocked_source_does_not_stop_others(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(M, "SCRAPERS", {"blocked": _Blocked, "boom": _Boom, "ok": _Ok})
    cfg = load_config(root=tmp_path, env={})
    cfg.search_queries = ["q"]
    cfg.exclude_title_keywords = ["java"]
    assert M.run(M.parse_args(["--dry-run", "--no-ai", "--print", "10"]), cfg, T) == 0
    report = (tmp_path / "output" / T.isoformat() / "report.md").read_text(encoding="utf-8")
    assert report.count("linkedin.com/jobs/view/") == 2  # 4 cards - Java - 3-day-old one
    assert "[blocked] blocked" in caplog.text and "Scraper boom failed" in caplog.text


def test_default_sources_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SCRAPERS", {"ok": _Ok, "blocked": _Blocked})
    cfg = load_config(root=tmp_path, env={})
    cfg.sources = ["ok", "nope"]
    assert M.default_sources(cfg) == ["ok"]
    cfg.sources = []
    assert M.default_sources(cfg) == ["ok", "blocked"]


def test_sample_html_routes_to_matching_scraper(tmp_path, capsys):
    cfg = load_config(root=tmp_path, env={})
    cfg.exclude_title_keywords = ["java"]
    args = M.parse_args(["--dry-run", "--no-ai", "--sample-html", str(FIX / "linkedin_list.html"), "--print", "9"])
    assert M.run(args, cfg, T) == 0
    out = capsys.readouterr().out
    assert out.count("linkedin:") == 2 and "kariyernet:" not in out
