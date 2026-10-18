import json
from datetime import date
from pathlib import Path

import pytest

from src import main as M
from src.config import load_config
from src.scrapers import SCRAPERS
from src.scrapers import kariyernet as K
from tests.conftest import FakeResponse

FIX = Path(__file__).parent / "fixtures"
T = date(2026, 10, 18)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture
def jobs():
    return K.KariyerNetScraper().parse_html(load("kariyernet_list.html"), T)


def test_registered():
    assert SCRAPERS["kariyernet"] is K.KariyerNetScraper


def test_parse_list_ids_and_dedupe(jobs):
    assert [j.external_id for j in jobs] == [
        "4578674", "2496842", "4581001", "4581102", "4581203", "4579304", "4581405", "4580906"]
    assert all(j.source == "kariyernet" and j.uid == f"kariyernet:{j.external_id}" for j in jobs)
    # sponsored duplicate dropped in favour of the regular card
    assert "sponsored" not in jobs[0].flags


def test_related_ads_ignored(jobs):
    assert not {"4000001", "4000002"} & {j.external_id for j in jobs}


def test_card_fields(jobs):
    by = {j.external_id: j for j in jobs}
    lead = by["4578674"]
    assert (lead.title, lead.company, lead.location, lead.work_model) == (
        ".Net Lead Developer", "Turkcell ve Grup Şirketleri", "İstanbul (Tümü)", "hibrit")
    assert lead.posted_text == "1 saat" and lead.posted_date == T
    assert by["2496842"].work_model == "uzaktan" and by["2496842"].posted_date == T  # "Bugün"
    assert by["4581001"].location == "İstanbul(Asya) +1 il daha" and by["4581001"].posted_date == date(2026, 10, 17)
    assert by["4579304"].posted_date == date(2026, 10, 16)  # "2 gün"
    assert by["4581102"].title == "Java Developer" and by["4581102"].work_model == "iş yerinde"
    plain = by["4581405"]  # no class hints: text-order fallback, repeated company dropped
    assert (plain.title, plain.company, plain.location, plain.work_model, plain.posted_text) == (
        "Kıdemli Yazılım Geliştirici", "Gamma Teknoloji", "Ankara", "uzaktan", "6 saat")
    two_links = by["4580906"]
    assert two_links.title == "Full Stack Developer (.NET / JavaScript)"
    assert two_links.company == "Sigma Ödeme Sistemleri" and two_links.location == "İstanbul(Avr.)"


def test_url_normalization(jobs):
    assert all(j.url.startswith("https://www.kariyer.net/is-ilani/") for j in jobs)
    assert all("?" not in j.url and "#" not in j.url for j in jobs)
    assert K.normalize_url("https://akdeniz.kariyer.net/is-ilani/a-b-123?x=1#y") == \
        "https://www.kariyer.net/is-ilani/a-b-123"
    assert K.normalize_url("/is-ilani/a--net-dev-9") == "https://www.kariyer.net/is-ilani/a--net-dev-9"
    assert K.extract_id("/is-ilani/turkcell--net-lead-developer-4578674?ref=x") == "4578674"
    assert K.extract_id("/is-ilanlari/istanbul-2") is None


def test_sponsored_kept_when_not_duplicate():
    html = ('<div><a href="/is-ilani/firma-senior-net-developer-111"><span>Sponsorlu İlan</span>'
            '<span>Firma</span><span>Senior .NET Developer</span><span>İstanbul</span><span>Hibrit</span>'
            '<span>Tam zamanlı</span><span>2 saat</span></a></div>')
    [job] = K.KariyerNetScraper().parse_html(html, T)
    assert job.title == "Senior .NET Developer" and job.company == "Firma" and "sponsored" in job.flags


def test_no_results_page():
    assert K.KariyerNetScraper().parse_html(load("kariyernet_noresults.html"), T) == []


def test_search_url():
    assert K.search_url(".NET Developer") == "https://www.kariyer.net/is-ilanlari/net+developer"
    assert K.search_url("Yazılım Uzmanı .NET", page=2) == \
        "https://www.kariyer.net/is-ilanlari/yazilim+uzmani+net-2"
    assert K.search_url("c# developer", date_params={"p": "1"}) == \
        "https://www.kariyer.net/is-ilanlari/c+developer?p=1"
    assert K.DATE_PARAMS == {}


def test_embedded_ld_json_preferred():
    ld = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Senior .NET Developer",
          "identifier": {"@type": "PropertyValue", "value": "555"}, "datePosted": "2026-10-18",
          "url": "https://www.kariyer.net/is-ilani/acme-senior-net-developer-555",
          "hiringOrganization": {"@type": "Organization", "name": "Acme"},
          "jobLocation": {"@type": "Place", "address": {"addressLocality": "İstanbul"}},
          "description": "<p>C# ve .NET ile mikroservis geliştirecek ekip arkadaşı arıyoruz.</p>"}
    html = (f'<script type="application/ld+json">{json.dumps(ld)}</script>'
            '<a href="/is-ilani/other-1">Other</a>')
    [job] = K.KariyerNetScraper().parse_html(html, T)
    assert (job.external_id, job.company, job.location, job.posted_date) == ("555", "Acme", "İstanbul", T)
    assert "mikroservis" in job.description and job.language == "tr"


