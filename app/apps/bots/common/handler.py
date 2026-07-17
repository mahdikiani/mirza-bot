"""
Platform-agnostic bot orchestration.

Adapters normalize updates into events and call this module.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from apps.accounts.handlers import get_existing_usso_user
from apps.ai.clients import CompletionClient
from apps.bots.common import actions, billing, context, media_flow, settings
from apps.bots.common import keyboards as kb
from apps.bots.common.docx import extract_docx_text
from apps.bots.common.events import (
    CallbackEvent,
    InlineQueryEvent,
    MessageEvent,
    PlatformCapabilities,
)
from apps.bots.common.keyboards import InlineKeyboard, ReplyKeyboard
from apps.bots.common.link_router import LinkKind, classify_urls_in_text
from apps.bots.common.menu import resolve_menu_action
from apps.bots.common.onboarding import (
    contact_mismatch_message,
    contact_user_id_matches,
    detect_locale,
    get_bot_user,
    get_or_create_bot_user_from_contact,
    is_typed_phone_rejection,
    typed_phone_rejection_message,
)
from utils.i18n import text
from utils.texttools import contains_valid_urls

logger = logging.getLogger(__name__)


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


def _event_user_id(event: MessageEvent | CallbackEvent) -> str | None:
    if event.sender:
        return str(event.sender.id)
    value = event.metadata.get("user_id") or event.metadata.get("telegram_user_id")
    return str(value) if value else None


def _is_command(text_value: str, command: str) -> bool:
    return text_value == command or text_value.startswith(f"{command} ")


def _strip_bot_mention(text_value: str, bot_username: str | None) -> str:
    if not bot_username:
        return text_value
    pattern = re.compile(rf"@?{re.escape(bot_username)}\b", re.IGNORECASE)
    return pattern.sub("", text_value).strip()


def _bot_return_url(ctx: BotRuntimeContext) -> str:
    if ctx.platform == "bale":
        return f"https://ble.ir/{ctx.bot_username or ctx.bot_name}"
    return f"https://t.me/{ctx.bot_username or ctx.bot_name}"


def _sent_message_id(message: object | None, fallback: int | str) -> int | str:
    """Extract a platform message identifier from a renderer response."""
    return (
        getattr(message, "id", None) or getattr(message, "message_id", None) or fallback
    )


async def _resolve_locale(event: MessageEvent) -> str:
    user_id = _event_user_id(event)
    if user_id:
        return await settings.get_user_locale(user_id)
    return detect_locale(str(event.metadata.get("language_code") or ""))


async def _existing_user_for_event(event: MessageEvent) -> object | None:
    user_id = _event_user_id(event)
    if not user_id:
        return None
    try:
        return await get_existing_usso_user({
            "identifier_type": "telegram_id",
            "identifier": user_id,
        })
    except Exception:
        logger.exception("Failed to resolve existing user for %s", user_id)
        return None


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


async def _require_verified_user(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> tuple[str, object] | None:
    user_id = _event_user_id(event)
    if not user_id:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.no_user", locale=locale)
        )
        return None

    bot_user = await get_bot_user(user_id)
    if not bot_user or not bot_user.phone_verified:
        await ctx.renderer.send_contact_request(
            event.chat_id,
            text("messages.start_contact", locale=locale),
        )
        return None

    usso_user = await _existing_user_for_event(event)
    if not usso_user and bot_user.usso_synced:
        await ctx.renderer.send_contact_request(
            event.chat_id,
            text("messages.start_contact", locale=locale),
        )
        return None

    usso_uid = bot_user.usso_user_id or user_id
    return usso_uid, bot_user


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

    if _is_command(text_value, "/start"):
        bot_user = await get_bot_user(_event_user_id(event) or "")
        if not bot_user or not bot_user.phone_verified or bot_user.usso_synced:
            usso_user = await _existing_user_for_event(event)
            if not usso_user:
                await ctx.renderer.send_contact_request(
                    event.chat_id,
                    text("messages.start_contact", locale=locale),
                )
                return
        await _send_main_menu(ctx, event.chat_id, locale, reply_to=event.message_id)
        return

    if _is_command(text_value, "/help"):
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.help", locale=locale),
            reply_to=event.message_id,
            reply_keyboard=kb.main_menu_keyboard(),
        )
        return

    if _is_command(text_value, "/settings"):
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.settings_prompt", locale=locale),
            kb.settings_language_keyboard(current_lang=locale),
            reply_to=event.message_id,
        )
        return

    verified = await _require_verified_user(event, ctx, locale)
    if not verified:
        return
    usso_uid, bot_user = verified
    _event_user_id(event) or ""

    menu_action = resolve_menu_action(text_value)
    if menu_action and await _handle_menu_action(
        menu_action, event, ctx, locale, usso_uid
    ):
        return

    if event.file and not text_value:
        file_name = event.file.file_name or "file.bin"
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext in {"txt", "md", "markdown", "docx"}:
            await _handle_file_event(
                event=event,
                ctx=ctx,
                user_id=usso_uid,
                locale=locale,
                response_message_id=event.message_id,
            )
            return

        if hasattr(ctx.renderer, "send_upload_action"):
            await ctx.renderer.send_upload_action(event.chat_id)
        processing_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.processing", locale=locale),
            reply_to=event.message_id,
        )
        response_id = _sent_message_id(processing_msg, event.message_id)
        try:
            await _handle_file_event(
                event=event,
                ctx=ctx,
                user_id=usso_uid,
                locale=locale,
                response_message_id=response_id,
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
        await _handle_urls_message(event, ctx, text_value, usso_uid, locale)
        return

    if text_value:
        cleaned = _strip_bot_mention(text_value, ctx.bot_username)
        response = await context.chat_completion(
            event, cleaned, locale=locale, renderer=ctx.renderer
        )
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
        sent = await ctx.renderer.send_text(
            event.chat_id,
            response[: ctx.capabilities.max_text_chars or 4096],
            reply_to=event.message_id,
        )
        sent_id = getattr(sent, "id", None) or event.message_id
        await context.store_message(
            platform=event.platform,
            platform_chat_id=str(event.chat_id),
            platform_message_id=str(sent_id),
            role="assistant",
            content=response,
            user_id=usso_uid,
            reply_to_platform_message_id=str(event.message_id),
        )


async def _handle_file_event(
    *,
    event: MessageEvent,
    ctx: BotRuntimeContext,
    user_id: str,
    locale: str,
    response_message_id: int | str,
) -> None:
    if not event.file:
        return

    file_name = event.file.file_name or "file.bin"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    text_exts = {"txt", "md", "markdown"}

    if ext in text_exts or ext == "docx":
        downloaded = await ctx.renderer.download_attached_file(event)
        if downloaded:
            if ext == "docx":
                content = extract_docx_text(downloaded[0])
            else:
                content = downloaded[0].decode("utf-8", errors="replace")
            await context.store_message(
                platform=event.platform,
                platform_chat_id=str(event.chat_id),
                platform_message_id=str(event.message_id),
                role="user",
                content=content,
                user_id=user_id,
                content_type="document",
            )
            await ctx.renderer.send_text(
                event.chat_id,
                text("messages.content_added_to_chat", locale=locale),
                reply_to=event.message_id,
                reply_keyboard=kb.main_menu_keyboard(),
            )
        return

    downloaded = await ctx.renderer.download_attached_file(event)
    if not downloaded:
        raise RuntimeError("Could not download attached file")

    file_bytes, resolved_name = downloaded
    task_uid = await media_flow.submit_file_bytes(
        event=event,
        bot_name=ctx.bot_name,
        file_bytes=file_bytes,
        file_name=resolved_name or file_name,
        response_message_id=response_message_id,
        content_type=event.content_type,
        user_id=user_id,
        locale=locale,
    )
    if not task_uid:
        raise RuntimeError("AI Toolkit did not return a task identifier")


async def _handle_urls_message(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    text_value: str,
    user_id: str,
    locale: str,
) -> None:
    classified = classify_urls_in_text(text_value)
    webpage_urls = [url for url, kind in classified if kind == LinkKind.webpage]
    async_urls = [url for url, kind in classified if kind != LinkKind.webpage]

    user_text = text_value
    for url, _ in classified:
        user_text = user_text.replace(url, "").strip()

    if webpage_urls and not async_urls:
        reading_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.reading_link", locale=locale),
            reply_to=event.message_id,
        )
        contents = await media_flow.fetch_webpages_parallel(webpage_urls)
        combined_parts = [part for part in [user_text, *contents] if part]
        combined = "\n\n".join(combined_parts)
        response = await context.chat_completion(
            event, combined, locale=locale, renderer=ctx.renderer
        )
        await ctx.renderer.edit_message(
            event.chat_id,
            _sent_message_id(reading_msg, event.message_id),
            response[: ctx.capabilities.max_text_chars or 4096],
        )
        return

    for url in async_urls:
        processing_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.processing", locale=locale),
            reply_to=event.message_id,
        )
        task_uid = await media_flow.submit_url(
            event=event,
            bot_name=ctx.bot_name,
            url=url,
            response_message_id=_sent_message_id(processing_msg, event.message_id),
            user_id=user_id,
            locale=locale,
        )
        if not task_uid:
            await ctx.renderer.edit_message(
                event.chat_id,
                _sent_message_id(processing_msg, event.message_id),
                text("messages.file_processing_error", locale=locale),
            )
    if webpage_urls:
        contents = await media_flow.fetch_webpages_parallel(webpage_urls)
        if contents:
            combined = (
                "\n\n".join([user_text, *contents])
                if user_text
                else "\n\n".join(contents)
            )
            response = await context.chat_completion(
                event, combined, locale=locale, renderer=ctx.renderer
            )
            await ctx.renderer.send_text(
                event.chat_id,
                response[: ctx.capabilities.max_text_chars or 4096],
                reply_to=event.message_id,
            )


async def handle_callback_event(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
) -> None:
    """Handle inline keyboard callback queries."""
    locale = "fa"
    user_id = _event_user_id(event)
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

    if data == "settings:lang:menu":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.settings_prompt", locale=locale),
            inline_keyboard=kb.settings_language_keyboard(current_lang=locale),
        )
        return

    if data.startswith("settings:lang:"):
        lang = data.rsplit(":", 1)[-1]
        if user_id:
            await settings.set_preferred_language(user_id, lang)
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.language_changed", locale=lang),
            reply_to=event.message_id,
        )
        return

    if data == "settings:model:menu":
        bot_user = await get_bot_user(user_id or "") if user_id else None
        current = bot_user.preferred_model if bot_user else settings.DEFAULT_MODEL
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.model_prompt", locale=locale),
            inline_keyboard=kb.settings_model_keyboard(current),
        )
        return

    if data.startswith("settings:model:"):
        model = data.split(":", 2)[-1]
        if user_id:
            await settings.set_preferred_model(user_id, model)
        bot_user = await get_bot_user(user_id or "") if user_id else None
        current = bot_user.preferred_model if bot_user else settings.DEFAULT_MODEL
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.model_changed", locale=locale, model=model),
            inline_keyboard=kb.settings_model_keyboard(current),
        )
        return

    if data.startswith("products_page:"):
        page = int(data.split(":", 1)[1])
        msg, products, total = await billing.fetch_products_page(
            locale=locale, page=page
        )
        keyboard = kb.products_keyboard(products, page, total)
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            msg,
            inline_keyboard=keyboard,
        )
        return

    if data.startswith("buy:"):
        product_uid = data.split(":", 1)[1]
        bot_user = await get_bot_user(user_id or "") if user_id else None
        usso_uid = bot_user.usso_user_id if bot_user else user_id
        if not usso_uid:
            return
        return_url = _bot_return_url(ctx)
        await ctx.renderer.answer_callback(event.callback_id, "⏳")
        try:
            pay_url = await billing.purchase_product(product_uid, usso_uid, return_url)
            await ctx.renderer.send_text(
                event.chat_id,
                text("messages.purchase_prompt", locale=locale),
                reply_to=event.message_id,
            )
            await ctx.renderer.send_text(event.chat_id, pay_url)
        except Exception:
            logger.exception("Purchase failed for product %s", product_uid)
            await ctx.renderer.send_text(
                event.chat_id,
                text("messages.purchase_error", locale=locale),
            )
        return

    if data == "menu:purchase":
        msg, products, total = await billing.fetch_products_page(locale=locale, page=0)
        keyboard = kb.products_keyboard(products, 0, total)
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            msg,
            inline_keyboard=keyboard,
        )
        return

    if data.startswith("action:"):
        action_name = data.split(":", 1)[1]
        prompt = actions.map_callback_action(action_name)
        if prompt and user_id:
            bot_user = await get_bot_user(user_id)
            target_lang = bot_user.preferred_language if bot_user else locale
            content = event.message_text or ""
            if not content and event.message_id:
                data = await ctx.renderer.download_document(
                    event.chat_id, event.message_id
                )
                if data:
                    content = data.decode("utf-8", errors="replace")
            processing_msg = await ctx.renderer.send_text(
                event.chat_id,
                text("messages.processing", locale=target_lang),
                reply_to=event.message_id,
            )
            meta = {
                **dict(event.metadata),
                "chat_id": event.chat_id,
                "message_id": _sent_message_id(processing_msg, event.message_id),
                "bot_name": ctx.bot_name,
                "user_id": bot_user.usso_user_id if bot_user else user_id,
                "locale": target_lang,
            }
            await actions.run_promptic_action(
                prompt_name=prompt,
                content=content,
                user_id=bot_user.usso_user_id if bot_user else user_id,
                target_language=target_lang,
                meta_data=meta,
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
