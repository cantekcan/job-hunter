import pytest
import requests

from src.ai import providers as P
from src.config import load_config
from tests.conftest import FakeResponse


def groq_ok(text="merhaba"):
    return FakeResponse(200, {"choices": [{"message": {"content": text}}]})


def gemini_ok(text="gemini cevap"):
    return FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": text}]}}]})


class Recorder:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def no_sleep():
    return lambda s: None


def test_groq_ok(monkeypatch, no_sleep):
    rec = Recorder(groq_ok('{"a": 1}'))
    monkeypatch.setattr(P.requests, "post", rec)
    chain = P.ProviderChain([P.GroqProvider("k", "small", "big", sleep=no_sleep)])
    assert chain.complete("sys", "usr", json_mode=True) == '{"a": 1}'
    url, kw = rec.calls[0]
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert kw["json"]["model"] == "small"
    assert kw["json"]["response_format"] == {"type": "json_object"}
    assert kw["headers"]["Authorization"] == "Bearer k"
    assert kw["timeout"] == 60
    assert chain.last_provider == "groq"


def test_strong_model_and_no_json_mode(monkeypatch, no_sleep):
    rec = Recorder(groq_ok())
    monkeypatch.setattr(P.requests, "post", rec)
    P.GroqProvider("k", "small", "big", sleep=no_sleep).complete("s", "u", strong=True)
    body = rec.calls[0][1]["json"]
    assert body["model"] == "big" and "response_format" not in body


def test_groq_500_falls_back_to_gemini(monkeypatch, no_sleep):
    rec = Recorder(FakeResponse(500, text="boom"), gemini_ok("ok from gemini"))
    monkeypatch.setattr(P.requests, "post", rec)
    chain = P.ProviderChain([
        P.GroqProvider("g", "m", sleep=no_sleep),
        P.GeminiProvider("gk", "gemini-2.0-flash", sleep=no_sleep),
    ])
    assert chain.complete("s", "u", json_mode=True) == "ok from gemini"
    assert chain.last_provider == "gemini"
    url, kw = rec.calls[1]
    assert url.endswith("/v1beta/models/gemini-2.0-flash:generateContent")
    assert kw["params"] == {"key": "gk"}
    assert kw["json"]["generationConfig"]["responseMimeType"] == "application/json"
    assert kw["json"]["systemInstruction"]["parts"][0]["text"] == "s"


def test_timeout_falls_back(monkeypatch, no_sleep):
    rec = Recorder(requests.Timeout("slow"), gemini_ok())
    monkeypatch.setattr(P.requests, "post", rec)
    chain = P.ProviderChain([P.GroqProvider("g", "m", sleep=no_sleep), P.GeminiProvider("k", "m", sleep=no_sleep)])
    assert chain.complete("s", "u") == "gemini cevap"


def test_429_retried_once(monkeypatch):
    slept = []
    rec = Recorder(FakeResponse(429, text="slow down", headers={"Retry-After": "2"}), groq_ok("second try"))
    monkeypatch.setattr(P.requests, "post", rec)
    assert P.GroqProvider("k", "m", sleep=slept.append).complete("s", "u") == "second try"
    assert slept == [2.0] and len(rec.calls) == 2


def test_429_twice_falls_back(monkeypatch, no_sleep):
    rec = Recorder(FakeResponse(429), FakeResponse(429), gemini_ok())
    monkeypatch.setattr(P.requests, "post", rec)
    chain = P.ProviderChain([P.GroqProvider("g", "m", sleep=no_sleep), P.GeminiProvider("k", "m", sleep=no_sleep)])
    assert chain.complete("s", "u") == "gemini cevap"
    assert len(rec.calls) == 3


def test_all_fail(monkeypatch, no_sleep):
    rec = Recorder(FakeResponse(500), FakeResponse(200, {"unexpected": True}), requests.ConnectionError("x"))
    monkeypatch.setattr(P.requests, "post", rec)
    chain = P.ProviderChain([
        P.GroqProvider("g", "m", sleep=no_sleep),
        P.GeminiProvider("k", "m", sleep=no_sleep),
        P.XAIProvider("x", "grok", sleep=no_sleep),
    ])
    with pytest.raises(P.AllProvidersFailed) as ei:
        chain.complete("s", "u")
    assert [name for name, _ in ei.value.errors] == ["groq", "gemini", "xai"]
    assert rec.calls[2][0] == "https://api.x.ai/v1/chat/completions"


def test_empty_chain_raises():
    with pytest.raises(P.AllProvidersFailed):
        P.ProviderChain([]).complete("s", "u")


def test_build_chain_order_and_skip(tmp_path):
    cfg = load_config(root=tmp_path, env={
        "AI_PROVIDERS": "gemini,groq,xai,bogus", "GEMINI_API_KEY": "gk", "GROQ_API_KEY": "g",
    })
    chain = P.build_chain(cfg)
    assert [p.name for p in chain.providers] == ["gemini", "groq"]  # xai has no key, bogus unknown
    assert chain.providers[1].model_strong == "llama-3.3-70b-versatile"

    assert not P.build_chain(load_config(root=tmp_path, env={}))
