"""Contact / onboarding message handling."""

from __future__ import annotations

import logging

from apps.bots.common import team_invites
from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext, event_user_id
from apps.bots.common.handlers.menu import resolve_locale, send_main_menu
from apps.bots.common.handlers.messages import _accept_invite_and_notify
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
        bot_user = await get_or_create_bot_user_from_contact(event, phone_number)
    except Exception:
        logger.exception("Failed to complete onboarding for %s", event.chat_id)
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.onboarding_error", locale=locale),
            reply_to=event.message_id,
        )
        return

    messenger_id = event_user_id(event)
    invite_token = (
        await team_invites.pop_pending_invite(event.platform, messenger_id)
        if messenger_id
        else None
    )
    if invite_token and bot_user.usso_user_id:
        await _accept_invite_and_notify(
            event, ctx, locale, invite_token, bot_user.usso_user_id, bot_user
        )

    await send_main_menu(
        ctx,
        event.chat_id,
        locale,
        reply_to=event.message_id,
        message_key="messages.onboarding_success",
    )
