"""Job Hunter CLI.

    python -m src.main [--dry-run] [--limit N] [--no-ai] [--sources kariyernet] [--sample-html PATH]
"""
from __future__ import annotations

import argparse
import html
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

from .ai.providers import AllProvidersFailed, build_chain
from .config import Config, load_config
from .cover_letter import detect_language, generate_cover_letter, save_cover_letter
from .dateparse import parse_relative_date
from .filter import JobStore, is_excluded, is_recent, is_relevant
from .models import Job
from .notify import TelegramNotifier, format_message, format_summary
from .redact import install_log_redaction
from .report import ReportRow, write_report
from .scorer import score_job
from .scrapers import SCRAPERS, BaseScraper, SourceBlocked

log = logging.getLogger("job_hunter")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m src.main", description="Job Hunter günlük tarama")
    p.add_argument("--dry-run", action="store_true",
                   help="Telegram'a gönderme; DB'ye kalıcı yazma (geçmişe göre dedupe yine yapılır)")
    p.add_argument("--limit", type=int, default=None, help="En fazla N yeni ilanı işle")
    p.add_argument("--no-ai", action="store_true", help="Puanlama ve ön yazı adımlarını atla")
    p.add_argument("--sources", default=None, help="Virgülle ayrılmış kaynaklar (varsayılan: hepsi)")
    p.add_argument("--sample-html", type=Path, default=None,
                   help="Ağ yerine kaydedilmiş bir ilan listesi HTML'ini ayrıştır")
    p.add_argument("--print", dest="print_n", type=int, default=None, metavar="N",
                   help="İşlenen ilanlardan ilk N tanesini ekrana tablo olarak bas")
    p.add_argument("--once-per-day", action="store_true",
                   help="Bugün zaten başarılı bir çalışma olduysa hiçbir şey yapma (yedek zamanlama için)")
    p.add_argument("--check", action="store_true",
                   help="Sadece bağlantı testi: Telegram'a test mesajı at, AI anahtarlarını dene")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("%s not found", path)
        return ""


def build_scrapers(sources: list[str]) -> dict[str, BaseScraper]:
    scrapers: dict[str, BaseScraper] = {}
    for name in sources:
        scraper_cls = SCRAPERS.get(name)
        if scraper_cls is None:
            log.warning("Unknown source %r (registered: %s)", name, ", ".join(SCRAPERS) or "none")
            continue
        scrapers[name] = scraper_cls()
    return scrapers


def collect_jobs(cfg: Config, sources: list[str], sample_html: Optional[Path],
                 scrapers: Optional[dict[str, BaseScraper]] = None,
                 today: Optional[date] = None, raw_dir: Optional[Path] = None) -> list[Job]:
    """Run every scraper; a failing or blocked source never stops the others."""
    # Relative ages ("2 gün") must be resolved against the run's day, not the wall clock.
    jobs: list[Job] = []
    scrapers = build_scrapers(sources) if scrapers is None else scrapers
    sample = sample_html.read_text(encoding="utf-8") if sample_html else None
    if sample is not None and len(scrapers) > 1:
        sniffed = {n: s for n, s in scrapers.items() if s.sniff(sample)}
        scrapers = sniffed or scrapers  # parse a saved page only with the site(s) it belongs to
    deadline = time.monotonic() + float(getattr(cfg, "scrape_deadline_s", 1080) or 1080)
    for name, scraper in scrapers.items():
        if hasattr(scraper, "deadline") and getattr(scraper, "deadline", None) is None:
            scraper.deadline = deadline  # shared global scrape deadline (lists + details)
        if today is not None and hasattr(scraper, "today"):
            scraper.today = today
        if raw_dir is not None and hasattr(scraper, "raw_dir"):
            scraper.raw_dir = raw_dir / name
        try:
            if sample is not None:
                found = scraper.parse_html(sample)
                log.info("[%s] %d cards (sample)", name, len(found))
            elif hasattr(scraper, "fetch_all"):
                found = scraper.fetch_all(cfg)
            else:  # minimal scrapers that only implement fetch()
                found = []
                for query in cfg.search_queries:
                    try:
                        found += scraper.fetch(query, max_pages=cfg.max_pages)
                    except Exception:  # noqa: BLE001 - one failing query must not stop the run
                        log.exception("[%s] query %r failed", name, query)
            for job in found:
                job.source = job.source or name
            jobs += found
        except SourceBlocked as exc:
            log.warning("[%s] blocked (%s); source skipped for this run", name, exc)
        except Exception:  # noqa: BLE001
            log.exception("Scraper %s failed", name)
    return jobs


