"""Cover letter generation (strong model) and saving to output/YYYY-MM-DD/."""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .ai.providers import ProviderChain
from .models import Job
from .textutil import slugify, tr_lower

log = logging.getLogger(__name__)

REVIEW_NOTE = "Göndermeden önce oku ve kendi cümlelerinle düzelt."

_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
_TR_WORDS = {
    "ve", "bir", "için", "ile", "olarak", "bu", "da", "de", "olan", "en", "az", "yıl", "deneyim",
    "deneyimli", "aranıyor", "arıyoruz", "çalışma", "bilgi", "sahibi", "tercihen", "iyi", "ekip",
    "geliştirme", "yazılım", "konusunda", "veya", "gibi", "olmak", "üzere",
}
_EN_WORDS = {
    "the", "and", "for", "with", "you", "we", "our", "are", "is", "of", "to", "in", "experience",
    "years", "looking", "team", "will", "work", "skills", "strong", "knowledge", "development",
    "requirements", "responsibilities", "an", "a", "or", "be", "your",
    "engineer", "engineers", "hybrid", "onsite", "office", "english", "candidate", "join", "hiring",
}


def detect_language(text: str) -> str:
    """Cheap tr/en heuristic: stopwords + Turkish letters. Defaults to 'tr'.

    Turkish letters only count in words that are not capitalized, so a place name such as
    "İstanbul" or "Şişli" in an English ad is not evidence for Turkish.
    """
    if not text or not text.strip():
        return "tr"
    raw_words = re.findall(r"[^\W\d_]+", text)
    tr_words = [tr_lower(w) for w in raw_words]
    en_words = [w.lower() for w in raw_words]
    tr_chars = sum(1 for w in raw_words if not w[0].isupper() and any(ch in _TR_CHARS for ch in w))
    tr_score = sum(w in _TR_WORDS for w in tr_words) + tr_chars
    en_score = sum(w in _EN_WORDS for w in en_words)
    return "en" if en_score > tr_score else "tr"


SYSTEM_TR = """Sen adayın adına kısa, samimi ve profesyonel ön yazılar yazan bir kariyer danışmanısın.
Kurallar:
- Ön yazıyı TÜRKÇE yaz, 200-280 kelime.
- YALNIZCA CV'de geçen deneyim, şirket, teknoloji ve başarıları kullan. CV'de olmayan hiçbir deneyim,
  sertifika, rakam veya teknoloji UYDURMA. İlandaki eksik bir beceri için "öğrenmeye açığım" de, sahipmiş gibi yazma.
- İlandaki gereksinimlerle CV'deki en güçlü 2-3 eşleşmeyi somut örneklerle bağla.
- Klişe ve abartıdan kaçın. Başlık, konu satırı veya markdown kullanma; sadece mektup metni.
- "Merhaba," veya "Sayın İşe Alım Ekibi," ile başla, adayın adıyla bitir."""

SYSTEM_EN = """You are a career coach who writes short, warm, professional cover letters for the candidate.
Rules:
- Write the cover letter in ENGLISH, 200-280 words.
- Use ONLY experience, companies, technologies and achievements stated in the CV. Never invent experience,
  certificates, numbers or technologies. For a skill the CV lacks, say the candidate is eager to learn it.
- Connect the 2-3 strongest CV matches to the ad's requirements with concrete examples.
- Avoid clichés and exaggeration. No title, subject line or markdown; only the letter body.
- Start with "Dear Hiring Team," and end with the candidate's name."""


def build_prompt(job: Job, cv_text: str, prefs_text: str, score_result: dict[str, Any]) -> str:
    return (
        f"## CV\n{cv_text.strip()}\n\n"
        f"## Tercihler (bağlam)\n{prefs_text.strip()[:3000]}\n\n"
        f"## İlan\nBaşlık: {job.title}\nŞirket: {job.company}\nLokasyon: {job.location}\n"
        f"Açıklama:\n{(job.description or '').strip()[:6000]}\n\n"
        f"## Değerlendirme\nEşleşen: {', '.join(score_result.get('eslesen', []))}\n"
        f"Eksik: {', '.join(score_result.get('eksik', []))}\n"
        f"Özet: {score_result.get('ozet', '')}\n"
    )


def _clean(text: str) -> str:
    text = text.strip()
    m = re.fullmatch(r"```[a-zA-Z]*\s*(.*?)```", text, re.DOTALL)
    return (m.group(1) if m else text).strip()


def generate_cover_letter(job: Job, cv_text: str, prefs_text: str, score_result: dict[str, Any],
                          chain: ProviderChain) -> str:
    """Generate the letter in the ad's language with the strong model. Raises AllProvidersFailed."""
    lang = score_result.get("dil") or job.language or detect_language(f"{job.title}\n{job.description}")
    system = SYSTEM_EN if lang == "en" else SYSTEM_TR
    text = chain.complete(system, build_prompt(job, cv_text, prefs_text, score_result), strong=True)
    return _clean(text)


def save_cover_letter(job: Job, letter: str, output_dir: Path, today: Optional[date] = None,
                      score: Optional[int] = None) -> Path:
    today = today or date.today()
    day_dir = Path(output_dir) / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify(f"{job.company} {job.title}") + "-" + slugify(job.external_id, 20)
    path = day_dir / f"{slug}.md"
    header = [
        f"# Ön Yazı — {job.title} — {job.company}",
        "",
        f"> ⚠️ {REVIEW_NOTE}",
        f"> İlan: {job.url}",
    ]
    if score is not None:
        header.append(f"> Puan: {score}/100")
    path.write_text("\n".join(header) + "\n\n---\n\n" + letter.strip() + "\n", encoding="utf-8")
    return path
