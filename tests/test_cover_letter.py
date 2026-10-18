from datetime import date

from src.cover_letter import REVIEW_NOTE, detect_language, generate_cover_letter, save_cover_letter
from tests.conftest import make_job


class FakeChain:
    def __init__(self, text):
        self.text, self.calls = text, []

    def complete(self, system, user, json_mode=False, strong=False):
        self.calls.append(dict(system=system, user=user, json_mode=json_mode, strong=strong))
        return self.text


def test_detect_language():
    assert detect_language("Kıdemli .NET geliştirici arıyoruz. En az 5 yıl deneyim ve mikroservis bilgisi.") == "tr"
    assert detect_language("We are looking for a Senior .NET Engineer with strong experience in "
                           "microservices to join our team.") == "en"
    assert detect_language("") == "tr"
    assert detect_language("SENIOR BACKEND DEVELOPER - WE ARE HIRING AND YOU WILL WORK WITH THE TEAM") == "en"


def test_generate_uses_strong_model_and_ad_language():
    chain = FakeChain("```\nDear Hiring Team,\n...\nCan Tekcan\n```")
    job = make_job(description="We are looking for a .NET engineer with experience in the cloud.")
    letter = generate_cover_letter(job, "CV TEXT", "PREFS", {"dil": "en", "eslesen": [".NET"], "eksik": []}, chain)
    assert letter.startswith("Dear Hiring Team,") and "```" not in letter
    call = chain.calls[0]
    assert call["strong"] is True and "ENGLISH" in call["system"] and "CV TEXT" in call["user"]

    generate_cover_letter(make_job(), "CV", "P", {"dil": "tr"}, chain)
    assert "TÜRKÇE" in chain.calls[1]["system"]


def test_save_cover_letter(tmp_path):
    job = make_job(title="Kıdemli Yazılım Geliştirici (.NET)", company="Örnek Şirket A.Ş.", external_id="12345")
    path = save_cover_letter(job, "Merhaba,\nmetin\n", tmp_path, date(2026, 10, 18), score=81)
    assert path.parent == tmp_path / "2026-10-18"
    assert path.name == "ornek-sirket-a-s-kidemli-yazilim-gelistirici-net-12345.md"
    text = path.read_text(encoding="utf-8")
    assert REVIEW_NOTE in text and "Göndermeden önce oku ve kendi cümlelerinle düzelt." in text
    assert "https://example.com/ilan/1" in text and "81/100" in text and text.rstrip().endswith("metin")