def default_sources(cfg: Config) -> list[str]:
    """``cfg.sources`` that are registered; falls back to every registered scraper."""
    configured = [s for s in getattr(cfg, "sources", []) or [] if s in SCRAPERS]
    unknown = [s for s in getattr(cfg, "sources", []) or [] if s not in SCRAPERS]
    if unknown:
        log.warning("Unknown sources in preferences ignored: %s", ", ".join(unknown))
    return configured or list(SCRAPERS)


def prepare(jobs: list[Job], today: date) -> list[Job]:
    """Dedupe within the batch and fill derived fields (posted_date, language)."""
    unique: dict[str, Job] = {}
    for job in jobs:
        if job.posted_date is None and job.posted_text:
            job.posted_date = parse_relative_date(job.posted_text, today)
        if job.language is None and job.description:
            job.language = detect_language(f"{job.title}\n{job.description}")
        unique.setdefault(job.uid, job)
    return list(unique.values())


def fetch_details(jobs: list[Job], scrapers: dict[str, BaseScraper], cap: int) -> None:
    """Fill descriptions from detail pages (only for new jobs, only when AI scoring runs)."""
    skipped: set[str] = set()
    for job in jobs[: max(cap, 0)]:
        scraper = scrapers.get(job.source)
        fetch = getattr(scraper, "fetch_detail", None)
        if fetch is None or job.description or job.source in skipped:
            continue
        deadline = getattr(scraper, "deadline", None)
        if getattr(scraper, "blocked", False) or (deadline is not None and time.monotonic() >= deadline):
            log.warning("[%s] blocked or scrape deadline reached; skipping remaining detail pages", job.source)
            skipped.add(job.source)
            continue
        try:
            fetch(job)
        except SourceBlocked as exc:
            log.warning("[%s] detail pages skipped for the rest of the run (%s)", job.source, exc)
            skipped.add(job.source)
        except Exception:  # noqa: BLE001 - a missing description only weakens the score
            log.exception("Detail fetch failed for %s", job.uid)


