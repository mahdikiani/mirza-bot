"""Registry of active platform renderers for webhook delivery."""

from __future__ import annotations

from typing import Protocol

from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard


class BotRenderer(Protocol):
    """Minimal renderer used by AI webhook delivery."""

    async def send_text(
        self,
        chat_id: int | str,
        text_value: str,
        reply_to: int | str | None = None,
        reply_keyboard: ReplyKeyboard | None = None,
    ) -> object | None:
        """Send a text message."""
        ...

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> None:
        """Edit an existing message."""
        ...

    async def send_typing(self, chat_id: int | str) -> None:
        """Show typing indicator."""
        ...

    async def send_document(
        self,
        chat_id: int | str,
        file_data: bytes,
        file_name: str,
        caption: str | None = None,
        reply_to: int | str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> object | None:
        """Send a document attachment."""
        ...

    async def delete_message(self, chat_id: int | str, message_id: int | str) -> None:
        """Delete a chat message."""
        ...

    async def download_document(
        self, chat_id: int | str, message_id: int | str
    ) -> bytes | None:
        """Download a document by message id."""
        ...


_renderers: dict[str, BotRenderer] = {}


def register_renderer(bot_name: str, renderer: BotRenderer) -> None:
    """Register a live renderer for a bot username."""
    _renderers[bot_name] = renderer


def get_renderer(bot_name: str) -> BotRenderer | None:
    """Return the renderer for a bot, if connected."""
    return _renderers.get(bot_name)
