"""Main menu, products, and locale helpers for message orchestration."""


from __future__ import annotations

from apps.bots.common import billing, settings
from apps.bots.common import keyboards as kb
from apps.bots.common.callbacks.team import send_team_menu
from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext, event_user_id
from apps.bots.common.onboarding import detect_locale
from utils.i18n import text


async def resolve_locale(event: MessageEvent) -> str:
    """Resolve the UI locale for an inbound message event."""
    user_id = event_user_id(event)
    if user_id:
        return await settings.get_user_locale(user_id)
    return detect_locale(str(event.metadata.get("language_code") or ""))


async def send_main_menu(
    ctx: BotRuntimeContext,
    chat_id: int | str,
    locale: str,
    *,
    reply_to: int | str | None = None,
    message_key: str = "messages.start",
) -> None:
    """Send the main reply keyboard menu to a chat."""
    await ctx.renderer.send_text(
        chat_id,
        text(message_key, locale=locale),
        reply_to=reply_to,
        reply_keyboard=kb.main_menu_keyboard(),
    )


async def handle_menu_action(
    action: str,
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
    usso_uid: str,
    bot_user: object = None,
) -> bool:
    """Handle a main-menu text action; return True if consumed."""
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
        messenger_id = event_user_id(event)
        current = (
            await settings.get_user_model(messenger_id)
            if messenger_id
            else settings.DEFAULT_MODEL
        )
        await ctx.renderer.send_inline_text(
            event.chat_id,
            text("messages.model_prompt", locale=locale),
            kb.settings_model_keyboard(current_model=current),
            reply_to=event.message_id,
        )
        return True

    if action in {"account", "balance"}:
        workspace_id = getattr(bot_user, "telegram_workspace_id", None)
        balance_msg = await billing.fetch_balance(
            usso_uid, locale=locale, workspace_id=workspace_id
        )
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
        await show_products(event, ctx, locale, page=0)
        return True

    if action == "team" and bot_user is not None:
        await send_team_menu(
            ctx, event.chat_id, locale, bot_user, usso_uid, reply_to=event.message_id
        )
        return True

    return False


async def show_products(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    locale: str,
    page: int,
) -> None:
    """Send a paginated products list with purchase inline keyboard."""
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
