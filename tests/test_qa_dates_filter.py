"""QA: date rule + title exclusion (black-box, adversarial)."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from src.config import load_preferences
from src.dateparse import parse_relative_date
from src.filter import DATE_UNKNOWN, is_excluded, is_recent
from tests.conftest import TODAY, make_job

ROOT = Path(__file__).resolve().parent.parent
REAL_KEYWORDS = load_preferences(ROOT / "profile" / "preferences.md")["exclude_title_keywords"]
Y = TODAY - timedelta(days=1)


def _passes(text):
    job = make_job(posted_text=text, posted_date=parse_relative_date(text, TODAY))
    return is_recent(job, TODAY, 1), job


@pytest.mark.parametrize("text", [
    "Bugün", "BUGÜN", "bugün", "Dün", "DÜN", "dün", "Today", "TODAY", "Yesterday", "YESTERDAY",
    "3 saat önce", "15 dakika önce", "5 dk önce", "az önce", "Yeni", "just now", "an hour ago",
    "2 hours ago", "1 gün önce", "bir gün önce", "a day ago", "1 day ago", "Posted 1 day ago",
    "2026-10-18", "2026-10-17T23:59:00Z", "18.10.2026", "17 Ekim 2026", "17 October 2026",
])
def test_today_or_yesterday_pass(text):
    ok, job = _passes(text)
    assert job.posted_date in (TODAY, Y), text
    assert ok and DATE_UNKNOWN not in job.flags


@pytest.mark.parametrize("text", [
    "2 gün önce", "2 GÜN ÖNCE", "iki gün önce", "3 gün önce", "2 days ago", "two days ago",
    "1 hafta önce", "1 week ago", "1 ay önce", "30+ gün önce", "Posted 30+ days ago",
    "2026-10-16", "16.10.2026", "1 yıl önce",
])
def test_two_days_or_older_dropped(text):
    ok, job = _passes(text)
    assert job.posted_date is not None and job.posted_date <= TODAY - timedelta(days=2), text
    assert not ok


@pytest.mark.xfail(reason="BUG: hour/minute units map to 0 days regardless of quantity; "
                          "'48 saat önce' is parsed as today and passes the 24h rule", strict=True)
@pytest.mark.parametrize("text,expected", [
    ("48 saat önce", TODAY - timedelta(days=2)),
    ("72 hours ago", TODAY - timedelta(days=3)),
])
def test_large_hour_counts_are_old(text, expected):
    assert parse_relative_date(text, TODAY) == expected


@pytest.mark.parametrize("text", ["", "   ", None, "Pazartesi", "İlan tarihi belirtilmemiş", "???"])
def test_unknown_date_kept_and_flagged(text):
    job = make_job(posted_text=text or "", posted_date=parse_relative_date(text, TODAY))
    assert job.posted_date is None
    assert is_recent(job, TODAY, 1) is True
    assert job.flags.count(DATE_UNKNOWN) == 1
    is_recent(job, TODAY, 1)
    assert job.flags.count(DATE_UNKNOWN) == 1  # idempotent


def test_dun_not_matched_inside_word():
    assert parse_relative_date("Dünya Bankası projesi", TODAY) is None


# ---------------- exclusion ----------------

@pytest.mark.parametrize("title", [
    "Junior .NET Developer", "JUNİOR .NET Developer", "JUNIOR Backend Developer", "Jr. C# Developer",
    "Stajyer Yazılım Geliştirici", "STAJYER", "Yazılım Stajı (staj)", "İntern - Backend",
    "INTERN Software Engineer", "Software Engineering Internship", "Yeni Mezun Yazılım Uzmanı",
    "YENİ MEZUN .NET", "Java Developer", "Senior JAVA Developer", "Java/Spring Developer",
    "Frontend Developer", "Mobil Uygulama Geliştirici", "Trainee Engineer", "Junior/Mid Backend",
])
def test_excluded_titles(title):
    assert is_excluded(make_job(title=title), REAL_KEYWORDS), title


@pytest.mark.parametrize("title", [
    "JavaScript Developer", "Senior .NET Developer", "Backend Developer (C#)", "Mobilya Firması .NET Developer",
    "Otomobil Yazılım .NET Uzmanı", "Internal Tools Engineer (.NET)", "International Payments C# Developer",
    "Instaj Teknoloji .NET Developer", "Kıdemli Yazılım Geliştirici", "AI Engineer", "Senior Software Engineer .NET",
    "Biosphere .NET Developer", "Studios Backend Developer",
])
def test_not_excluded_titles(title):
    assert not is_excluded(make_job(title=title), REAL_KEYWORDS), title


@pytest.mark.xfail(reason="BUG: whole-word right boundary breaks Turkish/English suffixes "
                          "('Stajyerleri', 'Mezunlar', 'Interns' are not excluded)", strict=True)
@pytest.mark.parametrize("title", ["Yazılım Stajyerleri", "Yeni Mezunlar için .NET Programı", "Software Engineering Interns"])
def test_suffixed_exclusion_words(title):
    assert is_excluded(make_job(title=title), REAL_KEYWORDS)


@pytest.mark.xfail(reason="BUG: keyword 'jr ' (trailing space) needs a literal space, so 'Developer (Jr)' "
                          "and 'Jr/Mid' slip through; 'entry level' misses 'Entry-Level'", strict=True)
@pytest.mark.parametrize("title", ["Backend Developer (Jr)", "Jr/Mid .NET Developer", "Entry-Level .NET Developer"])
def test_jr_and_entry_level_variants(title):
    assert is_excluded(make_job(title=title), REAL_KEYWORDS)
