"""Verified-user resolution: USSO as source of truth with TTL cache."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

from apps.accounts.handlers import (
    get_existing_usso_user,
    usso_identifier_type_for_platform,
)
from apps.bots.common import models
from apps.bots.common.events import CallbackEvent, MessageEvent
from apps.bots.common.onboarding import get_bot_user

logger = logging.getLogger(__name__)


class VerifiedUserStatus(StrEnum):
    """Outcome of resolving a messenger user for bot access."""

    ok = "ok"
    needs_contact = "needs_contact"
    no_platform_user = "no_platform_user"


@dataclass(frozen=True)
class VerifiedUser:
    """Resolved bot user ready for privileged flows."""

    usso_uid: str
    bot_user: models.BotUser
    from_cache: bool = False
    usso_revalidate_pending: bool = False


def platform_user_id(event: MessageEvent | CallbackEvent) -> str | None:
    """Messenger-scoped user id from a normalized event."""
    if event.sender:
        return str(event.sender.id)
    value = event.metadata.get("user_id") or event.metadata.get("telegram_user_id")
    return str(value) if value else None


async def resolve_verified_user(
    event: MessageEvent | CallbackEvent,
) -> tuple[VerifiedUserStatus, VerifiedUser | None]:
    """
    Resolve a verified user for bot flows.

    USSO is the source of truth; lookups are cached (see accounts.handlers).
    On USSO outage, allow users with a previously synced local profile.
    """
    messenger_id = platform_user_id(event)
    if not messenger_id:
        return VerifiedUserStatus.no_platform_user, None

    bot_user = await get_bot_user(messenger_id)
    if not bot_user or not bot_user.phone_verified:
        return VerifiedUserStatus.needs_contact, None

    identifier_type = usso_identifier_type_for_platform(event.platform)
    credentials = {"identifier_type": identifier_type, "identifier": messenger_id}

    usso_user = None
    usso_unavailable = False
    try:
        usso_user = await get_existing_usso_user(credentials)
    except Exception:
        usso_unavailable = True
        logger.exception(
            "USSO lookup failed for %s=%s; using last-known local state if any",
            identifier_type,
            messenger_id,
        )

    if usso_user is not None:
        usso_uid = str(usso_user.uid)
        if bot_user.usso_user_id != usso_uid or not bot_user.usso_synced:
            bot_user.usso_user_id = usso_uid
            bot_user.usso_synced = True
            await bot_user.save()
        return VerifiedUserStatus.ok, VerifiedUser(
            usso_uid=usso_uid,
            bot_user=bot_user,
            from_cache=True,
            usso_revalidate_pending=False,
        )

    if usso_unavailable:
        if bot_user.usso_user_id:
            return VerifiedUserStatus.ok, VerifiedUser(
                usso_uid=bot_user.usso_user_id,
                bot_user=bot_user,
                from_cache=True,
                usso_revalidate_pending=True,
            )
        return VerifiedUserStatus.needs_contact, None

    if bot_user.usso_synced and bot_user.usso_user_id:
        return VerifiedUserStatus.needs_contact, None

    if bot_user.usso_user_id:
        return VerifiedUserStatus.ok, VerifiedUser(
            usso_uid=bot_user.usso_user_id,
            bot_user=bot_user,
            from_cache=False,
            usso_revalidate_pending=True,
        )

    return VerifiedUserStatus.needs_contact, None


async def require_verified_user_for_start(
    event: MessageEvent,
) -> tuple[VerifiedUserStatus, VerifiedUser | None]:
    """Same as resolve_verified_user; used for /start menu vs contact prompt."""
    return await resolve_verified_user(event)
