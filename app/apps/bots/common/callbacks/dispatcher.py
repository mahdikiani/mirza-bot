"""Dispatch inline keyboard callbacks to focused handlers."""

from __future__ import annotations

from apps.bots.common import settings
from apps.bots.common.callbacks.billing import handle_billing_callback
from apps.bots.common.callbacks.chat import handle_action_callback, handle_chat_callback
from apps.bots.common.callbacks.convert import handle_convert_callback
from apps.bots.common.callbacks.prefs import handle_settings_callback
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import BotRuntimeContext, event_user_id
from utils.i18n import text


async def handle_callback_event(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Handle inline keyboard callback queries."""
    locale = "fa"
    user_id = event_user_id(event)
    if user_id:
        locale = await settings.get_user_locale(user_id)

    await ctx.renderer.send_typing(event.chat_id)
    if event.callback_id:
        await ctx.renderer.answer_callback(
            event.callback_id,
            text("messages.processing", locale=locale),
            raw_event=event.raw,
        )

    data = event.data or ""

    if await handle_settings_callback(data, event, ctx, locale, user_id):
        return
    if await handle_billing_callback(data, event, ctx, locale):
        return
    if await handle_convert_callback(data, event, ctx, locale, user_id):
        return
    if await handle_chat_callback(data, event, ctx, locale):
        return
    if await handle_action_callback(data, event, ctx, locale, user_id):
        return
