"""QA: Telegram formatting/dry-run, cover letter language/path, config, secrets hygiene."""
import html
import re
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from src import cover_letter as CL
from src.config import load_config, load_preferences
from src.notify import TelegramNotifier, format_message, split_message
from tests.conftest import TODAY, FakeResponse, make_job

ROOT = Path(__file__).resolve().parent.parent
RES = {"score": 82, "eslesen": [".NET", "C#", "SQL"], "eksik": ["Kafka"], "ozet": "uygun"}


def _strip_tags(s):
    return html.unescape(re.sub(r"<[^>]+>", "", s))


def test_message_format_matches_example():
    job = make_job(title="Senior .NET Developer", company="XYZ Fintech", location="İstanbul", work_model="hibrit")
    lines = [_strip_tags(l) for l in format_message(job, RES, True).split("\n")]
    assert lines[0] == "🟢 82/100 – Senior .NET Developer – XYZ Fintech (İstanbul, hibrit)"
    assert lines[1] == "Eşleşen: .NET, C#, SQL · Eksik: Kafka"
    assert lines[-1] == "🔗 link · 📄 ön yazı ekte"
    assert "📄" not in format_message(job, RES, False)
    assert format_message(job, {**RES, "score": 55}, False).startswith("🟡")


def test_html_escaping():
    job = make_job(title="C# <Senior> & .NET", company="A&B <Ltd>", url='https://x.com/?a=1&b="2"')
    msg = format_message(job, {**RES, "eslesen": ["<script>"], "ozet": "a & b"}, False)
    assert "<Senior>" not in msg and "<Ltd>" not in msg and "<script>" not in msg
    assert "C# &lt;Senior&gt; &amp; .NET" in msg and "A&amp;B" in msg and "a &amp; b" in msg
    assert re.search(r"&(?!amp;|lt;|gt;|quot;|#x27;)", msg) is None


