from datetime import date, timedelta

import pytest

from src.filter import DATE_UNKNOWN, JobStore, is_excluded, is_recent
from tests.conftest import make_job

KEYWORDS = ["junior", "jr.", "jr ", "stajyer", "intern", "java", "spring boot", "frontend", "ios", "mobil"]


@pytest.mark.parametrize("title,excluded", [
    ("Java Developer", True),
    ("Senior JAVA Developer", True),
    ("Java/Spring Backend Developer", True),
    ("JavaScript Developer", False),
    ("Senior .NET Developer (JavaScript bilgisi artı)", False),
    ("Junior .NET Developer", True),
    ("JUNİOR Yazılım Geliştirici", True),
    ("Jr. Backend Developer", True),
    ("Backend Developer Jr", True),
    ("Stajyer Yazılım", True),
    ("Internal Tools .NET Developer", False),
    ("İOS Developer", True),
    ("IOS Developer", True),
    ("Biosystems .NET Engineer", False),
    ("Mobil Uygulama Geliştirici", True),
    ("Senior .NET Developer", False),
])
def test_is_excluded(title, excluded):
    assert is_excluded(make_job(title=title), KEYWORDS) is excluded


def test_is_excluded_accepts_config(tmp_path):
    from src.config import load_config
    cfg = load_config(root=tmp_path, env={})  # no prefs file -> defaults include "java"
    assert is_excluded(make_job(title="Java Developer"), cfg)
    assert not is_excluded(make_job(title="JavaScript Developer"), cfg)


def test_is_recent(today):
    assert is_recent(make_job(posted_date=today), today)
    assert is_recent(make_job(posted_date=today - timedelta(days=1)), today)
    assert not is_recent(make_job(posted_date=today - timedelta(days=2)), today)
    assert is_recent(make_job(posted_date=today - timedelta(days=3)), today, max_age_days=3)


def test_is_recent_unknown_date_kept_and_flagged(today):
    job = make_job(posted_date=None)
    assert is_recent(job, today)
    assert DATE_UNKNOWN in job.flags


def test_store_dedupe_across_runs(tmp_path, today):
    db = tmp_path / "jobs.db"
    run1 = [make_job(external_id="1"), make_job(external_id="2"), make_job(external_id="2")]
    with JobStore(db) as store:
        new1 = store.filter_new(run1, today)
    assert [j.uid for j in new1] == ["test:1", "test:2"]

    run2 = [make_job(external_id="2"), make_job(external_id="3")]
    with JobStore(db) as store:  # reopen: simulates the next day's run
        new2 = store.filter_new(run2, today + timedelta(days=1))
        assert [j.uid for j in new2] == ["test:3"]
        assert store.is_seen("test:1")
        assert store.get("test:3")["first_seen"] == (today + timedelta(days=1)).isoformat()


def test_store_score_notify_and_pending(tmp_path, today):
    with JobStore(tmp_path / "jobs.db") as store:
        store.filter_new([make_job(external_id="1", posted_date=today), make_job(external_id="2")], today)
        assert {j.uid for j in store.pending_unscored(today)} == {"test:1", "test:2"}
        store.set_score("test:1", 82, {"score": 82})
        store.mark_notified("test:1")
        row = store.get("test:1")
        assert row["score"] == 82 and row["notified"] == 1
        pending = store.pending_unscored(today)
        assert [j.uid for j in pending] == ["test:2"]
        assert pending[0].title == "Senior .NET Developer"
        assert store.pending_unscored(today + timedelta(days=5)) == []


def test_in_memory_copy_does_not_persist(tmp_path, today):
    db = tmp_path / "jobs.db"
    with JobStore(db) as store:
        store.filter_new([make_job(external_id="1")], today)
    mem = JobStore.in_memory_copy(db)
    assert mem.is_seen("test:1")
    assert [j.uid for j in mem.filter_new([make_job(external_id="9")], today)] == ["test:9"]
    mem.close()
    with JobStore(db) as store:
        assert not store.is_seen("test:9")


def test_possessive_suffix_is_excluded():
    from src.filter import matching_exclude_keyword
    assert matching_exclude_keyword("Yazılım Stajyeri", ["stajyer"]) == "stajyer"
    assert matching_exclude_keyword("JavaScript Developer", ["java"]) is None
