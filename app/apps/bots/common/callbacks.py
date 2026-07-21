"""Inline keyboard callback handling."""

from __future__ import annotations

import logging

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
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.convert_prompt", locale=locale),
            kb.convert_keyboard(),
            reply_to=event.message_id,
        )
        return

    if data == "convert:back":
        if event.message_id:
            await ctx.renderer.delete_message(event.chat_id, event.message_id)
        return

    if data == "convert:pdf":
        await ctx.renderer.answer_callback(event.callback_id, "🔜 به زودی")
        return

    if data == "convert:audio":
        await ctx.renderer.answer_callback(event.callback_id, "🔜 به زودی")
        return

    if data == "convert:docx":
        await ctx.renderer.answer_callback(event.callback_id, "⏳")
        content = await _get_content(event, ctx)
        if not content:
            await ctx.renderer.send_text(
                event.chat_id, text("messages.no_content", locale=locale),
                reply_to=event.message_id,
            )
            return
        try:
            from io import BytesIO
            from docx import Document
            from docx.oxml.ns import qn
            from docx.oxml import OxmlElement
            from docx.shared import Pt, RGBColor
            from docx.enum.text import WD_ALIGN_PARAGRAPH
            from utils.clients.media import MediaClient

            doc = Document()
            style = doc.styles["Normal"]
            style.font.size = Pt(11)
            rpr = style.element.get_or_add_rPr()
            def _xml(t: str): e = OxmlElement(t); return e
            rFonts = rpr.find(qn("w:rFonts"))
            if rFonts is None:
                rFonts = _xml("w:rFonts")
                rpr.append(rFonts)
            rFonts.set(qn("w:ascii"), "Calibri")
            rFonts.set(qn("w:hAnsi"), "Calibri")
            rFonts.set(qn("w:cs"), "B Nazanin")
            pPr = style.element.get_or_add_pPr()
            if pPr.find(qn("w:bidi")) is None:
                pPr.append(_xml("w:bidi"))

            for line in content.split("\n"):
                strip = line.strip()
                if not strip:
                    continue
                if strip.startswith("# "):
                    p = doc.add_heading(strip[2:], level=1)
                elif strip.startswith("## "):
                    p = doc.add_heading(strip[3:], level=2)
                elif strip.startswith("### "):
                    p = doc.add_heading(strip[4:], level=3)
                elif strip.startswith("!["):
                    continue
                else:
                    p = doc.add_paragraph(strip)
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                pPr = p._element.get_or_add_pPr()
                if pPr.find(qn("w:bidi")) is None:
                    pPr.append(_xml("w:bidi"))

            buf = BytesIO()
            doc.save(buf)
            buf.seek(0)
            docx_url = await MediaClient.upload(buf.getvalue(), "document.docx")
            await ctx.renderer.send_document(
                event.chat_id,
                file_data=buf.getvalue(),
                file_name="document.docx",
                caption="📄 فایل Word",
                reply_to=event.message_id,
            )
        except Exception:
            logger.exception("DOCX generation failed")
            await ctx.renderer.answer_callback(event.callback_id, "❌ خطا")
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
    """Get the text content from the message the callback was fired on."""
    if event.message_id:
        doc_bytes = await ctx.renderer.download_document(
            event.chat_id, event.message_id
        )
        if doc_bytes:
            return doc_bytes.decode("utf-8", errors="replace")
    return event.message_text or ""
