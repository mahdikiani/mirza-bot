"""Telegram bot identity/config for the Telethon gateway."""

from __future__ import annotations

import logging
import os

import singleton

logger = logging.getLogger(__name__)


class TelegramBot(metaclass=singleton.Singleton):
    """Lightweight Telegram config — transport is Telethon, not telebot."""

    token = os.getenv("TELEGRAM_TOKEN")
    me = os.getenv("TELEGRAM_BOT_NAME", "uln_ai_bot")
    webhook_route = me
    bot_type = "telegram"

    @classmethod
    def is_configured(cls) -> bool:
        """Return whether a Telegram bot token is available."""
        return bool((cls.token or "").strip())

    @property
    def link(self) -> str:
        """Bot's public deep-link URL."""
        return f"https://t.me/{self.me}"

    def __str__(self) -> str:
        """Return the bot's public deep-link URL."""
        return self.link
