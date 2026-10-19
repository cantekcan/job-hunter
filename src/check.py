"""Connection check: ``python -m src.main --check`` (also the "check" mode of the workflow).

Sends one Telegram test message (even if TELEGRAM_ENABLED is false) and asks every configured
AI provider for a tiny answer, so a manual GitHub Actions run shows whether the secrets work.
"""
from __future__ import annotations

import logging
from datetime import datetime

from .ai.providers import ProviderChain, build_chain
from .config import Config
from .notify import TelegramNotifier

log = logging.getLogger(__name__)


def run_check(cfg: Config) -> int:
    lines: list[str] = []
    ok = True

    chain = build_chain(cfg)
    if not chain:
        lines.append("❌ AI: hiçbir sağlayıcı için API anahtarı yok")
        ok = False
    for provider in chain.providers:
        try:
            one = ProviderChain([provider])
            one.complete("Sadece 'OK' yaz.", "ping")
            lines.append(f"✅ AI: {one.last_ai} çalışıyor")
        except Exception:  # noqa: BLE001 - details are already logged (redacted) by the chain
            lines.append(f"❌ AI: {provider.name} yanıt vermedi (loglara bak)")
            ok = False

    if not (cfg.telegram_bot_token and cfg.telegram_chat_id):
        lines.append("❌ Telegram: TELEGRAM_BOT_TOKEN veya TELEGRAM_CHAT_ID eksik")
        ok = False
    else:
        notifier = TelegramNotifier(cfg.telegram_bot_token, cfg.telegram_chat_id, enabled=True)
        text = "🤖 Job Hunter bağlantı testi – " + datetime.now().strftime("%d.%m.%Y %H:%M") + "\n" + "\n".join(lines)
        if notifier.send_message(text):
            lines.append("✅ Telegram: test mesajı gönderildi")
        else:
            lines.append("❌ Telegram: mesaj gönderilemedi (token/chat id yanlış olabilir, loglara bak)")
            ok = False
    if not cfg.telegram_enabled:
        lines.append("ℹ️ TELEGRAM_ENABLED=false: günlük ilan bildirimleri henüz kapalı")

    print("\n".join(lines))
    return 0 if ok else 1
