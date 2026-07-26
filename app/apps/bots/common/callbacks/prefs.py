"""Language and model preference callbacks."""

from __future__ import annotations

from apps.bots.common import keyboards as kb
from apps.bots.common import settings
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    require_verified_callback,
)
from utils.i18n import text


async def handle_settings_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    user_id: str | None,
) -> bool:
    """Handle settings:* callbacks. Returns True when handled."""
    if data == "settings:lang:menu":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.settings_prompt", locale=locale),
            inline_keyboard=kb.settings_language_keyboard(current_lang=locale),
        )
        return True

    if data.startswith("settings:lang:"):
        lang = data.rsplit(":", 1)[-1]
        if user_id:
            await settings.set_preferred_language(user_id, lang)
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.language_changed", locale=lang),
            reply_to=event.message_id,
        )
        return True

    if data == "settings:model:menu":
        current = (
            await settings.get_user_model(user_id)
            if user_id
            else settings.DEFAULT_MODEL
        )
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.model_prompt", locale=locale),
            inline_keyboard=kb.settings_model_keyboard(current),
        )
        return True

    if data.startswith("settings:model:"):
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return True
        model = data.split(":", 2)[-1]
        if not settings.is_allowed_model(model):
            await ctx.renderer.answer_callback(
                event.callback_id,
                text("messages.model_not_allowed", locale=locale),
            )
            return True
        if user_id:
            await settings.set_preferred_model(user_id, model)
        current = (
            await settings.get_user_model(user_id)
            if user_id
            else settings.DEFAULT_MODEL
        )
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.model_changed", locale=locale, model=model),
            inline_keyboard=kb.settings_model_keyboard(current),
        )
        return True

    return False
