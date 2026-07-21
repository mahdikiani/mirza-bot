"""
Platform-agnostic bot orchestration.

Adapters normalize updates into events and call this module.
"""

from __future__ import annotations

import logging

from apps.ai.clients import CompletionClient, InsufficientCreditsError
from apps.bots.common import billing, context, settings
from apps.bots.common import keyboards as kb
from apps.bots.common.auth_gate import VerifiedUserStatus, resolve_verified_user
from apps.bots.common.callbacks import handle_callback_event
from apps.bots.common.events import InlineQueryEvent, MessageEvent
from apps.bots.common.files import handle_file_event
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    EventRenderer,
    event_user_id,
    is_command,
    prompt_contact,
    require_verified_user,
    sent_message_id,
    strip_bot_mention,
)
from apps.bots.common.menu import resolve_menu_action
from apps.bots.common.onboarding import (
    contact_mismatch_message,
    contact_user_id_matches,
    detect_locale,
    get_or_create_bot_user_from_contact,
    is_typed_phone_rejection,
    typed_phone_rejection_message,
)
from apps.bots.common.urls import handle_urls_message
from utils.i18n import text
from utils.texttools import contains_valid_urls

logger = logging.getLogger(__name__)

__all__ = [
    "BotRuntimeContext",
    "EventRenderer",
    "handle_callback_event",
    "handle_contact_event",
    "handle_inline_query_event",
    "handle_message_event",
]


async def _resolve_locale(event: MessageEvent) -> str:
    user_id = event_user_id(event)
    if user_id:
        return await settings.get_user_locale(user_id)
    return detect_locale(str(event.metadata.get("language_code") or ""))


async def _send_main_menu(
    ctx: BotRuntimeContext,
    chat_id: int | str,
    locale: str,
    *,
    reply_to: int | str | None = None,
    message_key: str = "messages.start",
) -> None:
    await ctx.renderer.send_text(
        chat_id,
        text(message_key, locale=locale),
        reply_to=reply_to,
        reply_keyboard=kb.main_menu_keyboard(),
    )


async def handle_contact_event(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    phone_number: str,
    contact_user_id: int | str,
) -> None:
    """Complete onboarding after the user shares a verified contact."""
    locale = await _resolve_locale(event)
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

    await _send_main_menu(
        ctx,
        event.chat_id,
        locale,
        reply_to=event.message_id,
        message_key="messages.onboarding_success",
    )


async def _handle_menu_action(
    action: str,
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
    usso_uid: str,
) -> bool:
    if action == "help":
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.help", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return True

    if action == "info":
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.info", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return True

    if action == "models":
        from apps.bots.common.onboarding import get_bot_user

        bot_user = await get_bot_user(usso_uid) if usso_uid else None
        current = bot_user.preferred_model if bot_user else settings.DEFAULT_MODEL
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.model_prompt", locale=locale),
            kb.settings_model_keyboard(current_model=current),
            reply_to=event.message_id,
        )
        return True

    if action in {"account", "balance"}:
        balance_msg = await billing.fetch_balance(usso_uid, locale=locale)
        await ctx.renderer.send_text(
            event.chat_id,
            balance_msg,
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return True

    if action == "settings":
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.settings_prompt", locale=locale),
            kb.settings_language_keyboard(current_lang=locale),
            reply_to=event.message_id,
        )
        return True

    if action in {"purchase", "menu"}:
        await _show_products(event, ctx, locale, page=0)
        return True

    return False


async def _show_products(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
    page: int,
) -> None:
    msg, products, total = await billing.fetch_products_page(locale=locale, page=page)
    if not products:
        await ctx.renderer.send_text(
            event.chat_id,
            msg,
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return
    keyboard = kb.products_keyboard(products, page, total)
    await ctx.renderer.send_inline_text(
        event.chat_id,
        msg,
        keyboard,
        reply_to=event.message_id,
    )


async def handle_message_event(
    event: MessageEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Handle a normalized inbound user message."""
    text_value = (event.text or event.caption or "").strip()
    locale = await _resolve_locale(event)

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

    if is_command(text_value, "/start"):
        status, _verified = await resolve_verified_user(event)
        if status == VerifiedUserStatus.needs_contact:
            await prompt_contact(ctx, event, locale)
            return
        if status == VerifiedUserStatus.no_platform_user:
            await ctx.renderer.send_text(
                event.chat_id, text("messages.no_user", locale=locale)
            )
            return
        await _send_main_menu(ctx, event.chat_id, locale, reply_to=event.message_id)
        return

    if is_command(text_value, "/help"):
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.help", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return

    if is_command(text_value, "/settings"):
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.settings_prompt", locale=locale),
            kb.settings_language_keyboard(current_lang=locale),
            reply_to=event.message_id,
        )
        return

    if is_command(text_value, "/info"):
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.info", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return

    if is_command(text_value, "/models"):
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.model_prompt", locale=locale),
            kb.settings_model_keyboard(current_model=settings.DEFAULT_MODEL),
            reply_to=event.message_id,
        )
        return

    verified = await require_verified_user(event, ctx, locale)
    if not verified:
        return
    usso_uid, _bot_user = verified

    menu_action = resolve_menu_action(text_value)
    if menu_action and await _handle_menu_action(
        menu_action, event, ctx, locale, usso_uid
    ):
        return

    if event.file:
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
            )
        except Exception:
            logger.exception("File processing failed")
            await ctx.renderer.edit_message(
                event.chat_id,
                response_id,
                text("messages.file_processing_error", locale=locale),
            )
        return

    urls = contains_valid_urls(text_value)
    if urls:
        await handle_urls_message(event, ctx, text_value, usso_uid, locale)
        return

    if text_value:
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
            await context.notify_admin_insufficient_credits(
                ctx.renderer, event.chat_id
            )
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


async def handle_inline_query_event(
    event: InlineQueryEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Answer inline queries with a stateless completion."""
    if not event.text.strip():
        response = text("messages.inline_empty")
    else:
        messages = [{"role": "user", "content": event.text}]
        try:
            response = await CompletionClient.complete(messages)
        except Exception:
            logger.exception("Inline query completion failed")
            response = text("messages.ai_error", locale="fa")

    await ctx.renderer.answer_inline_query(
        event.query_id,
        response,
        raw_event=event.raw,
    )
