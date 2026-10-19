from src.ai.providers import GroqProvider, ProviderError
import pytest


class R:
    def __init__(self, status, data=None, text=""):
        self.status_code, self._d, self.text, self.headers = status, data or {}, text, {}

    def json(self):
        return self._d


OK = {"choices": [{"message": {"content": "{\"ok\": true}"}}]}
GONE = R(404, text='{"error":{"message":"The model `x` does not exist","code":"model_not_found"}}')


def test_next_configured_model_is_tried(monkeypatch):
    seen = []

    def post(url, json=None, **kw):
        seen.append(json["model"])
        return GONE if json["model"] == "old" else R(200, OK)

    monkeypatch.setattr("requests.post", post)
    p = GroqProvider("gsk_x", "old,new")
    assert p.complete("s", "u") == "{\"ok\": true}"
    assert seen == ["old", "new"] and p.model == "new"
    p.complete("s", "u")
    assert seen[-1] == "new"  # remembered, no retry of the dead model


def test_models_discovered_when_all_configured_are_gone(monkeypatch):
    seen = []

    def post(url, json=None, **kw):
        seen.append(json["model"])
        return R(200, OK) if json["model"] == "brand-new" else GONE

    def get(url, **kw):
        assert url.endswith("/models")
        return R(200, {"data": [{"id": "whisper-large-v3"}, {"id": "old"}, {"id": "brand-new"}]})

    monkeypatch.setattr("requests.post", post)
    monkeypatch.setattr("requests.get", get)
    p = GroqProvider("gsk_x", "old")
    p.complete("s", "u")
    assert "whisper-large-v3" not in seen and seen[-1] == "brand-new"


def test_other_errors_are_not_treated_as_model_errors(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: R(401, text='{"error":"invalid api key"}'))
    with pytest.raises(ProviderError):
        GroqProvider("gsk_x", "a,b").complete("s", "u")


def test_default_provider_is_groq_only(monkeypatch):
    from src.config import load_config
    monkeypatch.delenv("AI_PROVIDERS", raising=False)
    assert load_config(env={}).ai_providers == ["groq"]


def test_qwen_falls_back_to_gpt_oss_and_ai_is_reported(monkeypatch):
    from src.ai.providers import ProviderChain

    def post(url, json=None, **kw):
        return GONE if json["model"].startswith("qwen") else R(200, OK)

    monkeypatch.setattr("requests.post", post)
    chain = ProviderChain([GroqProvider("gsk_x", "qwen/qwen3.5-27b,openai/gpt-oss-120b")])
    chain.complete("s", "u")
    assert chain.last_ai == "groq · openai/gpt-oss-120b"


def test_discovery_prefers_lookalike_of_wanted_model():
    from src.ai.providers import rank_discovered
    found = ["llama-3.3-70b-versatile", "qwen/qwen3.5-27b-instruct", "openai/gpt-oss-120b"]
    assert rank_discovered(found, ["qwen/Qwen3.5-27B", "openai/gpt-oss-120b"])[:2] == [
        "qwen/qwen3.5-27b-instruct", "openai/gpt-oss-120b"]


def test_think_tags_are_stripped(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: R(200, {"choices": [{"message": {
        "content": "<think>hmm {not json}</think>\n{\"score\": 80}"}}]}))
    assert GroqProvider("gsk_x", "m").complete("s", "u") == "{\"score\": 80}"


def test_telegram_message_says_which_ai_wrote_it():
    from src.models import Job
    from src.notify import format_message
    job = Job(source="kariyernet", external_id="1", title="Senior .NET", company="X", location="İstanbul",
              work_model="hibrit", url="https://x", posted_text=None, posted_date=None, description="", language="tr")
    msg = format_message(job, {"score": 82, "eslesen": [], "eksik": [], "ozet": "",
                               "ai": "groq · qwen/qwen3.5-27b", "ai_letter": "groq · openai/gpt-oss-120b"}, True)
    assert "🤖 Puan: groq · qwen/qwen3.5-27b · Ön yazı: groq · openai/gpt-oss-120b" in msg
    assert "🤖 groq · qwen/qwen3.5-27b" in format_message(job, {"score": 60, "ai": "groq · qwen/qwen3.5-27b"}, False)
