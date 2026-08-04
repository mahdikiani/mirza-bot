"""Shared (team/B2B) workspace management callbacks."""

from __future__ import annotations

import logging

from apps.accounts.clients import usso_accounts_client
from apps.accounts.handlers import usso_identifier_type_for_platform
from apps.bots.common import keyboards as kb
from apps.bots.common import team_invites
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import (
    BotRuntimeContext,
    bot_return_url,
    event_user_id,
    require_verified_callback,
)
from utils.i18n import text

logger = logging.getLogger(__name__)

PERSONAL_SENTINEL = "personal"


def _display_name(bot_user: object, usso_uid: str) -> str:
    active = getattr(bot_user, "telegram_workspace_id", None)
    if not active or active == usso_uid:
        return text("labels.personal_workspace")
    return (getattr(bot_user, "known_workspaces", None) or {}).get(
        active, text("labels.team_workspace")
    )


def team_menu_message_and_keyboard(
    bot_user: object, usso_uid: str, locale: str
) -> tuple[str, kb.InlineKeyboard]:
    """Build the team-menu body text and keyboard for the current workspace."""
    active = getattr(bot_user, "telegram_workspace_id", None)
    is_personal = not active or active == usso_uid
    is_owner = bool(active) and active in (
        getattr(bot_user, "owned_workspace_ids", None) or []
    )
    message = text(
        "messages.team_menu",
        locale=locale,
        name=_display_name(bot_user, usso_uid),
    )
    keyboard = kb.team_menu_keyboard(is_personal=is_personal, is_owner=is_owner)
    return message, keyboard


async def send_team_menu(
    ctx: BotRuntimeContext,
    chat_id: int | str,
    locale: str,
    bot_user: object,
    usso_uid: str,
    *,
    reply_to: int | str | None = None,
) -> None:
    """Send the team menu as a new message (e.g. from /team or the reply menu)."""
    message, keyboard = team_menu_message_and_keyboard(bot_user, usso_uid, locale)
    await ctx.renderer.send_inline_text(chat_id, message, keyboard, reply_to=reply_to)


async def _send_menu(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    message, keyboard = team_menu_message_and_keyboard(bot_user, usso_uid, locale)
    await ctx.renderer.edit_message(
        event.chat_id,
        event.message_id,
        message,
        inline_keyboard=keyboard,
    )


async def _handle_create(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    first_name = event.sender.first_name if event.sender else None
    name = (
        text("labels.default_team_name", locale=locale, name=first_name)
        if first_name
        else text("labels.default_team_name_fallback", locale=locale)
    )
    try:
        workspace = await team_invites.create_team_workspace(
            name=name, owner_usso_uid=usso_uid
        )
    except Exception:
        logger.exception("Failed to create team workspace for %s", usso_uid)
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_create_error", locale=locale)
        )
        return

    workspace_id = workspace["uid"]
    bot_user.owned_workspace_ids = [
        *(bot_user.owned_workspace_ids or []),
        workspace_id,
    ]
    bot_user.known_workspaces = {
        **(bot_user.known_workspaces or {}),
        workspace_id: name,
    }
    bot_user.telegram_workspace_id = workspace_id
    await bot_user.save()
    await ctx.renderer.send_text(
        event.chat_id, text("messages.team_created", locale=locale, name=name)
    )


async def _handle_invite(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    active = getattr(bot_user, "telegram_workspace_id", None)
    if not active or active not in (bot_user.owned_workspace_ids or []):
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_invite_not_owner", locale=locale)
        )
        return
    name = (bot_user.known_workspaces or {}).get(active, text("labels.team_workspace"))
    token = await team_invites.create_invite(
        workspace_id=active,
        workspace_name=name,
        role="member",
        invited_by_usso_uid=usso_uid,
    )
    link = f"{bot_return_url(ctx)}?start=join_{token}"
    await ctx.renderer.send_text(
        event.chat_id,
        text(
            "messages.team_invite_link",
            locale=locale,
            name=name,
            link=link,
            days=team_invites.INVITE_TTL_DAYS,
        ),
    )


async def _handle_members(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    active = getattr(bot_user, "telegram_workspace_id", None)
    if not active or active == usso_uid:
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_members_none", locale=locale)
        )
        return
    try:
        async with usso_accounts_client() as client:
            members = await client.list_workspace_members(active)
    except Exception:
        logger.exception("Failed to list members for workspace %s", active)
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_members_error", locale=locale)
        )
        return
    lines = [
        f"• {m.get('name') or m.get('uid')} ({', '.join(m.get('roles') or [])})"
        for m in members
    ]
    body = "\n".join(lines) if lines else text("messages.team_members_none")
    await ctx.renderer.send_text(
        event.chat_id, text("messages.team_members_list", locale=locale, list=body)
    )


async def _handle_switch_to_personal(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    bot_user.telegram_workspace_id = usso_uid
    await bot_user.save()
    await ctx.renderer.send_text(
        event.chat_id, text("messages.team_switched_personal", locale=locale)
    )


async def _handle_switch_to_team(
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
    target: str,
) -> None:
    messenger_id = event_user_id(event)
    identifier_type = usso_identifier_type_for_platform(event.platform)
    try:
        async with usso_accounts_client() as client:
            fresh = await client.get_user_by_identifier(
                identifier_type, messenger_id or ""
            )
    except Exception:
        logger.exception("Failed to re-verify membership for %s", usso_uid)
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_switch_error", locale=locale)
        )
        return

    if not fresh or target not in (fresh.workspace_ids or []):
        await ctx.renderer.send_text(
            event.chat_id, text("messages.team_switch_not_member", locale=locale)
        )
        return

    bot_user.telegram_workspace_id = target
    await bot_user.save()
    name = (bot_user.known_workspaces or {}).get(target, text("labels.team_workspace"))
    await ctx.renderer.send_text(
        event.chat_id, text("messages.team_switched", locale=locale, name=name)
    )


async def _handle_switch(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
    bot_user: object,
    usso_uid: str,
) -> None:
    if data == "team:switch:menu":
        await ctx.renderer.edit_message(
            event.chat_id,
            event.message_id,
            text("messages.team_switch_prompt", locale=locale),
            inline_keyboard=kb.team_switch_keyboard(
                known_workspaces=bot_user.known_workspaces or {},
                active_id=getattr(bot_user, "telegram_workspace_id", None),
                usso_uid=usso_uid,
            ),
        )
        return

    target = data.removeprefix("team:switch:")
    if target == PERSONAL_SENTINEL:
        await _handle_switch_to_personal(event, ctx, locale, bot_user, usso_uid)
        return
    await _handle_switch_to_team(event, ctx, locale, bot_user, usso_uid, target)


_SIMPLE_HANDLERS = {
    "team:create": _handle_create,
    "team:invite": _handle_invite,
    "team:members": _handle_members,
}


async def handle_team_callback(
    data: str,
    event: CallbackEvent,
    ctx: BotRuntimeContext,
    locale: str,
) -> bool:
    """Handle team:* callbacks. Returns True when handled."""
    if not data.startswith("team:"):
        return False

    verified = await require_verified_callback(event, ctx, locale)
    if not verified:
        return True
    usso_uid, bot_user = verified

    if data == "team:menu":
        await _send_menu(event, ctx, locale, bot_user, usso_uid)
        return True

    handler = _SIMPLE_HANDLERS.get(data)
    if handler:
        await handler(event, ctx, locale, bot_user, usso_uid)
        return True

    if data.startswith("team:switch:"):
        await _handle_switch(data, event, ctx, locale, bot_user, usso_uid)
        return True

    return False
