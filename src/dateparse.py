"""Parse the relative / absolute posting dates job sites show ("2 gün önce", "Dün", "2026-10-18")."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .textutil import fold

# Folded (ASCII) Turkish and English month names -> month number.
MONTHS: dict[str, int] = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6,
    "temmuz": 7, "agustos": 8, "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# unit -> seconds per unit. Whole elapsed days are subtracted, so "3 saat önce" is today and
# "48 saat önce" is two days ago (``today`` carries no time of day, so this is the stable choice).
_M, _H, _D = 60, 3600, 86400
_UNITS: dict[str, int] = {
    "saniye": 1, "dakika": _M, "dk": _M, "saat": _H,
    "gun": _D, "hafta": 7 * _D, "ay": 30 * _D, "yil": 365 * _D,
    "second": 1, "seconds": 1, "sec": 1, "secs": 1,
    "minute": _M, "minutes": _M, "min": _M, "mins": _M,
    "hour": _H, "hours": _H, "hr": _H, "hrs": _H,
    "day": _D, "days": _D, "week": 7 * _D, "weeks": 7 * _D,
    "month": 30 * _D, "months": 30 * _D, "year": 365 * _D, "years": 365 * _D,
}
_UNIT_RE = "|".join(sorted(_UNITS, key=len, reverse=True))
_NUM_WORDS = {"bir": 1, "a": 1, "an": 1, "one": 1, "iki": 2, "two": 2, "uc": 3, "three": 3}

_REL_RE = re.compile(
    rf"(?<![\w])(\d+|bir|iki|uc|an|a|one|two|three)\+?\s*({_UNIT_RE})\b\s*(?:once|ago)?"
)
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?")
_DMY_RE = re.compile(r"\b(\d{1,2})([./-])(\d{1,2})\2(\d{4})\b")  # 18.10.2026, 1.09.2026, 16-10-2026
# Coarse filter labels such as "Son 1 Hafta" / "Son 3 Gün" are a range, not a posting date.
_RANGE_RE = re.compile(r"\bson\s+\d+\s*(dakika|saat|gun|hafta|ay)\b")
_TEXT_DATE_RE = re.compile(r"\b(\d{1,2})\s+([a-z]+)\.?,?\s+(\d{4})\b")

_TODAY_RE = re.compile(r"\b(bugun|yeni|az once|simdi|today|just now|just posted)\b")
_YESTERDAY_RE = re.compile(r"\b(dun|yesterday)\b")


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_relative_date(text: Optional[str], today: Optional[date] = None) -> Optional[date]:
    """Return the calendar date a posting refers to, or None if it cannot be understood."""
    if not text or not text.strip():
        return None
    today = today or date.today()
    raw = text.strip()

    m = _ISO_RE.search(raw)
    if m:  # timestamps keep their own calendar date; no timezone conversion
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _DMY_RE.search(raw)
    if m:
        return _safe_date(int(m.group(4)), int(m.group(3)), int(m.group(1)))

    s = fold(raw)

    m = _TEXT_DATE_RE.search(s)
    if m and m.group(2) in MONTHS:
        return _safe_date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))

    if _RANGE_RE.search(s):
        return None

    m = _REL_RE.search(s)
    if m:
        qty_raw, unit = m.group(1), m.group(2)
        qty = int(qty_raw) if qty_raw.isdigit() else _NUM_WORDS[qty_raw]
        return today - timedelta(days=(qty * _UNITS[unit]) // _D)

    if _YESTERDAY_RE.search(s):
        return today - timedelta(days=1)
    if _TODAY_RE.search(s):
        return today
    return None
