"""Shared handler types and small helpers (avoids circular imports)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from apps.bots.common.auth_gate import (
    VerifiedUserStatus,
    platform_user_id,
    resolve_verified_user,
)
from apps.bots.common.events import (
    CallbackEvent,
    MessageEvent,
    PlatformCapabilities,
)
from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard
from utils.i18n import text


class EventRenderer(Protocol):
    """Render bot messages and UI on a messenger platform."""

    async def send_typing(self, chat_id: int | str) -> None: ...

    async def send_text(
        self,
        chat_id: int | str,
        text_value: str,
        reply_to: int | str | None = None,
        reply_keyboard: ReplyKeyboard | None = None,
    ) -> object | None: ...

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> None: ...

    async def answer_callback(
        self,
        callback_id: int | str,
        text_value: str = "",
        raw_event: object | None = None,
    ) -> None: ...

    async def send_contact_request(
        self, chat_id: int | str, text_value: str
    ) -> None: ...

    async def download_attached_file(
        self, event: MessageEvent
    ) -> tuple[bytes, str] | None: ...

    async def send_inline_text(
        self,
        chat_id: int | str,
        text_value: str,
        inline_keyboard: InlineKeyboard,
        reply_to: int | str | None = None,
    ) -> object | None: ...

    async def send_upload_action(self, chat_id: int | str) -> None: ...

    async def answer_inline_query(
        self,
        query_id: str,
        text_value: str,
        *,
        raw_event: object | None = None,
    ) -> None: ...

    async def send_document(
        self,
        chat_id: int | str,
        file_data: bytes,
        file_name: str,
        caption: str | None = None,
        reply_to: int | str | None = None,
        inline_keyboard: InlineKeyboard | None = None,
    ) -> object | None: ...

    async def download_document(
        self, chat_id: int | str, message_id: int | str
    ) -> bytes | None: ...


@dataclass(frozen=True)
class BotRuntimeContext:
    """Runtime dependencies passed from platform adapters to handlers."""

    bot_name: str
    platform: str
    renderer: EventRenderer
    capabilities: PlatformCapabilities
    bot_user_id: int | str | None = None
    bot_username: str | None = None


def event_user_id(event: MessageEvent | CallbackEvent) -> str | None:
    return platform_user_id(event)


def is_command(text_value: str, command: str) -> bool:
    return text_value == command or text_value.startswith(f"{command} ")


def strip_bot_mention(text_value: str, bot_username: str | None) -> str:
    if not bot_username:
        return text_value
    pattern = re.compile(rf"@?{re.escape(bot_username)}\b", re.IGNORECASE)
    return pattern.sub("", text_value).strip()


def bot_return_url(ctx: BotRuntimeContext) -> str:
    if ctx.platform == "bale":
        return f"https://ble.ir/{ctx.bot_username or ctx.bot_name}"
    return f"https://t.me/{ctx.bot_username or ctx.bot_name}"


def sent_message_id(message: object | None, fallback: int | str) -> int | str:
    """Extract a platform message identifier from a renderer response."""
    return (
        getattr(message, "id", None) or getattr(message, "message_id", None) or fallback
    )


async def prompt_contact(
    ctx: BotRuntimeContext,
    event: MessageEvent | CallbackEvent,
    locale: str,
) -> None:
    await ctx.renderer.send_contact_request(
        event.chat_id,
        text("messages.start_contact", locale=locale),
    )


async def require_verified_user(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> tuple[str, object] | None:
    status, verified = await resolve_verified_user(event)
    if status == VerifiedUserStatus.no_platform_user:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.no_user", locale=locale)
        )
        return None
    if status == VerifiedUserStatus.needs_contact or verified is None:
        await prompt_contact(ctx, event, locale)
        return None
    return verified.usso_uid, verified.bot_user


async def require_verified_callback(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> tuple[str, object] | None:
    status, verified = await resolve_verified_user(event)
    if status == VerifiedUserStatus.no_platform_user:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.no_user", locale=locale)
        )
        return None
    if status == VerifiedUserStatus.needs_contact or verified is None:
        await prompt_contact(ctx, event, locale)
        return None
    return verified.usso_uid, verified.bot_user
