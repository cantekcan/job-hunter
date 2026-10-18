import pytest

from src import notify as N
from tests.conftest import make_job

RESULT = {"score": 82, "eslesen": [".NET", "bankacılık"], "eksik": ["Azure"], "ozet": ""}


def test_format_message():
    msg = N.format_message(make_job(), RESULT, has_letter=True)
    lines = msg.split("\n")
    assert lines[0] == "🟢 <b>82/100</b> – Senior .NET Developer – XYZ Fintech (İstanbul, hibrit)"
    assert lines[1] == "Eşleşen: .NET, bankacılık · Eksik: Azure"
    assert lines[2] == '🔗 <a href="https://example.com/ilan/1">link</a> · 📄 ön yazı ekte'


def test_format_message_escapes_and_yellow():
    job = make_job(title="C# <Dev> & Co", company='"Acme"', url="https://x.com/?a=1&b=2", work_model="")
    msg = N.format_message(job, {"score": 55, "eslesen": ["<b>"], "eksik": []}, has_letter=False)
    assert msg.startswith("🟡 <b>55/100</b> – C# &lt;Dev&gt; &amp; Co – &quot;Acme&quot; (İstanbul)")
    assert "Eşleşen: &lt;b&gt;" in msg and "Eksik" not in msg
    assert 'href="https://x.com/?a=1&amp;b=2"' in msg and "ön yazı" not in msg


def test_summary():
    s = N.format_summary(found=12, new=5, notified=2, scored=5, day="2026-10-18")
    assert "2026-10-18" in s and "Bulunan: 12" in s and "Yeni: 5" in s and "Bildirilen: 2" in s


def test_split_message():
    text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))
    chunks = N.split_message(text, limit=4000)
    assert len(chunks) > 1 and all(len(c) <= 4000 for c in chunks)
    assert "\n".join(chunks) == text
    assert all(len(c) <= 4000 for c in N.split_message("y" * 9000))


def _no_network(*a, **kw):
    raise AssertionError("network call in dry-run")


@pytest.mark.parametrize("enabled,token,chat", [(False, "t", "c"), (True, "", "c"), (True, "t", "")])
def test_dry_run_writes_file_and_no_network(tmp_path, monkeypatch, enabled, token, chat):
    monkeypatch.setattr(N.requests, "post", _no_network)
    out = tmp_path / "2026-10-18" / "telegram_dryrun.txt"
    tn = N.TelegramNotifier(token, chat, enabled, dryrun_path=out)
    assert tn.dry_run
    letter = tmp_path / "letter.md"
    letter.write_text("hi", encoding="utf-8")
    assert tn.send_message(N.format_message(make_job(), RESULT, True))
    assert tn.send_document(letter, "Ön yazı")
    content = out.read_text(encoding="utf-8")
    assert "82/100" in content and "letter.md" in content


def test_live_send_uses_telegram_api(tmp_path, monkeypatch):
    calls = []

    class R:
        status_code = 200
        text = "ok"

    def fake_post(url, **kw):
        calls.append((url, kw))
        return R()

    monkeypatch.setattr(N.requests, "post", fake_post)
    tn = N.TelegramNotifier("TOKEN", "42", True, dryrun_path=tmp_path / "d.txt")
    assert tn.send_message("a" * 5000)  # split into 2 messages
    letter = tmp_path / "l.md"
    letter.write_text("x", encoding="utf-8")
    assert tn.send_document(letter, "cap")
    assert [c[0].rsplit("/", 1)[1] for c in calls] == ["sendMessage", "sendMessage", "sendDocument"]
    assert calls[0][0] == "https://api.telegram.org/botTOKEN/sendMessage"
    assert calls[0][1]["data"]["parse_mode"] == "HTML" and calls[0][1]["data"]["chat_id"] == "42"
    assert calls[2][1]["files"]["document"][0] == "l.md"
    assert not (tmp_path / "d.txt").exists()
