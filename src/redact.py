"""Strip secrets (API keys, bot tokens) from text before it is logged or raised."""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable, Optional

_registered: set[str] = set()

_PATTERNS = [
    (re.compile(r"(/bot)\d+:[A-Za-z0-9_-]+"), r"\1***"),                      # Telegram URL token
    (re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b"), "***"),                   # bare Telegram token
    (re.compile(r"([?&](?:key|api_key|apikey|token)=)[^&\s'\"]+", re.I), r"\1***"),
    (re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.I), r"\1***"),
    (re.compile(r"(x-goog-api-key['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.I), r"\1***"),
]


def register_secret(value: Optional[str]) -> None:
    """Remember a secret value so :func:`redact` removes it wherever it appears."""
    if value and len(value.strip()) >= 4:
        _registered.add(value.strip())


def _env_secrets() -> Iterable[str]:
    for key, value in os.environ.items():
        if value and len(value) >= 4 and (key.endswith("_API_KEY") or key == "TELEGRAM_BOT_TOKEN"):
            yield value


def redact(value: Any) -> str:
    text = str(value)
    for secret in sorted({*_registered, *_env_secrets()}, key=len, reverse=True):
        if secret in text:
            text = text.replace(secret, "***")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactingFilter(logging.Filter):
    """Logging filter that redacts the fully formatted message (defense in depth)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging
            return True
        clean = redact(msg)
        if clean != msg:
            record.msg, record.args = clean, None
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            if redact(exc) != str(exc):
                record.exc_info = None
                record.exc_text = None
                record.msg = f"{record.msg} [{type(exc).__name__}: {redact(exc)}]"
        return True


def install_log_redaction(logger: Optional[logging.Logger] = None) -> None:
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())
