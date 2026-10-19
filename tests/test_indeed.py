from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from src.config import load_config
from src.scrapers import SCRAPERS
from src.scrapers import indeed as I
from src.scrapers.base import SourceBlocked
from tests.conftest import FakeResponse

FIX = Path(__file__).parent / "fixtures"
T = date(2026, 10, 19)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


class Session:
    def __init__(self, resp):
        self.resp, self.urls, self.headers = resp, [], {}

    def get(self, url, timeout=None, **kw):
        self.urls.append(url)
        return self.resp(url) if callable(self.resp) else self.resp


def scraper(resp, queries=("c#",), locations=("Türkiye",)):
    s = I.IndeedScraper(session=Session(resp), sleep=lambda _: None)
    s.today = T
    cfg = load_config(root=Path("/nonexistent"), env={})
    cfg.indeed_queries, cfg.indeed_locations, cfg.max_pages = list(queries), list(locations), 3
    s.configure(cfg)
    return s


def test_registered():
    assert SCRAPERS["indeed"] is I.IndeedScraper


def test_parse_embedded_json():
    jobs = I.IndeedScraper().parse_html(load("indeed_list.html"), T)
    assert [j.external_id for j in jobs] == ["ad8cbce77652e9c0", "ddd15c91e2bd2ba8", "74baf3f22ce04a2e",
                                             "1b2c3d4e5f607182"]
    first = jobs[0]
    assert (first.title, first.company, first.location, first.posted_date) == (
        ".NET Developer", "ISCOM", "İstanbul", T)
    assert first.url == "https://tr.indeed.com/viewjob?jk=ad8cbce77652e9c0" and first.uid == "indeed:ad8cbce77652e9c0"
    assert jobs[1].posted_date == date(2026, 10, 18) and jobs[2].posted_date == date(2026, 10, 16)
    assert jobs[3].work_model == "uzaktan"


def test_parse_html_fallback():
    jobs = I.IndeedScraper().parse_html(load("indeed_list_html_only.html"), T)
    assert [(j.external_id, j.title, j.company) for j in jobs] == [
        ("aaaa111122223333", "Senior .NET Developer", "Gamma Teknoloji"),
        ("bbbb444455556666", "C# Yazılım Uzmanı", "Sigma Yazılım")]
    assert jobs[0].posted_text == "Bugün" and jobs[0].posted_date == T and jobs[0].location == "Maslak, İstanbul"
    assert jobs[1].posted_date == date(2026, 10, 17) and jobs[1].work_model == "hibrit"


def test_search_url():
    q = parse_qs(urlsplit(I.search_url("c#", "İstanbul", 10)).query)
    assert q == {"q": ["c#"], "l": ["İstanbul"], "fromage": ["3"], "sort": ["date"], "start": ["10"]}


def test_challenge_page_raises_blocked():
    with pytest.raises(SourceBlocked):
        I.IndeedScraper().parse_html(load("indeed_challenge.html"), T)


@pytest.mark.parametrize("resp", [FakeResponse(403, text="Forbidden"), FakeResponse(429),
                                  FakeResponse(200, text=load("indeed_challenge.html"))])
def test_block_skips_indeed(resp):
    s = scraper(resp, queries=("c#", ".net", "backend"))
    assert s.fetch_all() == [] and s.blocked
    assert len(s.session.urls) == 1


def test_no_results_page_is_not_a_block():
    html = ('<!DOCTYPE html><html lang="tr"><head><title>x</title></head><body>'
            '<h1>c# iş ilanı aramanız hiçbir iş ilanıyla eşleşmedi</h1></body></html>')
    s = scraper(FakeResponse(200, text=html), queries=("c#", ".net"))
    assert s.fetch_all() == [] and not s.blocked and len(s.session.urls) == 2


def test_fetch_detail():
    detail = ('<!DOCTYPE html><html lang="tr"><head><title>d</title></head><body>'
              '<div id="jobDescriptionText"><p>C# ve .NET ile mikroservis geliştirecek ekip arkadaşı arıyoruz.</p></div>'
              '</body></html>')
    s = scraper(FakeResponse(200, text=detail))
    job = I.IndeedScraper().parse_html(load("indeed_list.html"), T)[0]
    s.fetch_detail(job)
    assert "mikroservis" in job.description and job.language == "tr"
    assert s.session.urls == ["https://tr.indeed.com/viewjob?jk=ad8cbce77652e9c0"]
