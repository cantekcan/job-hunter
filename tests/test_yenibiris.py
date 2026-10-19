from datetime import date
from pathlib import Path

from src import main as M
from src.config import load_config
from src.scrapers import SCRAPERS
from src.scrapers import yenibiris as Y

FIX = Path(__file__).parent / "fixtures"
T = date(2026, 10, 19)


def load(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_registered():
    assert SCRAPERS["yenibiris"] is Y.YenibirisScraper


def test_parse_cards_and_dates():
    jobs = Y.YenibirisScraper().parse_html(load("yenibiris_list.html"), T)
    assert [j.external_id for j in jobs] == ["1220282", "1220921", "1222191", "926914"]
    first = jobs[0]
    assert (first.title, first.company, first.location, first.posted_date) == (
        "Yazılım Geliştirme Uzmanı", "Beş Yıldız Eğitim Kurumları", "İstanbul Avrupa Yakası - Başakşehir",
        date(2026, 9, 17))
    assert jobs[2].posted_text == "Son 1 Hafta" and jobs[2].posted_date is None  # coarse label -> dedupe
    plain = jobs[3]
    assert (plain.title, plain.company, plain.location, plain.posted_date) == (
        ".NET Developer", "Omega Yazılım", "İstanbul Anadolu Yakası - Ataşehir", date(2026, 10, 9))
    assert plain.url == "https://www.yenibiris.com/is-ilani/net-developer/926914"
    assert all(j.uid.startswith("yenibiris:") for j in jobs)


def test_ids():
    assert Y.extract_id("https://www.yenibiris.com/is-ilani/net-developer/926914") == "926914"
    assert Y.extract_id("/is-ilanlari/yazilim?sayfa=2") is None
    assert Y.list_url("yazilim", 3) == "https://www.yenibiris.com/is-ilanlari/yazilim?sayfa=3"


def test_detail():
    job = Y.YenibirisScraper().parse_html(load("yenibiris_list.html"), T)[3]
    Y.parse_detail(load("yenibiris_detail.html"), job)
    assert job.posted_date == date(2026, 10, 18)
    assert job.description.startswith("İş Tanımı") and "Entity Framework" in job.description
    assert "Omega Yazılım" not in job.description


def test_sample_pipeline_keeps_undated_and_drops_old(tmp_path, capsys):
    cfg = load_config(root=tmp_path, env={})
    cfg.include_title_keywords = []  # everything relevant, to isolate the date rule
    args = M.parse_args(["--dry-run", "--no-ai", "--sample-html", str(FIX / "yenibiris_list.html"), "--print", "9"])
    assert M.run(args, cfg, T) == 0
    rows = [ln for ln in capsys.readouterr().out.splitlines() if "yenibiris:" in ln]
    # 17.09 / 11.09 / 9.10 are older than a day; "Son 1 Hafta" has no date -> kept for first-seen dedupe
    assert len(rows) == 1 and "yenibiris:1222191" in rows[0]
