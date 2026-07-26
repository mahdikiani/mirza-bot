"""Telethon outbound renderer for normalized bot handlers."""


from __future__ import annotations

import logging
from typing import Protocol

from apps.bots.common.events import MessageEvent
from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard

logger = logging.getLogger(__name__)


def _telethon_buttons(keyboard: InlineKeyboard | ReplyKeyboard | None) -> object | None:
    if keyboard is None:
        return None
    from telethon import Button

    if isinstance(keyboard, ReplyKeyboard):
        rows = []
        for row in keyboard.rows:
            buttons = []
            for item in row:
                if item.request_contact:
                    buttons.append(Button.request_phone(item.label, resize=True))
                else:
                    buttons.append(
                        Button.text(
                            item.label, resize=True, single_use=keyboard.one_time
                        )
                    )
            rows.append(buttons)
        return rows

    rows = []
    for row in keyboard.rows:
        buttons = []
        for item in row:
            if item.url:
                buttons.append(Button.url(item.label, item.url))
            else:
                buttons.append(Button.inline(item.label, item.callback_data))
        rows.append(buttons)
    return rows


class TelethonClient(Protocol):
    """Protocol for a basic Telethon client interface."""

    async def __call__(self, request: object) -> object:
        """Invoke a Telegram MTProto request."""
        ...

    def action(self, entity: int | str, action: str) -> object:
        """Return a Telethon chat action context manager."""
        ...

    async def send_message(
        self,
        entity: int | str,
        message: str,
        **kwargs: object,
    ) -> object:
        """Send a message to a Telegram entity."""
        ...

    async def disconnect(self) -> None:
        """Disconnect the Telethon client."""
        ...

    async def get_me(self) -> object:
        """Return the logged-in bot account."""
        ...

    async def download_media(self, message: object, file: object) -> bytes | None:
        """Download media from a message."""
        ...

    async def edit_message(
        self,
        entity: int | str,
        message: int | str,
        text: str,
        **kwargs: object,
    ) -> object:
        """Edit an existing message."""
        ...

    async def send_file(
        self,
        entity: int | str,
        file: object,
        **kwargs: object,
    ) -> object:
        """Send a file to a Telegram entity."""
        ...

    async def get_messages(
        self,
        entity: int | str,
        ids: int | str,
    ) -> object | None:
        """Get a message by ID."""
        ...


