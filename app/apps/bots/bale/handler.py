"""Bale webhook dispatch into shared bot handlers."""

from __future__ import annotations

import logging
from typing import Any

from apps.bots.bale.normalizer import (
    normalize_bale_callback,
    normalize_bale_contact,
    normalize_bale_message,
)
from apps.bots.bale.renderer import BaleEventRenderer
from apps.bots.common.events import PlatformCapabilities
from apps.bots.common.handler import (
    BotRuntimeContext,
    handle_callback_event,
    handle_contact_event,
    handle_message_event,
)
from apps.bots.common.renderer_registry import register_renderer

logger = logging.getLogger(__name__)


def _get_bot(bot_name: str) -> object:
    from apps.bots.runtime.handlers import get_bot

    return get_bot(bot_name)


async def handle_bale_update(payload: dict[str, Any], bot_name: str) -> None:
    """Dispatch a Bale webhook update through shared orchestration."""
    bot = _get_bot(bot_name)
    renderer = BaleEventRenderer(bot)
    register_renderer(bot_name, renderer)

    ctx = BotRuntimeContext(
        bot_name=bot_name,
        platform="bale",
        renderer=renderer,
        capabilities=PlatformCapabilities(
            supports_typing=True,
            supports_callback_buttons=True,
            max_text_chars=4096,
        ),
        bot_username=getattr(bot, "me", bot_name),
    )

    if callback := payload.get("callback_query"):
        event = normalize_bale_callback(callback, bot_name)
        await handle_callback_event(event, ctx)
        return

    message = payload.get("message")
    if not message:
        return

    if message.get("contact"):
        event, phone, contact_user_id = normalize_bale_contact(message, bot_name)
        await handle_contact_event(event, ctx, phone, contact_user_id)
        return

    event = normalize_bale_message(message, bot_name)
    await handle_message_event(event, ctx)
