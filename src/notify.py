"""Telegram notifications (HTML parse mode) with a network-free dry-run mode."""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

from .models import Job
from .redact import redact, register_secret

log = logging.getLogger(__name__)

API = "https://api.telegram.org/bot{token}/{method}"
MAX_LEN = 4000  # Telegram's hard limit is 4096
MAX_ITEMS = 5


def score_emoji(score: int) -> str:
    if score >= 70:
        return "🟢"
    if score >= 50:
        return "🟡"
    return "🔴"


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def format_message(job: Job, score_result: dict[str, Any], has_letter: bool) -> str:
    score = int(score_result.get("score", 0))
    place = ", ".join(p for p in (job.location, job.work_model) if p)
    title = f"{score_emoji(score)} <b>{score}/100</b> – {_e(job.title)} – {_e(job.company)}"
    if place:
        title += f" ({_e(place)})"
    lines = [title]

    eslesen = ", ".join(_e(x) for x in score_result.get("eslesen", [])[:MAX_ITEMS])
    eksik = ", ".join(_e(x) for x in score_result.get("eksik", [])[:MAX_ITEMS])
    detail = " · ".join(p for p in (eslesen and f"Eşleşen: {eslesen}", eksik and f"Eksik: {eksik}") if p)
    if detail:
        lines.append(detail)
    if score_result.get("ozet"):
        lines.append(f"<i>{_e(score_result['ozet'])}</i>")

    footer = [f'🔗 <a href="{_e(job.url)}">link</a>'] if job.url else []
    if has_letter:
        footer.append("📄 ön yazı ekte")
    if footer:
        lines.append(" · ".join(footer))
    return "\n".join(lines)


def format_summary(found: int, new: int, notified: int, scored: Optional[int] = None,
                   day: Optional[str] = None) -> str:
    day = day or datetime.now().date().isoformat()
    parts = [f"📊 <b>Günlük özet – {_e(day)}</b>", f"Bulunan: {found}", f"Yeni: {new}"]
    if scored is not None:
        parts.append(f"Puanlanan: {scored}")
    parts.append(f"Bildirilen: {notified}")
    return "\n".join(parts[:1]) + "\n" + " · ".join(parts[1:])


def _safe_cut(line: str, limit: int) -> int:
    """Cut index <= limit that is not inside an HTML entity (&...;) or tag (<...>)."""
    cut = limit
    amp = line.rfind("&", max(0, cut - 10), cut)
    if amp != -1 and line.find(";", amp, cut) == -1:
        cut = amp
    lt = line.rfind("<", 0, cut)
    if lt != -1 and line.find(">", lt, cut) == -1 and cut - lt < limit:
        cut = lt
    return cut if cut > 0 else limit


def split_message(text: str, limit: int = MAX_LEN) -> list[str]:
    """Split on line boundaries; long lines are cut outside HTML entities and tags."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            cut = _safe_cut(line, limit)
            chunks.append(line[:cut])
            line = line[cut:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, enabled: bool,
                 dryrun_path: Optional[Path] = None, timeout: float = 30):
        self.token = token
        register_secret(token)
        self.chat_id = chat_id
        self.timeout = timeout
        self.dryrun_path = Path(dryrun_path) if dryrun_path else None
        self.dry_run = not (enabled and token and chat_id)
        if self.dry_run:
            log.info("Telegram in DRY-RUN mode (enabled=%s, token=%s, chat_id=%s)",
                     enabled, bool(token), bool(chat_id))

    def _dry(self, kind: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"----- [{stamp}] {kind} -----\n{text}\n\n"
        log.info("[DRY-RUN telegram %s]\n%s", kind, text)
        if self.dryrun_path:
            self.dryrun_path.parent.mkdir(parents=True, exist_ok=True)
            with self.dryrun_path.open("a", encoding="utf-8") as fh:
                fh.write(entry)

    def _call(self, method: str, **kwargs: Any) -> bool:
        try:
            resp = requests.post(API.format(token=self.token, method=method), timeout=self.timeout, **kwargs)
        except requests.RequestException as exc:
            log.error("Telegram %s failed: %s", method, redact(exc))
            return False
        if resp.status_code != 200:
            log.error("Telegram %s HTTP %s: %s", method, resp.status_code, redact(resp.text[:200]))
            return False
        return True

    def send_message(self, text: str) -> bool:
        ok = True
        for chunk in split_message(text):
            if self.dry_run:
                self._dry("message", chunk)
                continue
            ok &= self._call("sendMessage", data={
                "chat_id": self.chat_id, "text": chunk,
                "parse_mode": "HTML", "disable_web_page_preview": "true",
            })
        return ok

    def send_document(self, path: Path, caption: str = "") -> bool:
        path = Path(path)
        caption = caption[:1000]  # Telegram caption limit is 1024
        if self.dry_run:
            self._dry("document", f"{path.name}\n{caption}".strip())
            return True
        with path.open("rb") as fh:
            return self._call(
                "sendDocument",
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "HTML"},
                files={"document": (path.name, fh, "text/markdown")},
            )
