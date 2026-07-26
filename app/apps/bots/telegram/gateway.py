"""
Telethon gateway for Telegram-native message handling.

Provides a Telethon-based message loop that normalizes inbound events
into platform-independent types (MessageEvent, CallbackEvent) and
dispatches them to the registered event handlers.
"""


from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from apps.bots.common.events import (
    CallbackEvent,
    InlineQueryEvent,
    MessageEvent,
    PlatformCapabilities,
    Sender,
)
from apps.bots.telegram.normalizer import (
    enrich_reply_metadata,
    normalize_telethon_callback,
    normalize_telethon_message,
)
from apps.bots.telegram.renderer import (
    TelethonClient,
    TelethonEventRenderer,
    _telethon_buttons,
)

logger = logging.getLogger(__name__)

MessageHandler = Callable[[MessageEvent, object], Awaitable[None]]
CallbackHandler = Callable[[CallbackEvent, object], Awaitable[None]]
InlineQueryHandler = Callable[[InlineQueryEvent, object], Awaitable[None]]
StartedHandler = Callable[[object], Awaitable[None]]

__all__ = [
    "TelethonClient",
    "TelethonEventRenderer",
    "TelethonGateway",
    "_telethon_buttons",
    "download_with_telethon",
]


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

    def _runtime_context(self) -> object:
        """Build shared runtime context for Telegram handlers."""
        from apps.bots.common.handler import BotRuntimeContext

        return BotRuntimeContext(
            bot_name=self.bot_name,
            platform="telegram",
            renderer=TelethonEventRenderer(self._client, self.bot_name),
            capabilities=self.capabilities,
            bot_user_id=self._bot_user_id,
            bot_username=self._bot_username,
        )

    async def _dispatch_new_message(self, event: object) -> None:
        """Normalize and route a NewMessage event."""
        if not self._message_handler:
            return
        logger.info(
            "Telethon message received bot=%s chat_id=%s message_id=%s",
            self.bot_name,
            getattr(event, "chat_id", None),
            getattr(event, "id", None),
        )
        msg = self._normalize_message(event)
        await enrich_reply_metadata(event, msg, self._bot_user_id)
        contact = getattr(event.message, "contact", None) if event.message else None
        if contact and contact.phone_number:
            from apps.bots.common.handler import handle_contact_event

            await handle_contact_event(
                msg,
                self._runtime_context(),
                phone_number=contact.phone_number,
                contact_user_id=contact.user_id
                or (msg.sender.id if msg.sender else 0),
            )
            return
        await self._message_handler(msg, self._client)

    async def _dispatch_callback(self, event: object) -> None:
        """Normalize and route a CallbackQuery event."""
        if not self._callback_handler:
            return
        logger.info(
            "Telethon callback received bot=%s chat_id=%s message_id=%s",
            self.bot_name,
            getattr(event, "chat_id", None),
            getattr(event, "message_id", None),
        )
        cb = self._normalize_callback(event)
        await self._callback_handler(cb, self._client)

    async def _dispatch_inline_query(self, event: object) -> None:
        """Normalize and route an InlineQuery event."""
        if not self._inline_query_handler:
            return
        query = InlineQueryEvent(
            platform="telegram",
            query_id=str(getattr(event, "id", "")),
            text=getattr(event, "text", "") or "",
            sender=Sender(id=getattr(event, "sender_id", 0)),
            metadata={"bot_name": self.bot_name},
            raw=event,
        )
        await self._inline_query_handler(query, self._client)

    def _register_handlers(self, events: object) -> None:
        """Attach Telethon event handlers to the connected client."""

        @self._client.on(events.NewMessage)
        async def handle_new_message(event: object) -> None:
            try:
                await self._dispatch_new_message(event)
            except Exception:
                logger.exception(
                    "Telethon message handler failed for %s", self.bot_name
                )

        @self._client.on(events.CallbackQuery)
        async def handle_callback(event: object) -> None:
            try:
                await self._dispatch_callback(event)
            except Exception:
                logger.exception(
                    "Telethon callback handler failed for %s", self.bot_name
                )

        @self._client.on(events.InlineQuery)
        async def handle_inline_query(event: object) -> None:
            try:
                await self._dispatch_inline_query(event)
            except Exception:
                logger.exception("Telethon inline handler failed for %s", self.bot_name)

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
        self._register_handlers(events)

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
        return normalize_telethon_message(event, self.bot_name)

    def _normalize_callback(self, event: object) -> CallbackEvent:
        """Normalize a Telethon callback event into CallbackEvent."""
        return normalize_telethon_callback(event, self.bot_name)


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
