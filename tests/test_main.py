import json

from src import main as M
from src.config import load_config
from src.scrapers.base import BaseScraper
from tests.conftest import TODAY, make_job


class FakeScraper(BaseScraper):
    name = "fake"

    def fetch(self, query, max_pages=1):
        return [
            make_job(source="fake", external_id="good", posted_text="Bugün"),
            make_job(source="fake", external_id="mid", title="Backend Developer", posted_text="Dün"),
            make_job(source="fake", external_id="java", title="Java Developer", posted_text="Bugün"),
            make_job(source="fake", external_id="old", posted_text="5 gün önce"),
        ]


class FakeChain:
    def __bool__(self):
        return True

    def complete(self, system, user, json_mode=False, strong=False):
        if strong:
            return "Merhaba,\nÖn yazı metni.\nCan Tekcan"
        score = 85 if "Senior .NET" in user else 55
        return json.dumps({"score": score, "eslesen": [".NET"], "eksik": [], "ozet": "ok", "dil": "tr"})


def test_pipeline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SCRAPERS", {"fake": FakeScraper})
    monkeypatch.setattr(M, "build_chain", lambda cfg: FakeChain())
    cfg = load_config(root=tmp_path, env={})
    cfg.search_queries = ["q"]

    assert M.run(M.parse_args([]), cfg, TODAY) == 0
    day = tmp_path / "output" / TODAY.isoformat()
    dry = (day / "telegram_dryrun.txt").read_text(encoding="utf-8")
    assert "85/100" in dry and "55/100" in dry and "Java Developer" not in dry
    assert "📄 ön yazı ekte" in dry and "Bulunan: 4" in dry and "Yeni: 2" in dry
    letters = [p for p in day.glob("*.md") if p.name != "report.md"]
    assert len(letters) == 1
    report = (day / "report.md").read_text(encoding="utf-8")
    assert report.index("85") < report.index("55")

    # second run: everything already seen -> nothing new
    (day / "telegram_dryrun.txt").unlink()
    assert M.run(M.parse_args([]), cfg, TODAY) == 0
    assert "Yeni: 0" in (day / "telegram_dryrun.txt").read_text(encoding="utf-8")


def test_dry_run_no_ai_does_not_persist(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SCRAPERS", {"fake": FakeScraper})
    cfg = load_config(root=tmp_path, env={})
    cfg.search_queries = ["q"]
    assert M.run(M.parse_args(["--dry-run", "--no-ai"]), cfg, TODAY) == 0
    assert not cfg.db_path.exists()
    assert "Yeni: 2" in (tmp_path / "output" / TODAY.isoformat() / "telegram_dryrun.txt").read_text("utf-8")


def test_empty_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "SCRAPERS", {})
    cfg = load_config(root=tmp_path, env={})
    assert M.run(M.parse_args(["--dry-run", "--no-ai", "--sources", "kariyernet"]), cfg, TODAY) == 0
