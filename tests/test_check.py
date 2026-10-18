from src.ai import providers as P
from src.check import run_check
from src.config import load_config


class Resp:
    def __init__(self, status=200, data=None):
        self.status_code, self._data, self.text = status, data or {}, ""

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _cfg(monkeypatch, **env):
    for k in ("GROQ_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.setenv(k, "")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return load_config()


def test_check_sends_telegram_even_when_disabled(monkeypatch, capsys):
    calls = []

    def fake_post(url, **kw):
        calls.append(url)
        if "telegram" in url:
            return Resp(200)
        return Resp(200, {"choices": [{"message": {"content": "OK"}}]})

    monkeypatch.setattr("requests.post", fake_post)
    cfg = _cfg(monkeypatch, GROQ_API_KEY="gsk_x", TELEGRAM_BOT_TOKEN="1:abc", TELEGRAM_CHAT_ID="42",
               TELEGRAM_ENABLED="false")
    assert run_check(cfg) == 0
    assert any("sendMessage" in u for u in calls) and any("groq" in u for u in calls)
    assert "✅ Telegram" in capsys.readouterr().out


def test_check_fails_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr("requests.post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
    assert run_check(_cfg(monkeypatch)) == 1
    out = capsys.readouterr().out
    assert "AI" in out and "Telegram" in out


def test_xai_key_in_groq_secret_is_used_as_xai(monkeypatch):
    cfg = _cfg(monkeypatch, GROQ_API_KEY="xai-abc", AI_PROVIDERS="groq,gemini")
    chain = P.build_chain(cfg)
    assert [p.name for p in chain.providers] == ["xai"]
