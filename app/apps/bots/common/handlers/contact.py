"""Contact / onboarding message handling."""

from __future__ import annotations

import logging

from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext
from apps.bots.common.handlers.menu import resolve_locale, send_main_menu
from apps.bots.common.onboarding import (
    contact_mismatch_message,
    contact_user_id_matches,
    get_or_create_bot_user_from_contact,
)
from utils.i18n import text

logger = logging.getLogger(__name__)


async def handle_contact_event(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    phone_number: str,
    contact_user_id: int | str,
) -> None:
    """Complete onboarding after the user shares a verified contact."""
    locale = await resolve_locale(event)
    if not contact_user_id_matches(event, contact_user_id):
        await ctx.renderer.send_text(
            event.chat_id,
            contact_mismatch_message(locale),
            reply_to=event.message_id,
        )
        return

    try:
        await get_or_create_bot_user_from_contact(event, phone_number)
    except Exception:
        logger.exception("Failed to complete onboarding for %s", event.chat_id)
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.onboarding_error", locale=locale),
            reply_to=event.message_id,
        )
        return

    await send_main_menu(
        ctx,
        event.chat_id,
        locale,
        reply_to=event.message_id,
        message_key="messages.onboarding_success",
    )
