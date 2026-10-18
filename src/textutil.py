"""Turkish-aware text helpers shared by date parsing, filtering and slugs."""
from __future__ import annotations

import re
import unicodedata


def tr_lower(text: str) -> str:
    """Lowercase with Turkish rules: 'İ' -> 'i', 'I' -> 'ı'."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def fold(text: str) -> str:
    """Aggressive ASCII fold for matching: Turkish-lowercase, strip diacritics, ı -> i.

    "Bugün" -> "bugun", "DÜN" -> "dun", "TODAY" -> "today" (I -> ı -> i).
    """
    s = tr_lower(text)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.replace("ı", "i")


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")
    return (s[:max_len].rstrip("-")) or "ilan"
