"""Telegram bot identity/config for the Telethon gateway."""

from __future__ import annotations

import logging
import os

import singleton

logger = logging.getLogger(__name__)


def raw_telegram_token(token: str | None = None) -> str:
    """Return the configured Telegram token from args or environment."""
    return (token or os.getenv("TELEGRAM_TOKEN", "") or "").strip()


class TelegramBot(metaclass=singleton.Singleton):
    """Lightweight Telegram config — transport is Telethon, not telebot."""

    bot_type = "telegram"

    def __init__(self, token: str | None = None) -> None:
        """Capture token/name at construction (after dotenv has loaded)."""
        self.token = raw_telegram_token(token)
        self.me = (os.getenv("TELEGRAM_BOT_NAME") or "mirzabenevisbot").strip()
        self.webhook_route = self.me

    @classmethod
    def is_configured(cls) -> bool:
        """Return whether a Telegram bot token is available."""
        return bool(raw_telegram_token())

    @property
    def link(self) -> str:
        """Bot's public deep-link URL."""
        return f"https://t.me/{self.me}"

    def __str__(self) -> str:
        """Return the bot's public deep-link URL."""
        return self.link
