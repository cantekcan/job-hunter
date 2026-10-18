"""Configuration: secrets from .env + the ```yaml block at the end of profile/preferences.md.

PyYAML is intentionally not used; ``parse_simple_yaml`` understands only what we need:
flat ``key: value`` scalars (int / bool / string), ``key:`` followed by ``- item`` lists,
quoted strings and ``#`` comments.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from dotenv import dotenv_values

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_PREFS: dict[str, Any] = {
    "search_queries": [".net developer", "senior .net developer", "backend developer"],
    "exclude_title_keywords": ["junior", "stajyer", "intern", "java", "frontend"],
    "include_locations": ["istanbul", "remote", "uzaktan"],
    "min_score_notify": 50,
    "min_score_cover_letter": 70,
    "max_age_days": 1,
    "max_pages": 3,
    "max_details": 40,
}

_YAML_BLOCK_RE = re.compile(r"^```ya?ml[^\n]*\n(.*?)^```", re.DOTALL | re.IGNORECASE | re.MULTILINE)


def _strip_comment(line: str) -> str:
    """Remove a trailing ``# comment`` that is not inside quotes."""
    quote: Optional[str] = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _scalar(raw: str) -> Any:
    v = raw.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    if v.lower() in ("true", "yes", "on"):
        return True
    if v.lower() in ("false", "no", "off"):
        return False
    if v.lower() in ("null", "~", ""):
        return None
    return v


def parse_simple_yaml(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list: Optional[str] = None
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if current_list is None:
                log.warning("YAML list item without key ignored: %r", raw_line)
                continue
            result[current_list].append(_scalar(stripped[2:]))
            continue
        m = re.match(r"^([A-Za-z_][\w\-]*)\s*:\s*(.*)$", stripped)
        if not m:
            log.warning("Unparsed YAML line ignored: %r", raw_line)
            continue
        key, value = m.group(1), m.group(2)
        if value == "":
            result[key] = []
            current_list = key
        else:
            result[key] = _scalar(value)
            current_list = None
    return result


def extract_config_block(markdown: str) -> Optional[str]:
    """Return the last ```yaml block of the markdown (the machine-readable config)."""
    blocks = _YAML_BLOCK_RE.findall(markdown)
    return blocks[-1] if blocks else None


def load_preferences(path: Path) -> dict[str, Any]:
    prefs = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_PREFS.items()}
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        log.warning("Preferences file not found (%s); using defaults", path)
        return prefs
    block = extract_config_block(text)
    if block is None:
        log.warning("No ```yaml config block in %s; using defaults", path)
        return prefs
    for key, value in parse_simple_yaml(block).items():
        default = DEFAULT_PREFS.get(key)
        if isinstance(default, int) and not isinstance(value, int):
            log.warning("Config %s=%r is not an int; keeping default %s", key, value, default)
            continue
        if isinstance(default, list) and not isinstance(value, list):
            value = [value]
        prefs[key] = value
    return prefs


def _cv_from_env(env: Mapping[str, str]) -> str:
    if (env.get("CV_MD") or "").strip():
        return env["CV_MD"]
    b64 = (env.get("CV_MD_B64") or "").strip()
    if b64:
        try:
            return base64.b64decode(b64).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exc:
            log.error("CV_MD_B64 could not be decoded (%s); falling back to profile/cv.md", exc)
    return ""


def _bool(v: Optional[str]) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Config:
    root: Path
    search_queries: list[str]
    exclude_title_keywords: list[str]
    include_locations: list[str]
    min_score_notify: int
    min_score_cover_letter: int
    max_age_days: int
    max_pages: int
    ai_providers: list[str]
    max_details: int = 40
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    groq_model_strong: str = "llama-3.3-70b-versatile"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    gemini_model_strong: str = "gemini-2.0-flash"
    xai_api_key: str = ""
    xai_model: str = "grok-3-mini"
    xai_model_strong: str = "grok-3"
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_enabled: bool = False
    cv_md: str = ""  # CV text from env (CV_MD / CV_MD_B64); overrides profile/cv.md
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def cv_path(self) -> Path:
        return self.root / "profile" / "cv.md"

    def read_cv(self) -> str:
        """CV text: env CV_MD / CV_MD_B64 if set (keeps cv.md out of a public repo), else profile/cv.md."""
        if self.cv_md.strip():
            return self.cv_md
        try:
            return self.cv_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            log.warning("CV not found: set CV_MD / CV_MD_B64 or create %s", self.cv_path)
            return ""

    @property
    def prefs_path(self) -> Path:
        return self.root / "profile" / "preferences.md"

    @property
    def db_path(self) -> Path:
        return self.root / "data" / "jobs.db"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"


def load_config(
    root: Optional[Path] = None,
    env: Optional[Mapping[str, str]] = None,
    prefs_path: Optional[Path] = None,
) -> Config:
    """Build the Config. ``env`` overrides the environment (tests pass a dict and skip .env)."""
    root = Path(root) if root else ROOT
    if env is None:
        merged: dict[str, str] = {k: v for k, v in dotenv_values(root / ".env").items() if v is not None}
        merged.update(os.environ)  # real environment wins over .env
        env = merged

    def e(key: str, default: str = "") -> str:
        return (env.get(key) or default).strip()

    prefs = load_preferences(prefs_path or root / "profile" / "preferences.md")
    known = {k: prefs[k] for k in DEFAULT_PREFS}
    extra = {k: v for k, v in prefs.items() if k not in DEFAULT_PREFS}

    gemini_model = e("GEMINI_MODEL", "gemini-2.0-flash")
    xai_model = e("XAI_MODEL", "grok-3-mini")
    return Config(
        root=root,
        **known,
        extra=extra,
        ai_providers=[p.strip().lower() for p in e("AI_PROVIDERS", "groq,gemini").split(",") if p.strip()],
        groq_api_key=e("GROQ_API_KEY"),
        groq_model=e("GROQ_MODEL", "llama-3.1-8b-instant"),
        groq_model_strong=e("GROQ_MODEL_STRONG", "llama-3.3-70b-versatile"),
        gemini_api_key=e("GEMINI_API_KEY"),
        gemini_model=gemini_model,
        gemini_model_strong=e("GEMINI_MODEL_STRONG", gemini_model),
        xai_api_key=e("XAI_API_KEY"),
        xai_model=xai_model,
        xai_model_strong=e("XAI_MODEL_STRONG", "grok-3"),
        telegram_bot_token=e("TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=e("TELEGRAM_CHAT_ID"),
        telegram_enabled=_bool(env.get("TELEGRAM_ENABLED")),
        cv_md=_cv_from_env(env),
    )
