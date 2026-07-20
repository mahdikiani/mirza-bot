"""Bale bot singleton using telegram-bale-bot / AsyncTeleBot."""

from __future__ import annotations

import asyncio
import logging
import os

import singleton
from telebot.async_telebot import AsyncTeleBot
from telebot.asyncio_helper import ApiTelegramException

from utils.texttools import split_text

logger = logging.getLogger(__name__)


def raw_bale_token(token: str | None = None) -> str:
    """Return the configured Bale token from args or environment."""
    return (token or os.getenv("BALE_BOT_TOKEN", "") or "").strip()


class BaleToken(str):
    """Route variable-length Bale tokens through telegram-bale-bot."""

    def __len__(self) -> int:
        """Return the token length expected by telegram-bale-bot routing."""
        return 51


class BaleBot(AsyncTeleBot, metaclass=singleton.Singleton):
    """Singleton Bale bot (telebot transport — required for Bale)."""

    last_update_id: int | None = None
    bot_user_id: int | None = None
    _me_resolved = False
    _client_ready = False

    @classmethod
    def is_configured(cls) -> bool:
        """Return whether a real Bale token is available."""
        return bool(raw_bale_token())

    def __init__(self, token: str | None = None, **kwargs: object) -> None:
        """Initialize the Bale bot client when a token is configured."""
        raw = raw_bale_token(token)
        self.lock = asyncio.Lock()
        self.me = (os.getenv("BALE_BOT_NAME") or "mirza_bale_bot").strip()
        self.webhook_route = self.me
        if not raw:
            self.token = ""
            self._client_ready = False
            return

        self.token = raw
        AsyncTeleBot.__init__(
            self,
            BaleToken(raw),
            parse_mode="HTML",
            **kwargs,
        )
        self._client_ready = True

    @property
    def bot_type(self) -> str:
        """Platform identifier for this bot."""
        return "bale"

    @property
    def needs_polling(self) -> bool:
        """Bale uses polling as a reliability fallback."""
        return True

    @property
    def link(self) -> str:
        """Bot's public deep-link URL."""
        return f"https://ble.ir/{self.me}"

    def __str__(self) -> str:
        """Return the bot's public deep-link URL."""
        return self.link

    async def resolve_me(self) -> None:
        """Fetch and cache the bot username from the Bale API."""
        if self._me_resolved or not self._client_ready:
            return
        try:
            bot_info = await self.get_me()
            if bot_info and bot_info.username:
                self.me = bot_info.username
                self.webhook_route = bot_info.username
                self.bot_user_id = getattr(bot_info, "id", None)
                self._me_resolved = True
        except Exception:
            logger.exception("Failed to resolve Bale bot name via getMe")

    async def edit_message_text(
        self, text: str, *args: object, **kwargs: object
    ) -> None:
        """Edit a message with safe error handling for common API exceptions."""
        try:
            await super().edit_message_text(text=text[:4096], **kwargs)
        except ApiTelegramException as e:
            err = str(e)
            if (
                "message is not modified:" in err
                or "message text is empty" in err
                or "MESSAGE_TOO_LONG" in err
            ):
                logging.warning("edit_message_text error: %s", e)
            elif "can't parse entities" in err:
                kwargs["parse_mode"] = ""
                await self.edit_message_text(text, *args, **kwargs)
            else:
                raise

    async def send_message(
        self, chat_id: int | str, text: str, *args: object, **kwargs: object
    ) -> object | None:
        """Send a message, splitting long text and handling parse errors."""
        sent = None
        try:
            messages = split_text(text)
            if not messages:
                return None
            for msg in messages:
                sent = await super().send_message(chat_id, msg, *args, **kwargs)
        except ApiTelegramException as e:
            if "MESSAGE_TOO_LONG" in str(e):
                logging.warning("send_message error: %s", e)
            elif "can't parse entities" in str(e):
                kwargs["parse_mode"] = ""
                await self.send_message(chat_id, text, *args, **kwargs)
                logging.warning("send_message error: %s", e)
            else:
                logging.exception("send_message error")
                raise
        return sent
