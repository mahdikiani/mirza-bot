"""Inbound text / file / URL message orchestration."""


from __future__ import annotations

import logging

from apps.ai.clients import InsufficientCreditsError
from apps.bots.common import context, settings
from apps.bots.common import keyboards as kb
from apps.bots.common.auth_gate import VerifiedUserStatus, resolve_verified_user
from apps.bots.common.events import MessageEvent
from apps.bots.common.files import handle_file_event
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    event_user_id,
    is_command,
    prompt_contact,
    require_verified_user,
    sent_message_id,
    strip_bot_mention,
)
from apps.bots.common.handlers.menu import (
    handle_menu_action,
    resolve_locale,
    send_main_menu,
)
from apps.bots.common.menu import resolve_menu_action
from apps.bots.common.onboarding import (
    is_typed_phone_rejection,
    typed_phone_rejection_message,
)
from apps.bots.common.urls import handle_urls_message
from utils.i18n import text
from utils.texttools import contains_valid_urls

logger = logging.getLogger(__name__)


async def _handle_slash_commands(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    text_value: str,
    locale: str,
) -> bool:
    """Handle /start /help /settings /info /models. Return True if consumed."""
    if is_command(text_value, "/start"):
        status, _verified = await resolve_verified_user(event)
        if status == VerifiedUserStatus.needs_contact:
            await prompt_contact(ctx, event, locale)
            return True
        if status == VerifiedUserStatus.no_platform_user:
            await ctx.renderer.send_text(
                event.chat_id, text("messages.no_user", locale=locale)
            )
            return True
        await send_main_menu(ctx, event.chat_id, locale, reply_to=event.message_id)
        return True

    if is_command(text_value, "/help"):
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.help", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return True

    if is_command(text_value, "/settings"):
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.settings_prompt", locale=locale),
            kb.settings_language_keyboard(current_lang=locale),
            reply_to=event.message_id,
        )
        return True

    if is_command(text_value, "/info"):
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.info", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return True

    if is_command(text_value, "/models"):
        messenger_id = event_user_id(event)
        current_model = (
            await settings.get_user_model(messenger_id)
            if messenger_id
            else settings.DEFAULT_MODEL
        )
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.model_prompt", locale=locale),
            kb.settings_model_keyboard(current_model=current_model),
            reply_to=event.message_id,
        )
        return True

    return False


async def _handle_inbound_file(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    *,
    usso_uid: str,
    locale: str,
    text_value: str,
    workspace_id: str | None = None,
) -> None:
    """Process an attached file (text extract or async OCR/transcribe)."""
    file_name = event.file.file_name or "file.bin"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if ext in {"txt", "md", "markdown", "docx"}:
        await handle_file_event(
            event=event,
            ctx=ctx,
            user_id=usso_uid,
            locale=locale,
            response_message_id=event.message_id,
            user_prompt=text_value or None,
            workspace_id=workspace_id,
        )
        return

    if hasattr(ctx.renderer, "send_upload_action"):
        await ctx.renderer.send_upload_action(event.chat_id)
    processing_msg = await ctx.renderer.send_text(
        event.chat_id,
        text("messages.processing", locale=locale),
        reply_to=event.message_id,
    )
    response_id = sent_message_id(processing_msg, event.message_id)
    try:
        await handle_file_event(
            event=event,
            ctx=ctx,
            user_id=usso_uid,
            locale=locale,
            response_message_id=response_id,
            user_prompt=text_value or None,
            workspace_id=workspace_id,
        )
    except Exception:
        logger.exception("File processing failed")
        await ctx.renderer.edit_message(
            event.chat_id,
            response_id,
            text("messages.file_processing_error", locale=locale),
        )


async def _handle_chat_text(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    *,
    usso_uid: str,
    locale: str,
    text_value: str,
) -> None:
    """Store user text, complete via AI, and store the assistant reply."""
    cleaned = strip_bot_mention(text_value, ctx.bot_username)
    await context.store_message(
        platform=event.platform,
        platform_chat_id=str(event.chat_id),
        platform_message_id=str(event.message_id),
        role="user",
        content=cleaned,
        user_id=usso_uid,
        reply_to_platform_message_id=(
            str(event.reply_to.message_id) if event.reply_to else None
        ),
    )
    try:
        response = await context.chat_completion(
            event, cleaned, locale=locale, renderer=ctx.renderer
        )
    except InsufficientCreditsError:
        await context.notify_admin_insufficient_credits(ctx.renderer, event.chat_id)
        response = text("messages.insufficient_credits", locale=locale)
    sent = await ctx.renderer.send_text(
        event.chat_id,
        response[: ctx.capabilities.max_text_chars or 4096],
        reply_to=event.message_id,
    )
    sent_id = sent_message_id(sent, event.message_id)
    if str(sent_id) == str(event.message_id):
        logger.warning(
            "Assistant message id matched inbound id; skipping assistant store"
        )
        return
    await context.store_message(
        platform=event.platform,
        platform_chat_id=str(event.chat_id),
        platform_message_id=str(sent_id),
        role="assistant",
        content=response,
        user_id=usso_uid,
        reply_to_platform_message_id=str(event.message_id),
    )


async def handle_message_event(
    event: MessageEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Handle a normalized inbound user message."""
    text_value = (event.text or event.caption or "").strip()
    locale = await resolve_locale(event)

    if is_typed_phone_rejection(text_value):
        await ctx.renderer.send_text(
            event.chat_id,
            typed_phone_rejection_message(locale),
            reply_to=event.message_id,
        )
        return

    if not context.should_respond_in_group(
        event, ctx.bot_username or "", ctx.bot_user_id
    ):
        return

    if not text_value and not event.file:
        return

    await ctx.renderer.send_typing(event.chat_id)

    if await _handle_slash_commands(event, ctx, text_value, locale):
        return

    verified = await require_verified_user(event, ctx, locale)
    if not verified:
        return
    usso_uid, bot_user = verified
    workspace_id = getattr(bot_user, "telegram_workspace_id", None)

    menu_action = resolve_menu_action(text_value)
    if menu_action and await handle_menu_action(
        menu_action, event, ctx, locale, usso_uid
    ):
        return

    if event.file:
        await _handle_inbound_file(
            event,
            ctx,
            usso_uid=usso_uid,
            locale=locale,
            text_value=text_value,
            workspace_id=workspace_id,
        )
        return

    if contains_valid_urls(text_value):
        await handle_urls_message(
            event, ctx, text_value, usso_uid, locale, workspace_id=workspace_id
        )
        return

    if text_value:
        await _handle_chat_text(
            event, ctx, usso_uid=usso_uid, locale=locale, text_value=text_value
        )
