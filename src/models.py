"""Core data models."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Optional


@dataclass
class Job:
    source: str
    external_id: str
    title: str
    company: str = ""
    location: str = ""
    work_model: str = ""  # e.g. "hibrit", "remote", "ofiste"
    url: str = ""
    posted_text: str = ""  # raw relative date text from the site ("2 gün önce")
    posted_date: Optional[date] = None
    description: str = ""
    language: Optional[str] = None  # 'tr' | 'en' | None
    flags: list[str] = field(default_factory=list)  # e.g. ["date_unknown"]

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.external_id}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["posted_date"] = self.posted_date.isoformat() if self.posted_date else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Job":
        d = dict(d)
        pd = d.get("posted_date")
        d["posted_date"] = date.fromisoformat(pd) if pd else None
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})
