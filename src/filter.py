"""Filtering and de-duplication.

Three-layer date rule (only ads from the last ~24h are processed):

1. **URL date filter (scraper):** each scraper asks the site for "last 24 hours" ads via its
   own search parameter, so most old ads never reach us.
2. **Relative date parse:** ``posted_text`` ("Bugün", "Dün", "2 gün önce") is parsed by
   :func:`src.dateparse.parse_relative_date`; :func:`is_recent` drops anything older than
   ``today - max_age_days``. Unparseable dates are *kept* and flagged ``date_unknown``.
3. **first_seen DB dedupe:** :class:`JobStore` remembers every uid with the day it was first
   seen, so an ad is processed once even if its date is unknown or the site re-bumps it.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Union

from .config import Config
from .models import Job
from .textutil import fold

log = logging.getLogger(__name__)

DATE_UNKNOWN = "date_unknown"


def is_recent(job: Job, today: date, max_age_days: int = 1) -> bool:
    """True if ``posted_date`` is within ``today - max_age_days .. today`` (future dates allowed).

    Jobs without a date are kept (the DB dedupe is the safety net) and flagged.
    """
    if job.posted_date is None:
        if DATE_UNKNOWN not in job.flags:
            job.flags.append(DATE_UNKNOWN)
        log.debug("No posted date for %s (%r); keeping", job.uid, job.posted_text)
        return True
    return job.posted_date >= today - timedelta(days=max_age_days)


# Plural / derivational suffixes accepted after a keyword ("stajyerleri", "mezunlar", "interns").
_SUFFIX = r"(?:s|es|ship|ships|ler|lar|leri|lari|lerin|larin|lik|luk|ligi|lugu)?"
# Keywords that must match as an exact whole word (no suffixes): "java" must never hit "javascript".
STRICT_KEYWORDS = {"java"}


def _normalize(text: str) -> str:
    """Fold Turkish chars, treat '-', '_' and '/' as spaces and collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[-_/]", " ", fold(text))).strip()


@lru_cache(maxsize=512)
def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    """Whole-word pattern; boundaries are only enforced on alphanumeric edges.

    "java" -> (?<![a-z0-9])java(?![a-z0-9]) : matches "Java Developer", "Java/Spring",
    not "JavaScript". Other keywords also accept plural suffixes ("stajyer" -> "stajyerleri").
    "jr." needs only a left boundary because it ends with a dot.
    """
    kw = _normalize(keyword)
    left = r"(?<![a-z0-9])" if kw[:1].isalnum() else ""
    if kw[-1:].isalnum():
        right = ("" if kw in STRICT_KEYWORDS else _SUFFIX) + r"(?![a-z0-9])"
    else:
        right = ""
    return re.compile(left + re.escape(kw).replace(r"\ ", " ") + right)


def matching_exclude_keyword(title: str, keywords: Iterable[str]) -> Optional[str]:
    normalized = _normalize(title)
    for kw in keywords:
        if kw and _normalize(kw) and _keyword_pattern(kw).search(normalized):
            return kw
    return None


def is_excluded(job: Job, cfg: Union[Config, Iterable[str]]) -> bool:
    """True if the title contains an excluded keyword (Turkish-aware, whole-word)."""
    keywords = cfg.exclude_title_keywords if isinstance(cfg, Config) else list(cfg)
    hit = matching_exclude_keyword(job.title, keywords)
    if hit:
        log.debug("Excluded %s %r by keyword %r", job.uid, job.title, hit)
    return hit is not None


def is_relevant(job: Job, cfg: Union[Config, Iterable[str]]) -> bool:
    """True if the title has at least one include keyword (empty list = everything is relevant).

    Kariyer.net pads search results with "similar" and generic ads (store clerks, drivers ...);
    this drops them before any AI call is spent on them.
    """
    keywords = cfg.include_title_keywords if isinstance(cfg, Config) else list(cfg)
    if not keywords:
        return True
    hit = matching_exclude_keyword(job.title, keywords)
    if not hit:
        log.debug("Not relevant %s %r (no include keyword)", job.uid, job.title)
    return hit is not None


class JobStore:
    """SQLite store of every job ever seen, used for dedupe and score bookkeeping."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS jobs (
        uid TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        title TEXT,
        company TEXT,
        url TEXT,
        first_seen DATE NOT NULL,
        posted_date DATE,
        score INTEGER NULL,
        notified INTEGER NOT NULL DEFAULT 0,
        payload JSON,
        result JSON
    )
    """

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(self.SCHEMA)
        self.conn.commit()

    @classmethod
    def in_memory_copy(cls, path: Union[str, Path]) -> "JobStore":
        """In-memory store seeded from ``path`` (if it exists): dedupes against history, persists nothing."""
        store = cls(":memory:")
        if Path(path).exists():
            src = sqlite3.connect(str(path))
            try:
                src.backup(store.conn)
            finally:
                src.close()
            store.conn.execute(cls.SCHEMA)
        return store

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "JobStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def is_seen(self, uid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM jobs WHERE uid = ?", (uid,)).fetchone() is not None

    def add(self, job: Job, first_seen: date) -> bool:
        """Insert the job; returns False if it was already stored."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO jobs (uid, source, title, company, url, first_seen, posted_date, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.uid, job.source, job.title, job.company, job.url, first_seen.isoformat(),
                job.posted_date.isoformat() if job.posted_date else None,
                json.dumps(job.to_dict(), ensure_ascii=False),
            ),
        )
        self.conn.commit()
        return cur.rowcount == 1

    def set_score(self, uid: str, score: int, result_json: Union[str, dict[str, Any]]) -> None:
        if not isinstance(result_json, str):
            result_json = json.dumps(result_json, ensure_ascii=False)
        self.conn.execute("UPDATE jobs SET score = ?, result = ? WHERE uid = ?", (score, result_json, uid))
        self.conn.commit()

    def mark_notified(self, uid: str) -> None:
        self.conn.execute("UPDATE jobs SET notified = 1 WHERE uid = ?", (uid,))
        self.conn.commit()

    def get(self, uid: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM jobs WHERE uid = ?", (uid,)).fetchone()

    def filter_new(self, jobs: Iterable[Job], today: date) -> list[Job]:
        """Return only never-seen jobs (deduped within the batch too) and store them."""
        new: list[Job] = []
        for job in jobs:
            if self.add(job, today):
                new.append(job)
        return new

    def pending_unscored(self, today: date, max_age_days: int = 1) -> list[Job]:
        """Recently first-seen jobs that still have no score (e.g. all AI providers failed)."""
        since = (today - timedelta(days=max_age_days)).isoformat()
        rows = self.conn.execute(
            "SELECT payload FROM jobs WHERE score IS NULL AND first_seen >= ? ORDER BY first_seen",
            (since,),
        ).fetchall()
        return [Job.from_dict(json.loads(r["payload"])) for r in rows if r["payload"]]
