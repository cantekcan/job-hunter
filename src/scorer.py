"""Score a job ad against the CV and preferences with an LLM."""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Optional

from .ai.providers import AllProvidersFailed, ProviderChain
from .cover_letter import detect_language
from .models import Job
from .redact import redact

log = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 6000

SYSTEM_PROMPT = """Sen deneyimli bir teknik işe alım uzmanısın. Görevin bir iş ilanını adayın CV'si ve \
tercihleriyle karşılaştırıp 0-100 arası bir uygunluk puanı vermek.
Kurallar:
- Tercihlerdeki puanlama kurallarına ve kesin eleme kriterlerine harfiyen uy.
- Sadece CV'de yazan bilgileri kullan; adaya olmayan bir deneyim atfetme.
- Yanıtın SADECE geçerli bir JSON nesnesi olsun; açıklama, markdown veya kod bloğu ekleme.
JSON şeması:
{"score": <0-100 tam sayı>, "eslesen": [<eşleşen beceri/kriterler>], "eksik": [<eksik beceri/kriterler>], \
"ozet": "<1-2 cümlelik Türkçe gerekçe; lokasyon/çalışma modeli değerlendirmesi dahil>", \
"on_yazi_gerekli": <true|false>, "dil": "<ilanın dili: tr veya en>"}"""


def build_user_prompt(job: Job, cv_text: str, prefs_text: str) -> str:
    desc = (job.description or "").strip()[:MAX_DESCRIPTION_CHARS]
    return (
        f"## ADAY CV\n{cv_text.strip()}\n\n"
        f"## ADAY TERCİHLERİ\n{prefs_text.strip()}\n\n"
        f"## İLAN\n"
        f"Başlık: {job.title}\nŞirket: {job.company}\nLokasyon: {job.location}\n"
        f"Çalışma modeli: {job.work_model or 'belirtilmemiş'}\nKaynak: {job.source}\nURL: {job.url}\n"
        f"Açıklama:\n{desc or '(açıklama yok)'}\n\n"
        "Bu ilanı değerlendir ve yalnızca JSON döndür."
    )


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def _first_json_object(text: str) -> Optional[str]:
    """Return the first balanced {...} substring, respecting JSON strings."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json(text: str) -> Optional[dict[str, Any]]:
    if not text:
        return None
    candidates = [m.strip() for m in _FENCE_RE.findall(text)] + [text.strip()]
    for cand in candidates:
        for chunk in (cand, _first_json_object(cand)):
            if not chunk:
                continue
            try:
                data = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def _to_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        m = re.search(r"-?\d+(?:[.,]\d+)?", value)
        value = float(m.group(0).replace(",", ".")) if m else None
    if isinstance(value, (int, float)):
        if not math.isfinite(value):  # NaN / Infinity / 1e400 are not scores
            return None
        return int(round(value))
    return None


def _to_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [p.strip() for p in re.split(r"[,;\n]", value) if p.strip()]
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def normalize_result(data: dict[str, Any], job: Job, min_score_cover_letter: int = 70) -> Optional[dict[str, Any]]:
    score = _to_int(data.get("score", data.get("puan")))
    if score is None:
        return None
    score = max(0, min(100, score))
    dil = str(data.get("dil") or "").strip().lower()[:2]
    if dil not in ("tr", "en"):
        dil = job.language or detect_language(f"{job.title}\n{job.description}")
    return {
        "score": score,
        "eslesen": _to_list(data.get("eslesen")),
        "eksik": _to_list(data.get("eksik")),
        "ozet": str(data.get("ozet") or "").strip(),
        "on_yazi_gerekli": score >= min_score_cover_letter,
        "dil": dil,
    }


def score_job(job: Job, cv_text: str, prefs_text: str, chain: ProviderChain,
              min_score_cover_letter: int = 70) -> Optional[dict[str, Any]]:
    """Return the normalized score dict, or None if no provider produced usable JSON."""
    try:
        raw = chain.complete(SYSTEM_PROMPT, build_user_prompt(job, cv_text, prefs_text), json_mode=True)
    except AllProvidersFailed as exc:
        log.error("Scoring failed for %s: %s", job.uid, redact(exc))
        return None
    data = extract_json(raw)
    if data is None:
        log.error("Scoring for %s returned no JSON: %s", job.uid, redact(repr(raw[:200])))
        return None
    result = normalize_result(data, job, min_score_cover_letter)
    if result is None:
        log.error("Scoring for %s returned JSON without a usable score: %r", job.uid, data)
    return result
