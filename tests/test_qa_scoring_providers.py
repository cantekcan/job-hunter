"""QA: scorer robustness + provider fallback chain (all HTTP mocked)."""
import json
import logging
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

import pytest
import requests

from src.ai import providers as P
from src.scorer import extract_json, normalize_result, score_job
from tests.conftest import FakeResponse, make_job

GROQ_OK = {"choices": [{"message": {"content": json.dumps({"score": 82, "eslesen": ["C#"], "eksik": []})}}]}


def gemini_ok(score=77):
    txt = json.dumps({"score": score, "eslesen": [".NET"], "eksik": ["Go"], "ozet": "x", "dil": "tr"})
    return {"candidates": [{"content": {"parts": [{"text": txt}]}}]}


def cfg(**kw):
    base = dict(ai_providers=["groq", "gemini"], groq_api_key="g-test", groq_model="m", groq_model_strong="M",
                gemini_api_key="gm-test", gemini_model="gm", gemini_model_strong="GM",
                xai_api_key="", xai_model="x", xai_model_strong="X")
    base.update(kw)
    return SimpleNamespace(**base)


class _Chain:
    def __init__(self, raw):
        self.raw = raw

    def complete(self, *a, **k):
        return self.raw


@pytest.mark.parametrize("raw,expected", [
    ('{"score": "82"}', 82), ('{"score": 82.6}', 83), ('{"score": 150}', 100), ('{"score": -20}', 0),
    ('{"score": "85/100"}', 85), ('```json\n{"score": 71}\n```', 71), ('Sonuç: {"score": 64, "ozet": "a } b"} bitti', 64),
    ('{"puan": 55}', 55), ('{"score": 90, "eslesen": "C#, .NET; SQL", "eksik": null}', 90),
])
def test_scorer_parses_messy_json(raw, expected):
    res = score_job(make_job(), "cv", "prefs", _Chain(raw))
    assert res is not None and res["score"] == expected
    assert isinstance(res["eslesen"], list) and isinstance(res["eksik"], list)
    assert res["on_yazi_gerekli"] == (expected >= 70)


@pytest.mark.parametrize("raw", ["", "not json", "{score: 80}", '{"score": "yüksek"}', '{"eslesen": []}',
                                 '{"score": null}', '{"score": true}', '{"score": [80]}',
                                 '{"score": 80,'])
def test_scorer_unusable_returns_none(raw):
    assert score_job(make_job(), "cv", "prefs", _Chain(raw)) is None


@pytest.mark.xfail(reason="BUG: NaN/Infinity scores (valid for Python json) raise ValueError/OverflowError "
                          "in scorer._to_int and crash the whole run", strict=True)
@pytest.mark.parametrize("raw", ['{"score": NaN}', '{"score": Infinity}', '{"score": 1e400}'])
def test_scorer_nan_score_does_not_crash(raw):
    assert score_job(make_job(), "cv", "prefs", _Chain(raw)) is None


@pytest.mark.parametrize("score,letter", [(49, False), (50, False), (69, False), (70, True), (100, True)])
def test_letter_threshold(score, letter):
    assert normalize_result({"score": score}, make_job(), 70)["on_yazi_gerekli"] is letter


def _router(groq_behavior, gemini_payload=None):
    calls = []

    def post(url, **kw):
        calls.append(url)
        if "groq" in url:
            if isinstance(groq_behavior, BaseException):
                raise groq_behavior
            return groq_behavior
        return FakeResponse(200, gemini_payload or gemini_ok())
    return post, calls


@pytest.mark.parametrize("groq", [
    FakeResponse(500, text="boom"), FakeResponse(503, text="x"), FakeResponse(401, text="bad key"),
    requests.Timeout("read timeout"), requests.ConnectionError("down"),
    FakeResponse(200, None, text="<html>not json</html>"),
    FakeResponse(200, {"choices": []}), FakeResponse(200, {"choices": [{"message": {"content": "  "}}]}),
])
def test_groq_failure_falls_back_to_gemini(groq):
    post, calls = _router(groq)
    chain = P.build_chain(cfg())
    with mock.patch("requests.post", side_effect=post):
        res = score_job(make_job(), "cv", "p", chain)
    assert res["score"] == 77 and chain.last_provider == "gemini"
    assert any("groq" in c for c in calls) and any("generativelanguage" in c for c in calls)


def test_groq_429_twice_falls_back_without_long_sleep():
    sleeps = []
    groq = P.GroqProvider("k", "m", sleep=sleeps.append)
    gem = P.GeminiProvider("k2", "gm", sleep=sleeps.append)
    post, calls = _router(FakeResponse(429, text="rate", headers={"Retry-After": "999"}))
    with mock.patch("requests.post", side_effect=post):
        out = P.ProviderChain([groq, gem]).complete("s", "u", json_mode=True)
    assert json.loads(out)["score"] == 77
    assert sum("groq" in c for c in calls) == 2  # one retry
    assert sleeps == [P.MAX_RETRY_AFTER_S]


def test_missing_keys_are_skipped():
    chain = P.build_chain(cfg(groq_api_key=""))
    assert [p.name for p in chain.providers] == ["gemini"]
    assert not P.build_chain(cfg(groq_api_key="", gemini_api_key=""))
    assert [p.name for p in P.build_chain(cfg(ai_providers=["gemini", "groq", "bogus"])).providers] == ["gemini", "groq"]


def test_all_fail_returns_none_and_no_exception():
    with mock.patch("requests.post", side_effect=requests.Timeout("t")):
        assert score_job(make_job(), "cv", "p", P.build_chain(cfg())) is None
    with pytest.raises(P.AllProvidersFailed):
        P.ProviderChain([]).complete("s", "u")


def _requests_like_post(url, params=None, **kw):
    """Mimic requests/urllib3: connection errors embed the full URL incl. query string."""
    full = url + ("?" + urlencode(params) if params else "")
    raise requests.ConnectionError(f"HTTPSConnectionPool(host='x', port=443): Max retries exceeded with url: {full}")


@pytest.mark.xfail(reason="BUG: Gemini key is sent as ?key= query param; requests ConnectionError text "
                          "contains the URL and providers/scorer log it verbatim -> API key leaks to logs", strict=True)
def test_gemini_key_not_logged_on_connection_error(caplog):
    caplog.set_level(logging.DEBUG)
    with mock.patch("requests.post", side_effect=_requests_like_post):
        score_job(make_job(), "cv", "p", P.build_chain(cfg(groq_api_key="", gemini_api_key="AIzaSECRET123")))
    assert "AIzaSECRET123" not in caplog.text
