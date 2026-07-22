"""Bale renderer backed by telegram-bale-bot."""

from __future__ import annotations

import logging

import httpx

from apps.bots.bale.bot import BaleBot
from apps.bots.bale.markup import to_inline_markup, to_reply_markup
from apps.bots.common.events import MessageEvent
from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard

logger = logging.getLogger(__name__)

# telebot's own download_file() uses an aiohttp session with the library
# default of ClientTimeout(total=300), which is too short for Bale's file
# server on larger (multi-MB) attachments — observed a real 8.5MB audio
# file both time out at exactly 300s through telebot and complete in ~53s
# via a plain longer-timeout request. Downloading directly here (Bale's
# getFile is a no-op that just echoes file_id back as file_path, so no
# separate resolution call is needed) works around that fixed timeout.
BALE_FILE_DOWNLOAD_TIMEOUT = 240.0


class BaleEventRenderer:
    """Send and edit Bale messages through AsyncTeleBot."""

    def __init__(self, bot: BaleBot) -> None:
        """Bind the renderer to a running Bale bot client."""
        self.bot = bot

    async def send_typing(self, chat_id: int | str) -> None:
        try:
            await self.bot.send_chat_action(chat_id, "typing")
        except Exception:
            logger.debug("Bale typing action failed for chat_id=%s", chat_id)

    async def send_text(
        self,
        chat_id: int | str,
        text_value: str,
        reply_to: int | str | None = None,
        reply_keyboard: ReplyKeyboard | None = None,
    ) -> object | None:
        kwargs: dict[str, object] = {}
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to
        markup = to_reply_markup(reply_keyboard)
        if markup is not None:
            kwargs["reply_markup"] = markup
        return await self.bot.send_message(chat_id, text_value, **kwargs)

    async def send_inline_text(
        self,
        chat_id: int | str,
        text_value: str,
        inline_keyboard: InlineKeyboard,
        reply_to: int | str | None = None,
    ) -> object | None:
        kwargs: dict[str, object] = {
            "reply_markup": to_inline_markup(inline_keyboard),
        }
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to
        return await self.bot.send_message(chat_id, text_value, **kwargs)

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> None:
        try:
            if text is None:
                msg = await self.bot.get_message(chat_id, message_id)
                text = getattr(msg, "text", None) or getattr(msg, "caption", "") or ""
            await self.bot.edit_message_text(
                text,
                chat_id,
                message_id,
                reply_markup=to_inline_markup(inline_keyboard),
            )
        except Exception:
            logger.warning(
                "edit_message failed, sending new message for chat=%s", chat_id
            )
            from apps.bots.bale.markup import to_inline_markup as to_markup

            kwargs: dict[str, object] = {}
            markup = to_markup(inline_keyboard)
            if markup is not None:
                kwargs["reply_markup"] = markup
            await self.bot.send_message(chat_id, text[:4096], **kwargs)

    async def answer_callback(
        self,
        callback_id: int | str,
        text_value: str = "",
        raw_event: object | None = None,
    ) -> None:
        await self.bot.answer_callback_query(
            callback_id,
            text=text_value or None,
            show_alert=False,
        )

    async def send_contact_request(self, chat_id: int | str, text_value: str) -> None:
        from apps.bots.common.keyboards import contact_request_keyboard

        await self.send_text(
            chat_id,
            text_value,
            reply_keyboard=contact_request_keyboard(),
        )

    async def _download_bale_file(self, file_id: str) -> bytes | None:
        """
        Download a file by ID directly against Bale's file server,
        bypassing telebot's fixed 300s aiohttp timeout (see module docstring
        comment above BALE_FILE_DOWNLOAD_TIMEOUT)."""
        url = f"https://tapi.bale.ai/file/bot{self.bot.token}/{file_id}"
        async with httpx.AsyncClient(timeout=BALE_FILE_DOWNLOAD_TIMEOUT) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content

    async def download_attached_file(
        self, event: MessageEvent
    ) -> tuple[bytes, str] | None:
        if not event.file or not event.file.file_id:
            return None
        data = await self._download_bale_file(event.file.file_id)
        if data is None:
            return None
        name = event.file.file_name or "file.bin"
        return data, name

    async def delete_message(
        self, chat_id: int | str, message_id: int | str
    ) -> None:
        try:
            await self.bot.delete_message(chat_id, message_id)
        except Exception:
            logger.debug("Bale delete_message failed for chat_id=%s msg_id=%s", chat_id, message_id)

    async def download_document(
        self, chat_id: int | str, message_id: int | str
    ) -> bytes | None:
        try:
            msg = await self.bot.get_message(chat_id, message_id)
            if not msg:
                return None
            document = getattr(msg, "document", None) or getattr(msg, "audio", None)
            if not document:
                text = getattr(msg, "text", None) or getattr(msg, "caption", None)
                return text.encode("utf-8") if text else None
            file_id = getattr(document, "file_id", None)
            if not file_id:
                return None
            return await self._download_bale_file(file_id)
        except Exception:
            logger.exception(
                "Failed to download document from chat_id=%s msg_id=%s",
                chat_id,
                message_id,
            )
            return None

    async def send_document(
        self,
        chat_id: int | str,
        file_data: bytes,
        file_name: str,
        caption: str | None = None,
        reply_to: int | str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> object | None:
        from io import BytesIO

        from apps.bots.bale.markup import to_inline_markup

        kwargs: dict[str, object] = {"caption": caption or ""}
        if reply_to:
            kwargs["reply_to_message_id"] = reply_to
        markup = to_inline_markup(inline_keyboard)
        if markup is not None:
            kwargs["reply_markup"] = markup
        return await self.bot.send_document(
            chat_id,
            BytesIO(file_data),
            visible_file_name=file_name,
            **kwargs,
        )

    async def send_upload_action(self, chat_id: int | str) -> None:
        try:
            await self.bot.send_chat_action(chat_id, "upload_document")
        except Exception:
            logger.debug("Bale upload action failed for chat_id=%s", chat_id)

    async def answer_inline_query(
        self,
        query_id: str,
        text_value: str,
        *,
        raw_event: object | None = None,
    ) -> None:
        logger.debug("Bale inline query not supported query_id=%s", query_id)
