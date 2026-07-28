"""Convert-to-file callback handlers."""

from __future__ import annotations

import logging

from apps.bots.common import keyboards as kb
from apps.bots.common.callbacks.content import get_content
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import BotRuntimeContext
from utils.i18n import text

logger = logging.getLogger(__name__)


async def handle_convert_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    user_id: str | None,
) -> bool:
    """Handle convert:* callbacks. Returns True when handled."""
    if data.startswith("convert:menu"):
        parts = data.split(":", 2)
        content_type = parts[2] if len(parts) > 2 else ""
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
            inline_keyboard=kb.convert_keyboard(content_type=content_type),
        )
        return True

    if data == "convert:back":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
        )
        return True

    if data == "convert:docx":
        await _handle_convert_docx(event, ctx, locale, user_id)
        return True

    if data == "convert:markdown":
        await _handle_convert_markdown(event, ctx, locale)
        return True

    return False


async def _handle_convert_docx(
    event: CallbackEvent, ctx: BotRuntimeContext, locale: str, user_id: str | None
) -> None:
    """Convert Markdown to DOCX via the AI Toolkit's document-convert API."""
    await ctx.renderer.answer_callback(event.callback_id, "⏳")
    content = await get_content(event, ctx)
    if not content:
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return

    try:
        from utils.clients.toolkit import convert_markdown_to_docx

        docx_bytes = await convert_markdown_to_docx(content)

        await ctx.renderer.send_document(
            event.chat_id,
            file_data=docx_bytes,
            file_name="document.docx",
            caption="📄 فایل Word",
            reply_to=event.message_id,
        )
    except Exception:
        logger.exception("DOCX generation failed")
        await ctx.renderer.answer_callback(event.callback_id, "❌ خطا")


async def _handle_convert_markdown(
    event: CallbackEvent, ctx: BotRuntimeContext, locale: str
) -> None:
    """Send the delivered result as a Markdown file."""
    await ctx.renderer.answer_callback(event.callback_id, "⏳")
    content = await get_content(event, ctx)
    if not content:
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return
    try:
        md_bytes = content.encode("utf-8")
        await ctx.renderer.send_document(
            event.chat_id,
            file_data=md_bytes,
            file_name="document.md",
            caption="📝 فایل Markdown",
            reply_to=event.message_id,
        )
    except Exception:
        logger.exception("MD upload failed")
        await ctx.renderer.send_text(
            event.chat_id,
            "❌ خطا در ارسال فایل",
            reply_to=event.message_id,
        )
