"""Chat-from-result and promptic action callbacks."""

from __future__ import annotations

import logging

from apps.bots.common import actions
from apps.bots.common.callbacks.content import get_content
from apps.bots.common.events import CallbackEvent, MessageEvent, MessageRef
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    require_verified_callback,
    sent_message_id,
)
from utils.i18n import text

logger = logging.getLogger(__name__)


async def handle_chat_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> bool:
    """Handle chat:transcript / chat:voice. Returns True when handled."""
    if data == "chat:transcript":
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return True
        usso_uid, _bot_user = verified
        await _handle_transcript_chat(event, ctx, locale, usso_uid)
        return True

    if data == "chat:voice":
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return True
        usso_uid, _bot_user = verified
        await _handle_voice_chat(event, ctx, locale, usso_uid)
        return True

    return False


async def handle_action_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    user_id: str | None,
) -> bool:
    """Handle action:* promptic callbacks. Returns True when handled."""
    if not data.startswith("action:"):
        return False

    verified = await require_verified_callback(event, ctx, locale)
    if not verified:
        return True
    usso_uid, bot_user = verified
    action_name = data.split(":", 1)[1]
    prompt = actions.map_callback_action(action_name)
    if prompt and user_id:
        target_lang = (
            (bot_user.preferred_language if bot_user else locale)
            if action_name == "translate"
            else "auto"
        )
        content = await get_content(event, ctx)
        if not content:
            await ctx.renderer.send_text(
                event.chat_id,
                text("messages.no_content", locale=locale),
                reply_to=event.message_id,
            )
            return True
        processing_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.processing", locale=target_lang),
            reply_to=event.message_id,
        )
        processing_msg_id = sent_message_id(processing_msg, event.message_id)
        meta = {
            **dict(event.metadata),
            "chat_id": event.chat_id,
            "message_id": processing_msg_id,
            "reply_to_message_id": event.message_id,
            "bot_name": ctx.bot_name,
            "user_id": usso_uid,
            "locale": target_lang,
            "action_name": action_name,
        }
        try:
            result = await actions.run_promptic_action(
                prompt_name=prompt,
                content=content,
                user_id=usso_uid,
                target_language=target_lang,
                meta_data=meta,
            )
            task_uid = str(result.get("uid") or result.get("id") or "")
        except Exception:
            logger.exception("Promptic action %s submission failed", action_name)
            task_uid = ""
        if not task_uid:
            await ctx.renderer.edit_message(
                event.chat_id,
                processing_msg_id,
                text("messages.file_processing_error", locale=target_lang),
            )
    return True


async def _handle_voice_chat(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    usso_uid: str,
) -> None:
    """Send a transcribed voice result directly to chat with reply-chain context."""
    from apps.bots.common import context

    transcript = await get_content(event, ctx)
    if not transcript:
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return

    stored = await context.get_message_by_platform_id(
        event.platform,
        str(event.chat_id),
        str(event.message_id),
    )
    reply_to = (
        MessageRef(message_id=stored.reply_to_platform_message_id)
        if stored and stored.reply_to_platform_message_id
        else None
    )
    chat_event = MessageEvent(
        platform=event.platform,
        chat_id=event.chat_id,
        message_id=event.message_id,
        sender=event.sender,
        reply_to=reply_to,
    )
    try:
        response = await context.chat_completion(
            chat_event,
            transcript,
            locale=locale,
            renderer=ctx.renderer,
        )
    except context.InsufficientCreditsError:
        await context.notify_admin_insufficient_credits(ctx.renderer, event.chat_id)
        response = text("messages.insufficient_credits", locale=locale)

    sent = await ctx.renderer.send_text(
        event.chat_id,
        response[: ctx.capabilities.max_text_chars or 4096],
        reply_to=event.message_id,
    )
    response_message_id = sent_message_id(sent, event.message_id)
    if str(response_message_id) == str(event.message_id):
        logger.warning("Assistant message id matched voice chat %s", event.message_id)
        return
    await context.store_message(
        platform=event.platform,
        platform_chat_id=str(event.chat_id),
        platform_message_id=str(response_message_id),
        role="assistant",
        content=response,
        user_id=usso_uid,
        reply_to_platform_message_id=str(event.message_id),
        content_type="text",
    )


async def _handle_transcript_chat(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    usso_uid: str,
) -> None:
    """Send a transcribed voice message to chat with its reply-chain context."""
    from apps.bots.common import context

    transcript = await get_content(event, ctx)
    if not transcript:
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return

    stored = await context.get_message_by_platform_id(
        event.platform,
        str(event.chat_id),
        str(event.message_id),
    )
    reply_to = (
        MessageRef(message_id=stored.reply_to_platform_message_id)
        if stored and stored.reply_to_platform_message_id
        else None
    )
    chat_event = MessageEvent(
        platform=event.platform,
        chat_id=event.chat_id,
        message_id=event.message_id,
        sender=event.sender,
        reply_to=reply_to,
    )
    try:
        response = await context.chat_completion(
            chat_event,
            transcript,
            locale=locale,
            renderer=ctx.renderer,
        )
    except context.InsufficientCreditsError:
        await context.notify_admin_insufficient_credits(ctx.renderer, event.chat_id)
        response = text("messages.insufficient_credits", locale=locale)

    sent = await ctx.renderer.send_text(
        event.chat_id,
        response[: ctx.capabilities.max_text_chars or 4096],
        reply_to=event.message_id,
    )
    response_message_id = sent_message_id(sent, event.message_id)
    if str(response_message_id) == str(event.message_id):
        logger.warning("Assistant message id matched transcript %s", event.message_id)
        return
    await context.store_message(
        platform=event.platform,
        platform_chat_id=str(event.chat_id),
        platform_message_id=str(response_message_id),
        role="assistant",
        content=response,
        user_id=usso_uid,
        reply_to_platform_message_id=str(event.message_id),
    )