def _clip(text: str, width: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= width else text[: width - 1] + "…"


def format_table(rows: list[ReportRow]) -> str:
    cols = [("#", 2), ("Puan", 4), ("Tarih", 10), ("Başlık", 38), ("Şirket", 26), ("Lokasyon", 22),
            ("Model", 10), ("ID", 18)]
    line = lambda vals: "  ".join(_clip(str(v), w).ljust(w) for v, (_, w) in zip(vals, cols)).rstrip()
    out = [line([c for c, _ in cols]), line(["-" * w for _, w in cols])]
    for i, r in enumerate(rows, 1):
        score = r.result["score"] if r.result else "–"
        posted = r.job.posted_date.isoformat() if r.job.posted_date else (r.job.posted_text or "?")
        out.append(line([i, score, posted, r.job.title, r.job.company, r.job.location,
                         r.job.work_model, r.job.uid]))
    if not rows:
        out.append("(ilan yok)")
    return "\n".join(out)


class _GitHubAnnotations(logging.Handler):
    """In GitHub Actions, surface warnings as run annotations (visible without downloading logs)."""

    def __init__(self, limit: int = 8):
        super().__init__(logging.WARNING)
        self.left = limit

    def emit(self, record: logging.LogRecord) -> None:
        if self.left <= 0:
            return
        self.left -= 1
        msg = self.format(record).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::warning title={record.name}::{msg}", flush=True)


def _notice(title: str, text: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title={title}::" + text.replace("%", "%25").replace("\n", "%0A"), flush=True)


def _source_counts(*stages: tuple[str, list[Job]]) -> str:
    names = sorted({j.source for _, jobs in stages for j in jobs})
    lines = []
    for name in names:
        parts = [f"{label} {sum(1 for j in jobs if j.source == name)}" for label, jobs in stages]
        lines.append(f"{name}: " + ", ".join(parts))
    return "\n".join(lines) or "hiç ilan yok"


def _top_jobs(rows: list[ReportRow], n: int = 5) -> list[tuple[int, str, str, str]]:
    """Best-scored jobs of the day for the summary message (also the ones below the notify bar)."""
    scored = [r for r in rows if r.result]
    scored.sort(key=lambda r: r.result["score"], reverse=True)
    return [(r.result["score"], r.job.title, r.job.company, r.job.url) for r in scored[:n]]


def run(args: argparse.Namespace, cfg: Optional[Config] = None, today: Optional[date] = None) -> int:
    cfg = cfg or load_config()
    today = today or date.today()
    day_dir = cfg.output_dir / today.isoformat()

    sources = [s.strip() for s in args.sources.split(",") if s.strip()] if args.sources else default_sources(cfg)
    if not sources:
        log.warning("No scrapers registered yet (src/scrapers/__init__.py SCRAPERS is empty)")

    scrapers = build_scrapers(sources)
    found = prepare(collect_jobs(cfg, sources, args.sample_html, scrapers, today,
                                 day_dir / "raw" if cfg.save_raw_html else None), today)
    relevant = [j for j in found if is_relevant(j, cfg)]
    kept = [j for j in relevant if not is_excluded(j, cfg)]
    recent = [j for j in kept if is_recent(j, today, cfg.max_age_days)]
    log.info("Found %d, relevant title %d, after exclude %d, recent %d",
             len(found), len(relevant), len(kept), len(recent))

    store = JobStore.in_memory_copy(cfg.db_path) if args.dry_run else JobStore(cfg.db_path)
    notifier = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id,
                                cfg.telegram_enabled and not args.dry_run,
                                dryrun_path=day_dir / "telegram_dryrun.txt")
    rows: list[ReportRow] = []
    scored = notified = 0
    try:
        new = store.filter_new(recent, today)
        log.info("New (unseen) jobs: %d", len(new))

        chain = None if args.no_ai else build_chain(cfg)
        if chain is not None and not chain:
            log.warning("No AI provider has an API key; continuing without scoring")
            chain = None

        if chain is None:
            todo = new
        else:  # also retry jobs from earlier runs whose scoring failed
            new_uids = {j.uid for j in new}
            todo = new + [j for j in store.pending_unscored(today, cfg.max_age_days) if j.uid not in new_uids]
        if args.limit is not None:
            todo = todo[: max(args.limit, 0)]

        if chain is not None and not args.sample_html:  # offline sample runs never hit the network
            fetch_details(todo, scrapers, cfg.max_details)
            # a detail page may reveal the real (older) posting date of an undated card
            before = len(todo)
            todo = [j for j in todo if is_recent(j, today, cfg.max_age_days)]
            if len(todo) < before:
                log.info("Dropped %d job(s) whose detail page shows an older posting date", before - len(todo))

        cv_text, prefs_text = cfg.read_cv(), _read(cfg.prefs_path)
        for i, job in enumerate(todo):
            if chain is not None and i and cfg.ai_delay_s > 0:
                time.sleep(cfg.ai_delay_s)  # stay under the free-tier requests/tokens per minute
            if chain is None:
                rows.append(ReportRow(job, None))
                continue
            result = score_job(job, cv_text, prefs_text, chain, cfg.min_score_cover_letter)
            if result is None:
                rows.append(ReportRow(job, None))
                continue
            scored += 1
            store.set_score(job.uid, result["score"], result)
            row = ReportRow(job, result)
            rows.append(row)
            if result["score"] < cfg.min_score_notify:
                continue
            if result["on_yazi_gerekli"]:
                try:
                    letter = generate_cover_letter(job, cv_text, prefs_text, result, chain)
                    if getattr(chain, "last_ai", None):
                        result["ai_letter"] = chain.last_ai
                    row.letter_path = save_cover_letter(job, letter, cfg.output_dir, today, result["score"],
                                                        result.get("ai_letter"))
                except AllProvidersFailed as exc:
                    log.error("Cover letter failed for %s: %s", job.uid, exc)
            ok = notifier.send_message(format_message(job, result, row.letter_path is not None))
            if ok and row.letter_path:
                ok = notifier.send_document(row.letter_path, caption=f"Ön yazı – {html.escape(job.title)}") and ok
            if ok:
                row.notified = True
                notified += 1
                store.mark_notified(job.uid)

        stats = {"Bulunan": len(found), "Yeni": len(new), "Puanlanan": scored, "Bildirilen": notified}
        notifier.send_message(format_summary(len(found), len(new), notified,
                                             None if chain is None else scored, today.isoformat(),
                                             getattr(chain, "last_ai", None), top=_top_jobs(rows)))
        report = write_report(rows, cfg.output_dir, today, stats)
        log.info("Report written: %s", report)
        _notice("Kaynaklar", _source_counts(("bulunan", found), ("ilgili", relevant), ("son 24s", recent),
                                            ("yeni", new)))
        best = "\n".join(f"{s} · {t} – {c}" for s, t, c, _ in _top_jobs(rows, 8))
        if best:
            _notice("En iyi ilanlar", best)
        if args.print_n:
            print(format_table(rows[: args.print_n]))
    finally:
        store.close()
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        handler = _GitHubAnnotations()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
    install_log_redaction()  # after all handlers exist: it filters per handler
    if args.check:
        from .check import run_check
        return run_check(load_config())
    if args.once_per_day:
        cfg = load_config()
        marker = cfg.db_path.parent / "last_run_day"
        today = date.today().isoformat()
        try:
            if marker.read_text(encoding="utf-8").strip() == today:
                log.info("Already ran today (%s); nothing to do", today)
                return 0
        except FileNotFoundError:
            pass
        code = run(args, cfg)
        if code == 0:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(today, encoding="utf-8")
        return code
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
