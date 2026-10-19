from datetime import date
from pathlib import Path

from src.config import load_config
from src.scrapers import SCRAPERS
from src.scrapers import secretcv as S
from tests.conftest import FakeResponse

FIX = Path(__file__).parent / "fixtures"
T = date(2026, 10, 19)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_registered():
    assert SCRAPERS["secretcv"] is S.SecretcvScraper


def test_parse_cards():
    jobs = S.SecretcvScraper().parse_html(load("secretcv_list.html"), T)
    assert [j.external_id for j in jobs] == ["1882116", "1882160", "1882140", "1883001", "1883002"]
    first = jobs[0]
    assert (first.title, first.company, first.location) == (
        "Boyner İstanbul Neomarin AVM - Kasiyer Full Time", "Boyner Büyük Mağazacılık", "İstanbul Anadolu")
    assert first.posted_text == "3 gün önce" and first.posted_date == date(2026, 10, 16)
    sponsored = jobs[3]
    assert sponsored.company == "Firma Adı Gizli" and sponsored.posted_date is None
    plain = jobs[4]  # text-order fallback
    assert (plain.title, plain.company, plain.location, plain.posted_date) == (
        "Backend Developer (C#)", "XYZ Fintech", "İstanbul Avrupa", T)
    assert plain.url == "https://www.secretcv.com/xyz-fintech/backend-developer-c-is-ilanlari-1883002"
    assert all(j.uid.startswith("secretcv:") for j in jobs)


def test_ids_and_urls():
    assert S.extract_id("/porland/magaza-is-ilanlari-1882140") == "1882140"
    assert S.extract_id("/is-ilanlari/istanbul-is-ilanlari/?sf=2") is None
    assert S.list_url("istanbul-is-ilanlari", 2) == "https://www.secretcv.com/is-ilanlari/istanbul-is-ilanlari?sf=2"


def test_no_results():
    html = ('<!DOCTYPE html><html lang="tr"><head><title>x</title></head><body>'
            '<p>Arama kriterlerinize ait ilan bulunamadı!</p></body></html>')
    assert S.SecretcvScraper().parse_html(html, T) == []


def test_detail():
    job = S.SecretcvScraper().parse_html(load("secretcv_list.html"), T)[3]
    S.parse_detail(load("secretcv_detail.html"), job)
    assert job.posted_date == date(2026, 10, 16)
    assert job.description.startswith("İş Açıklaması") and "RabbitMQ" in job.description
    assert "Firma bilgisi" not in job.description


def test_fetch_paginates():
    class Session:
        headers: dict = {}
        urls: list = []

        def get(self, url, params=None, timeout=None, **kw):
            self.urls.append(url)
            return FakeResponse(200, text=load("secretcv_list.html") if "sf=" not in url else "<html></html>")

    s = S.SecretcvScraper(session=Session(), sleep=lambda _: None)
    s.today = T
    s.configure(load_config(root=Path("/nonexistent"), env={}))
    jobs = s.fetch_all()
    assert len(jobs) == 5
    assert s.session.urls == ["https://www.secretcv.com/is-ilanlari/istanbul-is-ilanlari",
                              "https://www.secretcv.com/is-ilanlari/istanbul-is-ilanlari?sf=2"]
