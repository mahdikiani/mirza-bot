"""Settings and language preference management."""

from __future__ import annotations

import logging

from apps.accounts.clients import usso_accounts_client
from apps.bots.common import models
from apps.bots.common.onboarding import SUPPORTED_LOCALES

logger = logging.getLogger(__name__)


async def set_preferred_language(
    telegram_user_id: str,
    locale: str,
) -> models.BotUser | None:
    """Persist language preference locally and sync to USSO profile."""
    if locale not in SUPPORTED_LOCALES:
        locale = "fa"

    bot_user = await models.BotUser.find_one({"telegram_user_id": telegram_user_id})
    if not bot_user:
        return None

    bot_user.preferred_language = locale
    await bot_user.save()

    if bot_user.usso_user_id:
        try:
            async with usso_accounts_client() as usso:
                await usso.patch_profile(
                    bot_user.usso_user_id,
                    {"profile_data": {"engine_config": {"language": locale}}},
                )
        except Exception:
            logger.exception("Failed to sync language preference to USSO")

    return bot_user


LANGUAGES: list[dict[str, str]] = [
    {"code": "fa", "label": "🇮🇷 فارسی"},
    {"code": "en", "label": "🇬🇧 English"},
]

AVAILABLE_MODELS = [
    "openai/gpt-5.6-sol",
    "openai/gpt-5.6-terra",
    "openai/gpt-5.6-luna",
    "google/gemini-3.5-flash",
    "google/gemini-2.5-pro-preview-05-06",
    "google/gemini-2.5-flash-lite",
    "anthropic/claude-sonnet-5",
    "anthropic/claude-opus-4.8-fast",
    "deepseek/deepseek-v4-pro",
    "deepseek/deepseek-v4-flash",
]

DEFAULT_MODEL = "openai/gpt-5.6-terra"


async def set_preferred_model(
    telegram_user_id: str,
    model: str,
) -> models.BotUser | None:
    """Persist model preference locally and sync to USSO profile."""
    bot_user = await models.BotUser.find_one({"telegram_user_id": telegram_user_id})
    if not bot_user:
        return None

    bot_user.preferred_model = model
    await bot_user.save()

    if bot_user.usso_user_id:
        try:
            async with usso_accounts_client() as usso:
                await usso.patch_profile(
                    bot_user.usso_user_id,
                    {"profile_data": {"engine_config": {"model": model}}},
                )
        except Exception:
            logger.exception("Failed to sync model preference to USSO")

    return bot_user


async def get_user_locale(telegram_user_id: str) -> str:
    """Return preferred locale for a Telegram user."""
    bot_user = await models.BotUser.find_one({"telegram_user_id": telegram_user_id})
    if bot_user and bot_user.preferred_language:
        return bot_user.preferred_language
    return "fa"


async def get_user_model(telegram_user_id: str) -> str:
    """Return preferred model for a Telegram user."""
    bot_user = await models.BotUser.find_one({"telegram_user_id": telegram_user_id})
    if bot_user and bot_user.preferred_model:
        return bot_user.preferred_model
    return DEFAULT_MODEL
