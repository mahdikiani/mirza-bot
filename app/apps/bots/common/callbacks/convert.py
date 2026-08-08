"""Convert-to-file callback handlers."""

from __future__ import annotations

import logging

from apps.ai import result_media_cache
from apps.bots.common import keyboards as kb
from apps.bots.common.callbacks.content import get_content
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import BotRuntimeContext
from utils.i18n import text

logger = logging.getLogger(__name__)


async def _result_metadata(event: CallbackEvent) -> dict[str, str | None]:
    """Load cached result metadata, with an empty legacy fallback."""
    if not event.message_id:
        return {}
    try:
        return await result_media_cache.get_metadata(event.message_id) or {}
    except Exception:
        logger.debug("Result metadata cache lookup failed for %s", event.message_id)
        return {}


async def handle_convert_callback(  # ruff: ignore[complex-structure]
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
        metadata = await _result_metadata(event)
        media_url = metadata.get("media_url")
        # Persist the content type even for older results so Back can rebuild
        # the original keyboard after this menu has been opened once.
        try:
            await result_media_cache.save_metadata(
                event.message_id,
                content_type=content_type,
                media_url=media_url,
                docx_url=metadata.get("docx_url"),
                file_id=metadata.get("file_id"),
            )
        except Exception:
            logger.debug("Failed to persist convert menu metadata")
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
            inline_keyboard=kb.convert_keyboard(
                content_type=content_type, media_url=media_url
            ),
        )
        return True

    if data == "convert:back":
        content_type = "document"
        metadata = await _result_metadata(event)
        content_type = metadata.get("content_type") or content_type
        media_url = metadata.get("media_url")
        docx_url = metadata.get("docx_url")
        # The original content type is encoded in the Convert button's
        # callback, but Telegram/Bale only send the new callback payload.
        # Recover it from the stored message when available; document is the
        # safe fallback for legacy messages.
        try:
            from apps.bots.common import context

            artifact = await context.get_artifact_by_platform_message(
                event.platform,
                str(event.chat_id),
                str(event.message_id),
                user_id=user_id or "",
                workspace_id=None,
            )
            if artifact:
                content_type = artifact.source_type or content_type
                media_url = media_url or artifact.media_url
        except Exception:
            logger.debug("Could not restore result metadata for %s", event.message_id)
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
            inline_keyboard=kb.md_result_keyboard(
                content_type, media_url=media_url, docx_url=docx_url
            ),
        )
        return True

    if data == "convert:view":
        metadata = await _result_metadata(event)
        file_id = metadata.get("file_id")
        try:
            from utils.clients.media import MediaClient

            if file_id:
                fresh_url = await MediaClient.signed_url(file_id)
            else:
                # Legacy results predate file_id metadata. Re-upload their
                # cached Markdown once so they can still obtain a fresh URL.
                content = await get_content(event, ctx)
                if not content:
                    raise ValueError("missing result content")  # ruff: ignore[raise-within-try]
                fresh_url = await MediaClient.upload(
                    content.encode("utf-8"),
                    "result.md",
                    user_id=user_id,
                )
            await ctx.renderer.edit_message(
                event.chat_id,
                event.message_id,
                text=None,
                inline_keyboard=kb.convert_keyboard(
                    content_type=metadata.get("content_type") or "document",
                    media_url=fresh_url,
                    view_callback=False,
                ),
            )
        except Exception:
            logger.exception("Failed to refresh viewer URL")
            await ctx.renderer.answer_callback(event.callback_id, "خطا در ساخت لینک")
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