def test_long_message_split_under_4096():
    text = "\n".join(f"satır {i} " + "x" * 90 for i in range(200)) + "\n" + "y" * 9000
    chunks = split_message(text)
    assert len(chunks) > 2 and all(0 < len(c) <= 4096 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == text.replace("\n", "")


def test_split_does_not_break_entities():
    for c in split_message("x" + "&amp;" * 1000):
        assert not re.search(r"&[a-z]*$", c) and not re.match(r"^[a-z]*;", c)


@pytest.mark.parametrize("enabled,token,chat", [(False, "t", "c"), (True, "", "c"), (True, "t", ""), (True, "", "")])
def test_dry_run_makes_no_network_calls(tmp_path, enabled, token, chat):
    p = tmp_path / "out" / "telegram_dryrun.txt"
    letter = tmp_path / "l.md"
    letter.write_text("x", encoding="utf-8")
    with mock.patch("requests.post") as post, mock.patch("requests.get") as get:
        n = TelegramNotifier(token, chat, enabled, dryrun_path=p)
        assert n.dry_run
        assert n.send_message(format_message(make_job(), RES, True))
        assert n.send_document(letter, "cap")
    post.assert_not_called()
    get.assert_not_called()
    body = p.read_text(encoding="utf-8")
    assert "82/100" in body and "l.md" in body


def test_enabled_sends_html_parse_mode():
    with mock.patch("requests.post", return_value=FakeResponse(200, {"ok": True})) as post:
        assert TelegramNotifier("tok", "42", True).send_message("hi")
    data = post.call_args.kwargs["data"]
    assert data["parse_mode"] == "HTML" and data["chat_id"] == "42"


# ---------------- cover letter ----------------

EN_AD = ("We are looking for a Senior .NET Developer to join our team. You will work with C#, ASP.NET Core "
         "and Azure. Requirements: 5+ years of experience and strong knowledge of SQL.")
TR_AD = ("Ekibimize katılacak, C# ve .NET Core konusunda deneyimli bir yazılım geliştirici arıyoruz. "
         "En az 5 yıl deneyim, SQL bilgisi ve tercihen Azure tecrübesi.")


def test_language_detection():
    assert CL.detect_language(EN_AD) == "en"
    assert CL.detect_language(TR_AD) == "tr"
    assert CL.detect_language("SENIOR DEVELOPER - WE ARE LOOKING FOR AN ENGINEER WITH STRONG SKILLS") == "en"


def test_short_english_ad_with_turkish_location():
    assert CL.detect_language("Senior .NET Engineer\nC#, .NET 8, Azure Service Bus, Kubernetes. Hybrid - Maslak, İstanbul.") == "en"


@pytest.mark.parametrize("desc,dil,expected", [(EN_AD, None, CL.SYSTEM_EN), (TR_AD, None, CL.SYSTEM_TR),
                                               (TR_AD, "en", CL.SYSTEM_EN)])
def test_letter_prompt_language(desc, dil, expected):
    seen = {}

    class Chain:
        def complete(self, system, user, json_mode=False, strong=False):
            seen.update(system=system, strong=strong)
            return "```\nDear Hiring Team,\nbody\n```"

    res = {**RES, **({"dil": dil} if dil else {})}
    out = CL.generate_cover_letter(make_job(description=desc), "cv", "p", res, Chain())
    assert seen["system"] is expected and seen["strong"] is True
    assert out == "Dear Hiring Team,\nbody"


def test_letter_saved_under_dated_dir(tmp_path):
    job = make_job(title="Senior .NET / C# Developer", company="Şirket A.Ş.", external_id="ab/../12")
    p = CL.save_cover_letter(job, "Merhaba,\nmetin", tmp_path / "output", TODAY, 82)
    assert p.parent == tmp_path / "output" / "2026-10-18" and p.suffix == ".md"
    assert p.resolve().is_relative_to((tmp_path / "output" / "2026-10-18").resolve())
    txt = p.read_text(encoding="utf-8")
    assert CL.REVIEW_NOTE in txt and "82/100" in txt and "metin" in txt


# ---------------- config ----------------

def test_real_preferences_yaml():
    prefs = load_preferences(ROOT / "profile" / "preferences.md")
    assert prefs["min_score_notify"] == 50 and prefs["min_score_cover_letter"] == 70
    assert prefs["max_age_days"] == 1
    kws = prefs["exclude_title_keywords"]
    for k in ("junior", "stajyer", "intern", "yeni mezun", "java", "jr "):
        assert k in kws
    assert not any("#" in k for k in kws)  # inline comments stripped
    assert ".net developer" in prefs["search_queries"] and "yazılım uzmanı .net" in prefs["search_queries"]
    assert "istanbul(avr.)" in prefs["include_locations"]


def test_env_overrides(tmp_path, monkeypatch):
    for k in ("AI_PROVIDERS", "GROQ_API_KEY", "GEMINI_API_KEY", "TELEGRAM_ENABLED", "GEMINI_MODEL", "GEMINI_MODEL_STRONG"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text("AI_PROVIDERS=gemini, GROQ\nGROQ_API_KEY=fromdotenv\nTELEGRAM_ENABLED=yes\n"
                                   "GEMINI_MODEL=gm-x\n", encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "fromenv")
    c = load_config(root=tmp_path, prefs_path=ROOT / "profile" / "preferences.md")
    assert c.ai_providers == ["gemini", "groq"] and c.groq_api_key == "fromenv"
    assert c.telegram_enabled is True and c.gemini_model_strong == "gm-x"
    assert c.min_score_notify == 50
    c2 = load_config(root=tmp_path, env={"TELEGRAM_ENABLED": "false"})
    assert c2.telegram_enabled is False and c2.ai_providers == ["groq", "gemini"]


# ---------------- secrets hygiene ----------------

@pytest.mark.parametrize("path", [".env", "data/jobs.db", "output/2026-10-18/report.md", "output/x.md", "cv.pdf", "profile/cv.pdf"])
def test_gitignore_covers(path):
    r = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=ROOT)
    if r.returncode == 128:
        pytest.skip("not a git work tree")
    assert r.returncode == 0, f"{path} is not git-ignored"


def test_env_example_not_ignored():
    assert subprocess.run(["git", "check-ignore", "--no-index", "-q", ".env.example"], cwd=ROOT).returncode == 1


KEY_RE = re.compile(r"gsk_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_\-]{30,}|xai-[A-Za-z0-9]{20,}|\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")


def test_no_hardcoded_secrets():
    hits = []
    for p in ROOT.rglob("*"):
        if p.is_file() and ".git" not in p.parts and p.suffix in {".py", ".md", ".txt", ".example", ".yml", ".yaml", ".toml", ".json", ""}:
            if KEY_RE.search(p.read_text(encoding="utf-8", errors="ignore")):
                hits.append(str(p))
    assert hits == []
    for line in (ROOT / ".env.example").read_text().splitlines():
        if re.match(r"^(GROQ|GEMINI|XAI)_API_KEY=|^TELEGRAM_BOT_TOKEN=|^TELEGRAM_CHAT_ID=", line):
            assert line.split("=", 1)[1].strip() == "", line