def test_embedded_state_blob():
    state = {"search": {"items": [
        {"positionId": 777, "title": ".NET Developer", "companyName": "Beta", "locationText": "İstanbul(Asya)",
         "workModelText": "Uzaktan / Remote", "jobDateStatus": "Bugün",
         "detailPageUrl": "/is-ilani/beta-net-developer-777"},
        {"positionId": 777, "title": ".NET Developer", "companyName": "Beta"},  # duplicate
    ]}}
    html = f"<script>window.__INITIAL_STATE__ = {json.dumps(state)};</script>"
    [job] = K.KariyerNetScraper().parse_html(html, T)
    assert (job.external_id, job.work_model, job.posted_date) == ("777", "uzaktan", T)
    assert job.url == "https://www.kariyer.net/is-ilani/beta-net-developer-777"


def test_parse_detail():
    job = K.KariyerNetScraper().parse_html(load("kariyernet_list.html"), T)[0]
    K.parse_detail(load("kariyernet_detail.html"), job)
    assert job.posted_date == date(2026, 10, 14)  # lastPublishDate
    assert job.description.startswith("İş İlanı Hakkında")
    assert "RabbitMQ" in job.description and "5 - 14 yıl arası" in job.description
    assert "Şirket Hakkında" not in job.description and "Başka Firma" not in job.description
    assert job.language == "tr"


class FakeSession:
    def __init__(self, pages):
        self.pages, self.urls, self.headers = pages, [], {}

    def get(self, url, params=None, timeout=None, **kw):
        self.urls.append(url)
        return FakeResponse(200, text=self.pages.get(url, "<html></html>"))


def test_fetch_paginates_and_stops(monkeypatch):
    list_html = load("kariyernet_list.html")
    pages = {"https://www.kariyer.net/is-ilanlari/net+developer": list_html,
             "https://www.kariyer.net/is-ilanlari/net+developer-2": load("kariyernet_noresults.html")}
    sess = FakeSession(pages)
    scraper = K.KariyerNetScraper(session=sess, sleep=lambda s: None)
    jobs = scraper.fetch(".net developer", max_pages=3)
    assert len(jobs) == 8
    assert sess.urls == list(pages)  # stopped after the empty page 2
    assert sess.headers["Accept-Language"].startswith("tr-TR")


def test_fetch_detail_uses_http(monkeypatch):
    sess = FakeSession({"https://www.kariyer.net/is-ilani/x-1": load("kariyernet_detail.html")})
    job = K.KariyerNetScraper(session=sess, sleep=lambda s: None).parse_html(
        '<a href="/is-ilani/x-1"><span>F</span><span>T</span></a>', T)[0]
    K.KariyerNetScraper(session=sess, sleep=lambda s: None).fetch_detail(job)
    assert "Ne Bekliyoruz?" in job.description


def test_pipeline_sample_html(tmp_path, capsys):
    """Equivalent of: python -m src.main --dry-run --no-ai --sample-html tests/fixtures/kariyernet_list.html --print 5"""
    cfg = load_config(root=tmp_path, env={})
    cfg.exclude_title_keywords = ["junior", "java"]
    args = M.parse_args(["--dry-run", "--no-ai", "--sample-html", str(FIX / "kariyernet_list.html"), "--print", "5"])
    assert M.run(args, cfg, T) == 0
    out = capsys.readouterr().out
    rows = [ln for ln in out.splitlines() if "kariyernet:" in ln]
    assert len(rows) == 5
    assert "Java Developer" not in out and "Junior" not in out and "4579304" not in out
    report = (tmp_path / "output" / T.isoformat() / "report.md").read_text(encoding="utf-8")
    assert report.count("kariyer.net/is-ilani/") == 5
    assert "Bulunan: 8" in (tmp_path / "output" / T.isoformat() / "telegram_dryrun.txt").read_text("utf-8")
    assert not cfg.db_path.exists()


def test_details_fetched_only_with_ai(tmp_path, monkeypatch):
    calls = []

    class Scr(K.KariyerNetScraper):
        def fetch(self, query, max_pages=1):
            return self.parse_html(load("kariyernet_list.html"), T)

        def fetch_detail(self, job):
            calls.append(job.uid)
            job.description = "C# .NET"
            return job

    class Chain:
        def __bool__(self):
            return True

        def complete(self, system, user, json_mode=False, strong=False):
            return '{"score": 10}'

    monkeypatch.setattr(M, "SCRAPERS", {"kariyernet": Scr})
    cfg = load_config(root=tmp_path, env={})
    cfg.search_queries = ["q"]
    cfg.exclude_title_keywords = ["junior", "java"]
    cfg.max_details = 2
    assert M.run(M.parse_args(["--dry-run", "--no-ai"]), cfg, T) == 0
    assert calls == []
    monkeypatch.setattr(M, "build_chain", lambda c: Chain())
    assert M.run(M.parse_args(["--dry-run"]), cfg, T) == 0
    assert len(calls) == 2
