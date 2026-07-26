"""Purchase / products callback handlers."""

from __future__ import annotations

import logging

from apps.bots.common import billing
from apps.bots.common import keyboards as kb
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    bot_return_url,
    require_verified_callback,
)
from utils.i18n import text

logger = logging.getLogger(__name__)


async def handle_billing_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> bool:
    """Handle products/buy/menu:purchase callbacks. Returns True when handled."""
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
        return True

    if data.startswith("buy:"):
        verified = await require_verified_callback(event, ctx, locale)
        if not verified:
            return True
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
        return True

    if data == "menu:purchase":
        msg, products, total = await billing.fetch_products_page(locale=locale, page=0)
        keyboard = kb.products_keyboard(products, 0, total)
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            msg,
            inline_keyboard=keyboard,
        )
        return True

    return False
