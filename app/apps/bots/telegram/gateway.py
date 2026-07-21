"""
Telethon gateway for Telegram-native message handling.

Provides a Telethon-based message loop that normalizes inbound events
into platform-independent types (MessageEvent, CallbackEvent) and
dispatches them to the registered event handlers.

This gateway can replace the legacy webhook/polling modes for Telegram
bots, providing native MTProto support, large-file downloads, and
lower latency.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Protocol

from apps.bots.common.events import (
    CallbackEvent,
    FileRef,
    InlineQueryEvent,
    MessageEvent,
    MessageRef,
    PlatformCapabilities,
    Sender,
)
from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard

logger = logging.getLogger(__name__)

MessageHandler = Callable[[MessageEvent, object], Awaitable[None]]
CallbackHandler = Callable[[CallbackEvent, object], Awaitable[None]]
InlineQueryHandler = Callable[[InlineQueryEvent, object], Awaitable[None]]
StartedHandler = Callable[[object], Awaitable[None]]


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
        """Send with HTML so ``<b>…</b>`` in i18n strings renders; fall back to plain."""
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
        text: str,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> None:
        buttons = _telethon_buttons(inline_keyboard)
        try:
            await self.client.edit_message(
                chat_id,
                message_id,
                text,
                buttons=buttons,
                parse_mode="html",
            )
        except Exception as exc:
            if "parse" not in str(exc).lower() and "entities" not in str(exc).lower():
                raise
            logger.warning("HTML edit failed; editing as plain text: %s", exc)
            await self.client.edit_message(
                chat_id,
                message_id,
                text,
                buttons=buttons,
            )

    async def send_typing(self, chat_id: int | str) -> None:
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
        buttons = _telethon_buttons(inline_keyboard)
        kwargs: dict[str, object] = {"buttons": buttons}
        if reply_to:
            kwargs["reply_to"] = reply_to
        return await self._send_message_html(chat_id, text_value, **kwargs)

    async def send_upload_action(self, chat_id: int | str) -> None:
        async with self.client.action(chat_id, "document"):
            pass

    async def send_contact_request(self, chat_id: int | str, text_value: str) -> None:
        from apps.bots.common.keyboards import contact_request_keyboard

        await self.send_text(
            chat_id,
            text_value,
            reply_keyboard=contact_request_keyboard(),
        )

    async def delete_message(
        self, chat_id: int | str, message_id: int | str
    ) -> None:
        await self.client.delete_messages(chat_id, [message_id])

    async def download_document(
        self, chat_id: int | str, message_id: int | str
    ) -> bytes | None:
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


class TelethonGateway:
    """
    Telethon-based gateway for a single Telegram bot.

    Usage::
        gateway = TelethonGateway(bot_name, api_id, api_hash, bot_token)
        gateway.on_message(handle_message)
        gateway.on_callback(handle_callback)
        await gateway.start()
    """

    def __init__(
        self,
        bot_name: str,
        api_id: int,
        api_hash: str,
        bot_token: str,
        session_dir: str = "sessions",
    ) -> None:
        """Initialize the gateway with Telegram API credentials."""
        self.bot_name = bot_name
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_path = os.path.join(session_dir, f"gateway_{bot_name}")

        self._message_handler: MessageHandler | None = None
        self._callback_handler: CallbackHandler | None = None
        self._inline_query_handler: InlineQueryHandler | None = None
        self._started_handler: StartedHandler | None = None
        self._background_tasks: set[asyncio.Task] = set()
        self._running = False
        self._client: object | None = None
        self._bot_user_id: int | str | None = None
        self._bot_username: str | None = None
        self.capabilities = PlatformCapabilities(
            supports_typing=True,
            supports_streaming=True,
            supports_inline_query=True,
            supports_callback_buttons=True,
            max_text_chars=4096,
        )

    def on_message(self, handler: MessageHandler) -> None:
        """Register a handler for incoming messages."""
        self._message_handler = handler

    def on_callback(self, handler: CallbackHandler) -> None:
        """Register a handler for callback queries."""
        self._callback_handler = handler

    def on_inline_query(self, handler: InlineQueryHandler) -> None:
        """Register a handler for inline queries."""
        self._inline_query_handler = handler

    def on_started(self, handler: StartedHandler) -> None:
        """Register a handler called when the gateway starts."""
        self._started_handler = handler

    async def start(self) -> None:
        """Start the Telethon client and begin listening for updates."""
        from telethon import TelegramClient, events

        self._client = TelegramClient(self.session_path, self.api_id, self.api_hash)
        logger.info("Starting Telethon client for %s", self.bot_name)
        await asyncio.wait_for(self._client.start(bot_token=self.bot_token), timeout=30)
        logger.info("Telethon client authenticated for %s", self.bot_name)
        me = await self._client.get_me()
        self._bot_user_id = getattr(me, "id", None)
        self._bot_username = getattr(me, "username", None)

        from apps.bots.common.renderer_registry import register_renderer

        register_renderer(
            self.bot_name,
            TelethonEventRenderer(self._client, self.bot_name),
        )

        @self._client.on(events.NewMessage)
        async def handle_new_message(event: events.NewMessage) -> None:
            if not self._message_handler:
                return
            try:
                logger.info(
                    "Telethon message received bot=%s chat_id=%s message_id=%s",
                    self.bot_name,
                    getattr(event, "chat_id", None),
                    getattr(event, "id", None),
                )
                msg = self._normalize_message(event)
                contact = (
                    getattr(event.message, "contact", None) if event.message else None
                )
                if contact and contact.phone_number:
                    from apps.bots.common.handler import (
                        BotRuntimeContext,
                        handle_contact_event,
                    )

                    ctx = BotRuntimeContext(
                        bot_name=self.bot_name,
                        platform="telegram",
                        renderer=TelethonEventRenderer(self._client, self.bot_name),
                        capabilities=self.capabilities,
                        bot_user_id=self._bot_user_id,
                        bot_username=self._bot_username,
                    )
                    await handle_contact_event(
                        msg,
                        ctx,
                        phone_number=contact.phone_number,
                        contact_user_id=contact.user_id
                        or (msg.sender.id if msg.sender else 0),
                    )
                    return
                await self._message_handler(msg, self._client)
            except Exception:
                logger.exception(
                    "Telethon message handler failed for %s", self.bot_name
                )

        @self._client.on(events.CallbackQuery)
        async def handle_callback(event: events.CallbackQuery) -> None:
            if not self._callback_handler:
                return
            try:
                logger.info(
                    "Telethon callback received bot=%s chat_id=%s message_id=%s",
                    self.bot_name,
                    getattr(event, "chat_id", None),
                    getattr(event, "message_id", None),
                )
                cb = self._normalize_callback(event)
                await self._callback_handler(cb, self._client)
            except Exception:
                logger.exception(
                    "Telethon callback handler failed for %s", self.bot_name
                )

        @self._client.on(events.InlineQuery)
        async def handle_inline_query(event: events.InlineQuery) -> None:
            if not self._inline_query_handler:
                return
            try:
                query = InlineQueryEvent(
                    platform="telegram",
                    query_id=str(getattr(event, "id", "")),
                    text=getattr(event, "text", "") or "",
                    sender=Sender(id=getattr(event, "sender_id", 0)),
                    metadata={"bot_name": self.bot_name},
                    raw=event,
                )
                await self._inline_query_handler(query, self._client)
            except Exception:
                logger.exception("Telethon inline handler failed for %s", self.bot_name)

        self._running = True
        logger.info("Telethon gateway started for %s", self.bot_name)
        if self._started_handler:
            task = asyncio.create_task(
                self._started_handler(self._client),
                name=f"telethon-started-{self.bot_name}",
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        await self._client.run_until_disconnected()

    async def stop(self) -> None:
        """Stop the gateway and disconnect the Telethon client."""
        self._running = False
        if self._client:
            await self._client.disconnect()

    def _normalize_message(self, event: object) -> MessageEvent:
        """Normalize a Telethon event into MessageEvent."""
        from telethon import events as telethon_events

        if not isinstance(event, telethon_events.NewMessage) and not hasattr(
            event, "message"
        ):
            return MessageEvent(platform="telegram")

        msg = event.message
        chat = event.chat

        chat_type = "private"
        if chat:
            if hasattr(chat, "broadcast") and chat.broadcast:
                chat_type = "group"
            elif hasattr(chat, "megagroup") and chat.megagroup:
                chat_type = "supergroup"

        file_ref = None
        content_type: str = "text"
        if msg and msg.file:
            media = getattr(msg, "media", None)
            file_name = getattr(msg.file, "name", "") or ""
            mime = getattr(msg.file, "mime_type", "") or ""

            if getattr(msg, "voice", None) is not None:
                content_type = "voice"
                file_name = file_name or "voice.ogg"
            elif getattr(msg, "audio", None) is not None:
                content_type = "audio"
                file_name = file_name or "audio.mp3"
            elif getattr(msg, "video", None) is not None:
                content_type = "video"
                file_name = file_name or "video.mp4"
            elif getattr(msg, "video_note", None) is not None:
                content_type = "video"
                file_name = "video_note.mp4"
            elif getattr(msg, "photo", None) is not None:
                content_type = "photo"
                file_name = file_name or "photo.jpg"
                mime = mime or "image/jpeg"
            elif getattr(msg, "sticker", None) is not None:
                content_type = "sticker"
                file_name = file_name or "sticker.webp"
            elif getattr(media, "document", None) is not None:
                content_type = "document"
            else:
                content_type = "document"

            file_ref = FileRef(
                file_id=str(getattr(msg.file, "id", "")),
                file_name=file_name,
                mime_type=mime,
                size=getattr(msg.file, "size", 0) or 0,
                metadata={
                    "platform": "telegram",
                    "telegram_chat_id": getattr(chat, "id", 0) if chat else 0,
                    "telegram_message_id": getattr(msg, "id", 0),
                    "content_type": content_type,
                },
            )

        sender = None
        if msg and getattr(msg, "sender", None):
            sender_obj = msg.sender
            sender = Sender(
                id=getattr(sender_obj, "id", 0),
                is_bot=bool(getattr(sender_obj, "bot", False)),
                username=getattr(sender_obj, "username", None),
                first_name=getattr(sender_obj, "first_name", None),
                last_name=getattr(sender_obj, "last_name", None),
                metadata={"telegram_user_id": getattr(sender_obj, "id", 0)},
            )

        reply_to = None
        reply_to_msg_id = getattr(msg, "reply_to_msg_id", None) if msg else None
        if reply_to_msg_id:
            reply_to = MessageRef(
                message_id=reply_to_msg_id,
                chat_id=getattr(chat, "id", 0) if chat else 0,
                metadata={
                    "telegram_chat_id": getattr(chat, "id", 0) if chat else 0,
                    "telegram_message_id": reply_to_msg_id,
                    "is_bot_reply": bool(
                        getattr(msg, "reply_to", None)
                        and getattr(
                            getattr(msg, "reply_to", None), "forum_topic", False
                        )
                        is False
                    ),
                },
            )

        chat_id = getattr(chat, "id", 0) if chat else getattr(event, "chat_id", 0)
        message_id = getattr(msg, "id", 0) if msg else getattr(event, "id", 0)
        if sender is None and getattr(event, "sender_id", None):
            sender = Sender(
                id=event.sender_id,
                metadata={"telegram_user_id": event.sender_id},
            )

        return MessageEvent(
            platform="telegram",
            chat_id=chat_id,
            chat_type=chat_type,
            message_id=message_id,
            text=getattr(msg, "text", None) if msg else None,
            content_type=content_type,
            sender=sender,
            file=file_ref,
            reply_to=reply_to,
            metadata={
                "platform": "telegram",
                "chat_id": chat_id,
                "chat_type": chat_type,
                "message_id": message_id,
                "telegram_chat_id": chat_id,
                "telegram_message_id": message_id,
                "bot_name": self.bot_name,
            },
            raw=event,
        )

    def _normalize_callback(self, event: object) -> CallbackEvent:
        """Normalize a Telethon callback event into CallbackEvent."""
        from telethon import events as telethon_events

        if not isinstance(event, telethon_events.CallbackQuery) and not hasattr(
            event, "data"
        ):
            return CallbackEvent(platform="telegram")

        callback_id = getattr(event, "id", "")
        chat_id = getattr(event, "chat_id", 0)
        message_id = getattr(event, "message_id", 0)
        data = getattr(event, "data", b"")
        message_text = None
        if hasattr(event, "message") and event.message:
            message_text = getattr(event.message, "message", None) or getattr(
                event.message, "text", None
            )

        sender = None
        sender_id = getattr(event, "sender_id", None)
        if sender_id:
            sender = Sender(id=sender_id, metadata={"telegram_user_id": sender_id})

        return CallbackEvent(
            platform="telegram",
            callback_id=str(callback_id),
            chat_id=chat_id,
            message_id=message_id,
            data=data.decode() if data else "",
            message_text=message_text,
            sender=sender,
            metadata={
                "platform": "telegram",
                "chat_id": chat_id,
                "message_id": message_id,
                "telegram_callback_id": callback_id,
                "telegram_chat_id": chat_id,
                "telegram_message_id": message_id,
                "bot_name": self.bot_name,
            },
            raw=event,
        )


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


async def download_with_telethon(
    chat_id: int, message_id: int, bot_token: str, session_name: str = "temp_download"
) -> bytes | None:
    """
    Download a file from a Telegram message using Telethon.

    Useful for large files that exceed the Bot API limit (20MB).
    """
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if not api_id or not api_hash:
        raise RuntimeError("Missing TELEGRAM_API_ID/TELEGRAM_API_HASH")

    from telethon import TelegramClient

    async with TelegramClient(f"sessions/{session_name}", api_id, api_hash) as client:
        await client.start(bot_token=bot_token)
        entity = await client.get_input_entity(chat_id)
        msg = await client.get_messages(entity, ids=message_id)
        if not msg or not msg.media:
            return None
        data = await client.download_media(msg.media, bytes)
        return data
