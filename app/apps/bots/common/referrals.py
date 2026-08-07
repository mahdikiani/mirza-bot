"""Personal-referral and admin gift-code deep-link helpers."""

from __future__ import annotations

import logging

from server.db import get_redis

logger = logging.getLogger(__name__)

_PENDING_TTL_SECONDS = 900
_REFERRAL_KEY_PREFIX = "referral_pending:"
_GIFT_KEY_PREFIX = "gift_pending:"


def _pending_referral_key(platform: str, messenger_id: str) -> str:
    return f"{_REFERRAL_KEY_PREFIX}{platform}:{messenger_id}"


def _pending_gift_key(platform: str, messenger_id: str) -> str:
    return f"{_GIFT_KEY_PREFIX}{platform}:{messenger_id}"


def parse_start_payload(text_value: str) -> str | None:
    """Extract a referral code from a ``/start ref_<code>`` command."""
    parts = text_value.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("ref_"):
        return None
    return payload.removeprefix("ref_") or None


def parse_gift_payload(text_value: str) -> str | None:
    """Extract a gift code from a ``/start gift_<code>`` command."""
    parts = text_value.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("gift_"):
        return None
    return payload.removeprefix("gift_") or None


async def stash_pending_referral(
    platform: str, messenger_id: str, code: str
) -> None:
    """Remember a referral code across phone verification."""
    redis = get_redis()
    if redis is None:
        logger.warning(
            "Redis unavailable; referral code will be lost if %s needs onboarding",
            messenger_id,
        )
        return
    await redis.set(
        _pending_referral_key(platform, messenger_id),
        code,
        ex=_PENDING_TTL_SECONDS,
    )


async def pop_pending_referral(platform: str, messenger_id: str) -> str | None:
    """Retrieve and clear a stashed referral code, if any."""
    redis = get_redis()
    if redis is None:
        return None
    key = _pending_referral_key(platform, messenger_id)
    code = await redis.get(key)
    if code:
        await redis.delete(key)
    return code


async def stash_pending_gift(platform: str, messenger_id: str, code: str) -> None:
    """Remember a gift code across phone verification."""
    redis = get_redis()
    if redis is None:
        logger.warning(
            "Redis unavailable; gift code will be lost if %s needs onboarding",
            messenger_id,
        )
        return
    await redis.set(
        _pending_gift_key(platform, messenger_id),
        code,
        ex=_PENDING_TTL_SECONDS,
    )


async def pop_pending_gift(platform: str, messenger_id: str) -> str | None:
    """Retrieve and clear a stashed gift code, if any."""
    redis = get_redis()
    if redis is None:
        return None
    key = _pending_gift_key(platform, messenger_id)
    code = await redis.get(key)
    if code:
        await redis.delete(key)
    return code
