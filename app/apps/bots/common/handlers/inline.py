"""Telegram inline-query handling."""

from __future__ import annotations

import logging

from apps.ai.clients import CompletionClient, InsufficientCreditsError
from apps.bots.common.auth_gate import VerifiedUserStatus, resolve_verified_user
from apps.bots.common.events import InlineQueryEvent
from apps.bots.common.handler_context import BotRuntimeContext
from apps.bots.common.settings import get_user_locale
from utils.i18n import text

logger = logging.getLogger(__name__)


async def handle_inline_query_event(
    event: InlineQueryEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Answer inline queries with a stateless completion (Telegram only)."""
    if not ctx.capabilities.supports_inline_query:
        return

    messenger_id = str(event.sender.id) if event.sender else ""
    locale = await get_user_locale(messenger_id) if messenger_id else "fa"

    status, verified = await resolve_verified_user(event)
    if status != VerifiedUserStatus.ok or verified is None:
        await ctx.renderer.answer_inline_query(
            event.query_id,
            text("messages.inline_need_auth", locale=locale),
            raw_event=event.raw,
        )
        return

    if not event.text.strip():
        response = text("messages.inline_empty", locale=locale)
    else:
        messages = [{"role": "user", "content": event.text}]
        try:
            response = await CompletionClient.complete(
                messages,
                user_id=verified.usso_uid,
                workspace_id=(
                    verified.bot_user.telegram_workspace_id or verified.usso_uid
                ),
                audit_source="telegram_inline",
            )
        except InsufficientCreditsError:
            response = text("messages.insufficient_credits", locale=locale)
        except Exception:
            logger.exception("Inline query completion failed")
            response = text("messages.ai_error", locale=locale)

    await ctx.renderer.answer_inline_query(
        event.query_id,
        response,
        raw_event=event.raw,
    )
