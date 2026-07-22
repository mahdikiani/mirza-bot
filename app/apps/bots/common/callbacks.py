"""Inline keyboard callback handling."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import tempfile

from apps.ai import result_content_cache
from apps.bots.common import actions, billing, settings
from apps.bots.common import keyboards as kb
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    bot_return_url,
    event_user_id,
    require_verified_callback,
    sent_message_id,
)
from apps.bots.common.onboarding import get_bot_user
from utils.i18n import text

logger = logging.getLogger(__name__)


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
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return
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
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return
        usso_uid, _bot_user = verified
        product_uid = data.split(":", 1)[1]
        return_url = bot_return_url(ctx)
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

    if data == "convert:menu":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
            inline_keyboard=kb.convert_keyboard(),
        )
        return

    if data == "convert:back":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text=None,
        )
        return

    if data == "convert:pdf":
        await ctx.renderer.answer_callback(event.callback_id, "🔜 به زودی")
        return

    if data == "convert:audio":
        await ctx.renderer.answer_callback(event.callback_id, "🔜 به زودی")
        return

    if data == "convert:docx":
        await _handle_convert_docx(event, ctx, locale, user_id)
        return

    if data == "convert:markdown":
        await _handle_convert_markdown(event, ctx, locale)
        return

    if data.startswith("action:"):
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return
        usso_uid, bot_user = verified
        action_name = data.split(":", 1)[1]
        prompt = actions.map_callback_action(action_name)
        if prompt and user_id:
            preserve_lang = action_name in {"summarize", "structure", "format_notes", "cleanup", "minutes", "quiz", "ask_question"}
            target_lang = (
                (bot_user.preferred_language if bot_user else locale)
                if action_name == "translate"
                else "auto"
            )
            content = await _get_content(event, ctx)
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
            }
            await actions.run_promptic_action(
                prompt_name=prompt,
                content=content,
                user_id=usso_uid,
                target_language=target_lang,
                meta_data=meta,
            )


async def _get_content(event: CallbackEvent, ctx: BotRuntimeContext) -> str:
    """Get the raw Markdown content the callback's message was delivered with.

    Prefers the cache saved at delivery time (see result_content_cache):
    once a result is sent as real rich text (bold/italic entities), the
    platform strips the literal Markdown syntax from the message's plain
    text, so re-reading it back via download_document no longer contains
    the "# "/"**" markers the convert-to-file handlers depend on.
    """
    if event.message_id:
        try:
            cached = await result_content_cache.get(event.message_id)
        except Exception:
            logger.debug("Result content cache lookup failed for %s", event.message_id)
            cached = None
        if cached:
            return cached
        doc_bytes = await ctx.renderer.download_document(
            event.chat_id, event.message_id
        )
        if doc_bytes:
            return doc_bytes.decode("utf-8", errors="replace")
    return event.message_text or ""


async def _handle_convert_docx(
    event: CallbackEvent, ctx: BotRuntimeContext, locale: str, user_id: str | None
) -> None:
    """Convert Markdown to DOCX using pandoc with proper RTL/font styles."""
    await ctx.renderer.answer_callback(event.callback_id, "⏳")
    content = await _get_content(event, ctx)
    if not content:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return

    try:
        from utils.clients.media import MediaClient

        ref_path = await _get_reference_docx()

        md_bytes = content.encode("utf-8")

        proc = await asyncio.create_subprocess_exec(
            "pandoc",
            "--from", "markdown+pipe_tables+tex_math_dollars+hard_line_breaks",
            "--to", "docx",
            f"--reference-doc={ref_path}",
            "--wrap=preserve",
            "-o", "/tmp/_convert_output.docx",
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(input=md_bytes)

        if proc.returncode != 0:
            raise RuntimeError(f"pandoc failed: {stderr.decode(errors='replace')}")

        with open("/tmp/_convert_output.docx", "rb") as f:
            docx_bytes = f.read()

        os.unlink("/tmp/_convert_output.docx")

        await MediaClient.upload(docx_bytes, "document.docx")
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


_REFERENCE_DOCX_CACHE: str | None = None


async def _get_reference_docx() -> str:
    """Create and cache a reference DOCX with proper RTL Persian/English styles."""
    global _REFERENCE_DOCX_CACHE
    if _REFERENCE_DOCX_CACHE and os.path.exists(_REFERENCE_DOCX_CACHE):
        return _REFERENCE_DOCX_CACHE

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement, qn
    from docx.shared import Pt, RGBColor

    doc = Document()

    style = doc.styles["Normal"]
    style.font.size = Pt(11)
    pf = style.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pf.space_after = Pt(6)

    def _rFonts(rpr, *, cs="B Nazanin", latin="Calibri"):
        rf = rpr.find(qn("w:rFonts"))
        if rf is None:
            rf = OxmlElement("w:rFonts")
            rpr.append(rf)
        rf.set(qn("w:ascii"), latin)
        rf.set(qn("w:hAnsi"), latin)
        rf.set(qn("w:cs"), cs)
        rf.set(qn("w:eastAsia"), latin)

    rpr = style.element.get_or_add_rPr()
    _rFonts(rpr)

    pPr = style.element.get_or_add_pPr()
    if pPr.find(qn("w:bidi")) is None:
        pPr.append(OxmlElement("w:bidi"))
    sz = rpr.find(qn("w:sz"))
    if sz is None:
        rpr.append(OxmlElement("w:sz"))
        rpr.find(qn("w:sz")).set(qn("w:val"), "22")

    for level in range(1, 4):
        hs = doc.styles[f"Heading {level}"]
        hs.font.bold = True
        hpr = hs.element.get_or_add_rPr()
        _rFonts(hpr)
        if hpr.find(qn("w:bidi")) is None:
            hpr.append(OxmlElement("w:bidi"))
        hpf = hs.paragraph_format
        hpf.space_before = Pt(12)
        hpf.space_after = Pt(6)
        hpf.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    path = "/tmp/_ref_docx.docx"
    doc.save(path)
    _REFERENCE_DOCX_CACHE = path
    return path


async def _handle_convert_markdown(
    event: CallbackEvent, ctx: BotRuntimeContext, locale: str
) -> None:
    """Send the delivered result as a Markdown file."""
    await ctx.renderer.answer_callback(event.callback_id, "⏳")
    content = await _get_content(event, ctx)
    if not content:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.no_content", locale=locale),
            reply_to=event.message_id,
        )
        return
    try:
        from utils.clients.media import MediaClient

        md_bytes = content.encode("utf-8")
        await MediaClient.upload(md_bytes, "document.md")
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
            event.chat_id, "❌ خطا در ارسال فایل",
            reply_to=event.message_id,
        )
