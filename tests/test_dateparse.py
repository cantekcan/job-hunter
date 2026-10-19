from datetime import date

import pytest

from src.dateparse import parse_relative_date

T = date(2026, 10, 18)


@pytest.mark.parametrize("text,expected", [
    ("Bugün", T), ("BUGÜN", T), ("Yeni", T), ("YENİ", T), ("Az önce", T),
    ("3 saat önce", T), ("15 dakika önce", T),
    ("Dün", date(2026, 10, 17)), ("DÜN", date(2026, 10, 17)),
    ("2 gün önce", date(2026, 10, 16)), ("1 hafta önce", date(2026, 10, 11)),
    ("2 ay önce", date(2026, 8, 19)),
    ("today", T), ("Yesterday", date(2026, 10, 17)), ("3 days ago", date(2026, 10, 15)),
    ("5 hours ago", T), ("Just now", T), ("JUST NOW", T), ("Posted 3 days ago", date(2026, 10, 15)),
    ("30+ days ago", date(2026, 9, 18)), ("a day ago", date(2026, 10, 17)),
    ("2026-10-18", T), ("2026-10-18T09:00:00Z", T), ("2026-10-17T23:30:00+03:00", date(2026, 10, 17)),
    ("18.10.2026", T), ("18 Ekim 2026", T), ("18 EKİM 2026", T), ("1 Şubat 2026", date(2026, 2, 1)),
    ("Güncellendi: Bugün", T),
])
def test_known_formats(text, expected):
    assert parse_relative_date(text, T) == expected


@pytest.mark.parametrize("text", ["", None, "   ", "foo bar", "31.02.2026", "18 Foo 2026"])
def test_unknown_returns_none(text):
    assert parse_relative_date(text, T) is None


@pytest.mark.parametrize("text,expected", [
    ("1 saat", T), ("3 dakika", T), ("2 gün", date(2026, 10, 16)), ("1 hafta", date(2026, 10, 11)),
    ("1 gün", date(2026, 10, 17)), ("5 gün önce güncellendi", date(2026, 10, 13)),
])
def test_bare_kariyernet_ages(text, expected):
    assert parse_relative_date(text, T) == expected


@pytest.mark.parametrize("text,expected", [
    ("16-10-2026", date(2026, 10, 16)), ("1.09.2026", date(2026, 9, 1)), ("İlan Tarihi: 3 gün önce", date(2026, 10, 15)),
    ("Şimdi", T), ("Son 1 Hafta", None), ("Son 3 Gün", None), ("16-10.2026", None),
])
def test_secretcv_yenibiris_indeed_formats(text, expected):
    assert parse_relative_date(text, T) == expected
