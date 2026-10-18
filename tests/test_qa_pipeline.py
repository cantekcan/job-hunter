"""QA: end-to-end pipeline (fake scraper, mocked HTTP for LLM + Telegram, tmp DB/output)."""
import json
import re
from datetime import timedelta
from unittest import mock

import pytest
import requests

from src import main as M
from src.config import load_config
from src.filter import JobStore
from src.scrapers.base import BaseScraper
from tests.conftest import TODAY, FakeResponse, make_job

SCORES = {"s49": 49, "s50": 50, "s69": 69, "s70": 70, "s95": 95}


class FakeScraper(BaseScraper):
    name = "fake"
    jobs = []

    def fetch(self, query, max_pages=1):
        return [make_job(**j) for j in self.jobs]


def default_jobs():
    return [dict(source="fake", external_id=k, title=f"Senior .NET Developer {k}", posted_text="Bugün",
                 url=f"https://ex.com/{k}") for k in SCORES] + [
        dict(source="fake", external_id="old", title="Senior .NET Developer old", posted_text="2 gün önce"),
        dict(source="fake", external_id="jun", title="JUNİOR .NET Developer", posted_text="Bugün"),
        dict(source="fake", external_id="unk", title="Senior .NET Developer s50 unk", posted_text=""),
    ]


class Http:
    """Routes requests.post: LLM endpoints + Telegram. llm_up=False -> every LLM call times out."""

    def __init__(self, llm_up=True):
        self.llm_up = llm_up
        self.telegram = []
        self.llm_calls = 0

    def __call__(self, url, **kw):
        if "api.telegram.org" in url:
            self.telegram.append((url.rsplit("/", 1)[-1], kw.get("data", {})))
            return FakeResponse(200, {"ok": True})
        self.llm_calls += 1
        if not self.llm_up:
            raise requests.Timeout("timeout")
        user = kw["json"]["messages"][1]["content"] if "messages" in kw["json"] else ""
        if "strong" in kw["json"].get("model", "") or kw["json"].get("model") == "M":
            content = "Merhaba,\nÖn yazı.\nCan"
        else:
            title = re.search(r"Başlık: (.*)", user).group(1)
            key = title.split()[-1] if title.split()[-1] in SCORES else title.split()[-2]
            content = json.dumps({"score": str(SCORES[key]), "eslesen": ["C#"], "eksik": ["Go"], "ozet": "o", "dil": "tr"})
        return FakeResponse(200, {"choices": [{"message": {"content": content}}]})


@pytest.fixture
def setup(tmp_path, monkeypatch):
    FakeScraper.jobs = default_jobs()
    monkeypatch.setattr(M, "SCRAPERS", {"fake": FakeScraper})
    env = {"AI_PROVIDERS": "groq", "GROQ_API_KEY": "k", "GROQ_MODEL": "m", "GROQ_MODEL_STRONG": "M",
           "TELEGRAM_ENABLED": "true", "TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42"}

    def make_cfg(**over):
        c = load_config(root=tmp_path, env={**env, **over})
        c.search_queries = ["q"]
        return c
    return tmp_path, make_cfg


def _sent_titles(http):
    return [d["text"] for m, d in http.telegram if m == "sendMessage" and "/100" in d["text"]]


def test_thresholds_and_two_run_dedupe(setup):
    tmp, make_cfg = setup
    cfg = make_cfg()
    http = Http()
    with mock.patch("requests.post", side_effect=http):
        M.run(M.parse_args([]), cfg, TODAY)
    msgs = _sent_titles(http)
    joined = "\n".join(msgs)
    assert "49/100" not in joined and "old" not in joined and "JUNİOR" not in joined
    for s in ("50/100", "69/100", "70/100", "95/100"):
        assert s in joined
    assert "unk" in joined  # unknown date kept
    docs = [d for m, d in http.telegram if m == "sendDocument"]
    assert len(docs) == 2  # 70 and 95 only
    assert all(("📄" in m) == (("70/100" in m) or ("95/100" in m)) for m in msgs)
    letters = [p for p in (tmp / "output" / "2026-10-18").glob("*.md") if p.name != "report.md"]
    assert len(letters) == 2
    report = (tmp / "output" / "2026-10-18" / "report.md").read_text("utf-8")
    assert "s49" in report  # <50 still in report

    http2 = Http()
    with mock.patch("requests.post", side_effect=http2):
        M.run(M.parse_args([]), cfg, TODAY)
    assert _sent_titles(http2) == [] and http2.llm_calls == 0
    assert [m for m, _ in http2.telegram] == ["sendMessage"]  # summary only
    assert "Yeni: 0" in http2.telegram[0][1]["text"]

    http3 = Http()  # next day, same DB: still nothing re-notified
    with mock.patch("requests.post", side_effect=http3):
        M.run(M.parse_args([]), cfg, TODAY + timedelta(days=1))
    assert _sent_titles(http3) == []


