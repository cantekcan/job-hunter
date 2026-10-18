from src.ai.providers import AllProvidersFailed
from src.scorer import extract_json, score_job
from tests.conftest import make_job


class FakeChain:
    def __init__(self, text=None, exc=None):
        self.text, self.exc, self.calls = text, exc, []

    def complete(self, system, user, json_mode=False, strong=False):
        self.calls.append(dict(system=system, user=user, json_mode=json_mode, strong=strong))
        if self.exc:
            raise self.exc
        return self.text


def test_fenced_json():
    text = 'Tabii, işte sonuç:\n```json\n{"score": 82, "eslesen": [".NET", "bankacılık"], "eksik": ["Azure"],' \
           ' "ozet": "İyi uyum", "on_yazi_gerekli": false, "dil": "tr"}\n```\nBaşka bir şey?'
    chain = FakeChain(text)
    res = score_job(make_job(), "CV", "PREFS", chain)
    assert res == {"score": 82, "eslesen": [".NET", "bankacılık"], "eksik": ["Azure"], "ozet": "İyi uyum",
                   "on_yazi_gerekli": True, "dil": "tr"}  # forced by score >= 70
    assert chain.calls[0]["json_mode"] is True and not chain.calls[0]["strong"]
    assert "Senior .NET Developer" in chain.calls[0]["user"] and "CV" in chain.calls[0]["user"]


def test_json_embedded_in_prose_with_braces_in_strings():
    data = extract_json('Sonuç: {"score": 60, "ozet": "a {b} c"} teşekkürler {not json}')
    assert data == {"score": 60, "ozet": "a {b} c"}


def test_garbage_returns_none():
    assert score_job(make_job(), "cv", "p", FakeChain("Üzgünüm, yardımcı olamam.")) is None
    assert score_job(make_job(), "cv", "p", FakeChain('{"ozet": "skor yok"}')) is None


def test_all_providers_failed_returns_none():
    assert score_job(make_job(), "cv", "p", FakeChain(exc=AllProvidersFailed([]))) is None


def test_clamping_and_coercion():
    res = score_job(make_job(), "cv", "p", FakeChain(
        '{"score": "140/100", "eslesen": "C#, SQL; Redis", "eksik": null, "ozet": 5, "on_yazi_gerekli": "no"}'))
    assert res["score"] == 100
    assert res["eslesen"] == ["C#", "SQL", "Redis"] and res["eksik"] == []
    assert res["ozet"] == "5" and res["on_yazi_gerekli"] is True
    low = score_job(make_job(), "cv", "p", FakeChain('{"score": -12.4, "on_yazi_gerekli": true, "dil": "EN"}'))
    assert low["score"] == 0 and low["on_yazi_gerekli"] is False and low["dil"] == "en"


def test_cover_letter_threshold_param_and_language_fallback():
    job = make_job(description="We are looking for a senior engineer with strong experience in the team.")
    res = score_job(job, "cv", "p", FakeChain('{"score": 72}'), min_score_cover_letter=80)
    assert res["on_yazi_gerekli"] is False
    assert res["dil"] == "en"
