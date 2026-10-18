import logging

from src.redact import RedactingFilter, redact, register_secret


def test_redact_patterns_and_registered(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_envsecret123")
    register_secret("my-registered-secret")
    text = ("url https://api.telegram.org/bot123456:ABCdef_ghi/sendMessage ?key=AIzaXYZ&alt=json "
            "Bearer sk-abc.def gsk_envsecret123 my-registered-secret")
    out = redact(text)
    for leaked in ("ABCdef_ghi", "AIzaXYZ", "sk-abc.def", "gsk_envsecret123", "my-registered-secret"):
        assert leaked not in out
    assert "alt=json" in out and "/bot***" in out


def test_filter_redacts_args():
    rec = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed: %s", ("?key=SECRETVAL",), None)
    RedactingFilter().filter(rec)
    assert "SECRETVAL" not in rec.getMessage()