class TelethonEventRenderer:
    """Renderer adapter for normalized handlers running on Telethon."""

    def __init__(self, client: TelethonClient, bot_name: str = "") -> None:
        """Bind the renderer to a Telethon client."""
        self.client = client
        self.bot_name = bot_name

    async def _send_message_html(
        self,
        chat_id: int | str,
        text_value: str,
        **kwargs: object,
    ) -> object | None:
        """
        Send with HTML so ``<b>…</b>`` in i18n strings renders.

        Allows for sending HTML tags in the message, and falls back to plain text if the
        HTML tags are not supported.
        """
        try:
            return await self.client.send_message(
                chat_id, text_value, parse_mode="html", **kwargs
            )
        except Exception as exc:
            if "parse" not in str(exc).lower() and "entities" not in str(exc).lower():
                raise
            logger.warning("HTML parse failed; sending plain text: %s", exc)
            kwargs.pop("parse_mode", None)
            return await self.client.send_message(chat_id, text_value, **kwargs)

    async def send_text(
        self,
        chat_id: int | str,
        text_value: str,
        reply_to: int | str | None = None,
        reply_keyboard: ReplyKeyboard | None = None,
    ) -> object | None:
        """Send a plain text message."""
        kwargs: dict[str, object] = {}
        if reply_to:
            kwargs["reply_to"] = reply_to
        buttons = _telethon_buttons(reply_keyboard)
        if buttons is not None:
            kwargs["buttons"] = buttons
        return await self._send_message_html(chat_id, text_value, **kwargs)

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> None:
        """Edit an existing message text and optional keyboard."""
        buttons = _telethon_buttons(inline_keyboard)
        try:
            kwargs: dict = {"buttons": buttons}
            if text is not None:
                kwargs["parse_mode"] = "html"
            await self.client.edit_message(
                chat_id,
                message_id,
                text,
                **kwargs,
            )
        except Exception as exc:
            if "parse" not in str(exc).lower() and "entities" not in str(exc).lower():
                raise
            logger.warning("HTML edit failed; editing as plain text: %s", exc)
            if text is not None:
                kwargs.pop("parse_mode", None)
                await self.client.edit_message(
                    chat_id,
                    message_id,
                    text,
                    buttons=buttons,
                )

    async def send_typing(self, chat_id: int | str) -> None:
        """Show a typing indicator in the chat."""
        from telethon import functions, types

        await self.client(
            functions.messages.SetTypingRequest(
                peer=chat_id,
                action=types.SendMessageTypingAction(),
            )
        )

    async def send_inline_text(
        self,
        chat_id: int | str,
        text_value: str,
        inline_keyboard: InlineKeyboard,
        reply_to: int | str | None = None,
    ) -> object | None:
        """Send text with an inline keyboard."""
        buttons = _telethon_buttons(inline_keyboard)
        kwargs: dict[str, object] = {"buttons": buttons}
        if reply_to:
            kwargs["reply_to"] = reply_to
        return await self._send_message_html(chat_id, text_value, **kwargs)

    async def send_upload_action(self, chat_id: int | str) -> None:
        """Show an upload-document chat action."""
        async with self.client.action(chat_id, "document"):
            pass

    async def send_contact_request(self, chat_id: int | str, text_value: str) -> None:
        """Ask the user to share a contact."""
        from apps.bots.common.keyboards import contact_request_keyboard

        await self.send_text(
            chat_id,
            text_value,
            reply_keyboard=contact_request_keyboard(),
        )

    async def delete_message(self, chat_id: int | str, message_id: int | str) -> None:
        """Delete a chat message."""
        await self.client.delete_messages(chat_id, [message_id])

    async def download_document(
        self, chat_id: int | str, message_id: int | str
    ) -> bytes | None:
        """Download document bytes for a message id."""
        msg = await self.client.get_messages(chat_id, ids=message_id)
        if not msg:
            return None
        if not msg.media:
            return msg.message.encode("utf-8") if msg.message else None
        data = await self.client.download_media(msg, bytes)
        return bytes(data) if data else None

    async def send_document(
        self,
        chat_id: int | str,
        file_data: bytes,
        file_name: str,
        caption: str | None = None,
        reply_to: int | str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> object | None:
        """Send a document file to the chat."""
        from io import BytesIO

        from telethon.tl.types import DocumentAttributeFilename

        buttons = _telethon_buttons(inline_keyboard)
        return await self.client.send_file(
            chat_id,
            file=BytesIO(file_data),
            attributes=[DocumentAttributeFilename(file_name)],
            caption=caption or "",
            parse_mode="html" if caption else None,
            reply_to=reply_to,
            buttons=buttons,
        )

    async def answer_callback(
        self,
        callback_id: int | str,
        text_value: str = "",
        raw_event: object | None = None,
    ) -> None:
        """Answer a callback query."""
        event = raw_event
        if event is not None and hasattr(event, "answer"):
            await event.answer(text_value or None)
            return
        logger.debug("Callback answer requested id=%s text=%s", callback_id, text_value)

    async def answer_inline_query(
        self,
        query_id: str,
        text_value: str,
        *,
        raw_event: object | None = None,
    ) -> None:
        """Answer an inline query."""
        from telethon import Button

        if raw_event is None or not hasattr(raw_event, "answer"):
            return
        results = [
            await raw_event.builder.article(
                title="AI",
                text=text_value[:4096],
                buttons=Button.url("Open", f"https://t.me/{self.bot_name}"),
            )
        ]
        await raw_event.answer(results, cache_time=10)

    async def download_attached_file(
        self, event: MessageEvent
    ) -> tuple[bytes, str] | None:
        """Download the file attached to an inbound event."""
        raw = event.raw
        if raw is None:
            return None
        msg = getattr(raw, "message", None)
        if msg is None or not getattr(msg, "media", None):
            return None
        data = await self.client.download_media(msg, bytes)
        if not data:
            return None
        if event.file and event.file.file_name:
            file_name = event.file.file_name
        else:
            ct = (
                (event.file.metadata or {}).get("content_type", "")
                if event.file
                else ""
            )
            file_name = f"file.{_guess_ext(ct)}" if ct else "file.bin"
        return data, file_name


_CONTENT_EXT: dict[str, str] = {
    "voice": "ogg",
    "audio": "mp3",
    "video": "mp4",
    "photo": "jpg",
    "sticker": "webp",
    "document": "bin",
    "animation": "gif",
}


def _guess_ext(content_type: str) -> str:
    return _CONTENT_EXT.get(content_type, "bin")
