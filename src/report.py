"""Daily Markdown report: output/YYYY-MM-DD/report.md."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .models import Job


@dataclass
class ReportRow:
    job: Job
    result: Optional[dict[str, Any]]  # None = not scored (--no-ai or AI failure)
    letter_path: Optional[Path] = None
    notified: bool = False


def _cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


def write_report(rows: list[ReportRow], output_dir: Path, today: date,
                 stats: Optional[dict[str, int]] = None) -> Path:
    day_dir = Path(output_dir) / today.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / "report.md"

    ordered = sorted(rows, key=lambda r: (r.result is None, -(r.result or {}).get("score", 0)))
    lines = [f"# Job Hunter raporu – {today.isoformat()}", ""]
    if stats:
        lines += [" · ".join(f"**{k}:** {v}" for k, v in stats.items()), ""]
    if not ordered:
        lines.append("_Bugün yeni ilan yok._")
    else:
        lines += [
            "| Puan | Başlık | Şirket | Lokasyon | Eşleşen | Eksik | Ön yazı | Bildirildi |",
            "|---:|---|---|---|---|---|---|:-:|",
        ]
        for r in ordered:
            res = r.result or {}
            score = res.get("score", "–") if r.result else "–"
            title = f"[{_cell(r.job.title)}]({r.job.url})" if r.job.url else _cell(r.job.title)
            place = ", ".join(p for p in (r.job.location, r.job.work_model) if p)
            letter = f"[{r.letter_path.name}]({r.letter_path.name})" if r.letter_path else ""
            lines.append(
                f"| {score} | {title} | {_cell(r.job.company)} | {_cell(place)} | "
                f"{_cell(', '.join(res.get('eslesen', [])))} | {_cell(', '.join(res.get('eksik', [])))} | "
                f"{letter} | {'✓' if r.notified else ''} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
