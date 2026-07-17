"""Onboarding: contact verification and USSO user provisioning."""

from __future__ import annotations

import logging

from apps.accounts.clients import usso_accounts_client
from apps.bots.common import models
from apps.bots.common.events import MessageEvent
from utils.i18n import text
from utils.texttools import is_phone, normalize_phone

logger = logging.getLogger(__name__)

SUPPORTED_LOCALES = {"fa", "en"}


def detect_locale(language_code: str | None) -> str:
    """Map Telegram language_code to a supported bot locale."""
    if not language_code:
        return "fa"
    code = language_code.lower().split("-")[0]
    return code if code in SUPPORTED_LOCALES else "fa"


async def get_bot_user(telegram_user_id: str) -> models.BotUser | None:
    """Return the local bot user record for a Telegram user id."""
    return await models.BotUser.find_one({"telegram_user_id": telegram_user_id})


async def _sync_usso_user(telegram_id: str, phone_number: str) -> str:
    """
    Best-effort sync to USSO. Returns the USSO uid, or "" if unavailable.

    First tries to find an existing USSO user by phone number (so that a user
    who already onboarded on another platform gets their Telegram linked to
    the same account). Falls back to looking up or creating by telegram_id.
    """
    try:
        async with usso_accounts_client() as usso:
            normalized_phone = normalize_phone(phone_number)
            existing = await usso.get_user_by_identifier("phone", normalized_phone)
            if existing:
                usso_uid = str(existing.uid)
                try:
                    await usso.link_identifier(usso_uid, "telegram_id", telegram_id)
                except Exception:
                    logger.exception("Failed to link telegram_id for user %s", usso_uid)
                return usso_uid

            usso_user = await usso.get_or_create_user_by_identifier(
                "telegram_id",
                telegram_id,
            )
            usso_uid = str(usso_user.uid)
            try:
                await usso.link_identifier(usso_uid, "phone", normalized_phone)
            except Exception:
                logger.exception("Failed to link phone for user %s", usso_uid)
            return usso_uid
    except Exception:
        logger.warning(
            "USSO service unavailable during onboarding for telegram_id=%s; "
            "continuing with a local-only account (will sync later).",
            telegram_id,
            exc_info=True,
        )
        return ""


async def get_or_create_bot_user_from_contact(
    event: MessageEvent,
    phone_number: str,
) -> models.BotUser:
    """
    Verify contact, sync to USSO best-effort, and persist local bot user.

    If USSO is temporarily unreachable, the bot user is still created/updated
    locally (unblocking the user) with ``usso_synced=False`` so it can be
    reconciled with USSO once the service recovers.
    """
    telegram_id = str(event.sender.id) if event.sender else ""
    locale = detect_locale(event.metadata.get("language_code"))

    usso_uid = await _sync_usso_user(telegram_id, phone_number)
    synced = bool(usso_uid)

    existing = await get_bot_user(telegram_id)
    if existing:
        existing.phone_number = phone_number
        existing.phone_verified = True
        if synced:
            existing.usso_user_id = usso_uid
            existing.usso_synced = True
        else:
            existing.usso_synced = existing.usso_synced and bool(existing.usso_user_id)
        existing.preferred_language = locale
        await existing.save()
        return existing

    bot_user = models.BotUser(
        user_id=usso_uid or telegram_id,
        telegram_user_id=telegram_id,
        usso_user_id=usso_uid,
        usso_synced=synced,
        preferred_language=locale,
        phone_verified=True,
        phone_number=phone_number,
        platform=event.platform,
    )
    await bot_user.save()
    return bot_user


def is_typed_phone_rejection(text_value: str) -> bool:
    """Return True when user typed a phone number instead of sharing contact."""
    stripped = text_value.strip()
    if not stripped:
        return False
    if stripped.startswith("/"):
        return False
    return is_phone(stripped)


def contact_user_id_matches(event: MessageEvent, contact_user_id: int | str) -> bool:
    """Verify shared contact belongs to the sender."""
    sender_id = event.sender.id if event.sender else None
    return sender_id is not None and str(contact_user_id) == str(sender_id)


def onboarding_success_message(locale: str) -> str:
    """Localized message shown after successful onboarding."""
    return text("messages.onboarding_success", locale=locale)


def contact_mismatch_message(locale: str = "fa") -> str:
    """Localized message when contact does not match sender."""
    return text("messages.contact_mismatch", locale=locale)


def typed_phone_rejection_message(locale: str = "fa") -> str:
    """Localized message when user types phone instead of sharing contact."""
    return text("messages.typed_phone_rejected", locale=locale)