def test_dry_run_with_ai_does_not_persist_or_send(setup):
    tmp, make_cfg = setup
    cfg = make_cfg()
    http = Http()
    with mock.patch("requests.post", side_effect=http):
        M.run(M.parse_args(["--dry-run"]), cfg, TODAY)
    assert http.telegram == [] and http.llm_calls > 0
    assert not cfg.db_path.exists()
    dry = (tmp / "output" / "2026-10-18" / "telegram_dryrun.txt").read_text("utf-8")
    assert "95/100" in dry and "49/100" not in dry


def test_dry_run_does_not_modify_existing_db(setup):
    tmp, make_cfg = setup
    cfg = make_cfg()
    with mock.patch("requests.post", side_effect=Http(llm_up=False)):
        M.run(M.parse_args([]), cfg, TODAY)  # real run, all unscored
    before = cfg.db_path.read_bytes()
    with mock.patch("requests.post", side_effect=Http()):
        M.run(M.parse_args(["--dry-run"]), cfg, TODAY)
    assert cfg.db_path.read_bytes() == before
    with JobStore(cfg.db_path) as s:
        assert s.get("fake:s95")["score"] is None


def test_all_providers_fail_then_retry_next_run(setup):
    tmp, make_cfg = setup
    cfg = make_cfg()
    down = Http(llm_up=False)
    with mock.patch("requests.post", side_effect=down):
        M.run(M.parse_args([]), cfg, TODAY)
    assert _sent_titles(down) == []
    with JobStore(cfg.db_path) as s:
        pend = {j.uid for j in s.pending_unscored(TODAY, 1)}
    assert "fake:s95" in pend and "fake:old" not in pend and "fake:jun" not in pend

    FakeScraper.jobs = []  # ads disappeared from the site; retry must come from the DB
    up = Http()
    with mock.patch("requests.post", side_effect=up):
        M.run(M.parse_args([]), cfg, TODAY + timedelta(days=1))
    joined = "\n".join(_sent_titles(up))
    assert "95/100" in joined and "70/100" in joined
    with JobStore(cfg.db_path) as s:
        assert s.get("fake:s95")["score"] == 95 and s.get("fake:s95")["notified"] == 1


def test_no_telegram_creds_zero_network(setup):
    tmp, make_cfg = setup
    cfg = make_cfg(TELEGRAM_BOT_TOKEN="", TELEGRAM_ENABLED="true")
    http = Http()
    with mock.patch("requests.post", side_effect=http):
        M.run(M.parse_args([]), cfg, TODAY)
    assert http.telegram == []
    assert (tmp / "output" / "2026-10-18" / "telegram_dryrun.txt").exists()


def test_message_title_escaped_in_pipeline(setup):
    tmp, make_cfg = setup
    FakeScraper.jobs = [dict(source="fake", external_id="x", title="Senior C# & .NET <Lead> s95",
                             company="A&B", posted_text="Dün", url="https://ex.com/x")]
    http = Http()
    with mock.patch("requests.post", side_effect=http):
        M.run(M.parse_args([]), make_cfg(), TODAY)
    msg = _sent_titles(http)[0]
    assert "&amp; .NET &lt;Lead&gt;" in msg and "A&amp;B" in msg


def test_document_caption_escaped(setup):
    tmp, make_cfg = setup
    FakeScraper.jobs = [dict(source="fake", external_id="x", title="Senior C# & .NET <Lead> s95",
                             posted_text="Dün", url="https://ex.com/x")]
    http = Http()
    with mock.patch("requests.post", side_effect=http):
        M.run(M.parse_args([]), make_cfg(), TODAY)
    cap = [d for m, d in http.telegram if m == "sendDocument"][0]["caption"]
    assert "<Lead>" not in cap and re.search(r"&(?!amp;|lt;|gt;)", cap) is None


def test_telegram_token_not_logged(caplog):
    from src.notify import TelegramNotifier

    def boom(url, **kw):
        raise requests.ConnectionError(f"Max retries exceeded with url: {url}")
    with mock.patch("requests.post", side_effect=boom):
        TelegramNotifier("123456:SECRETTOKEN", "42", True).send_message("hi")
    assert "SECRETTOKEN" not in caplog.text
