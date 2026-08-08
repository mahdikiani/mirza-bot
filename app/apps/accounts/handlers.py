"""Handlers for resolving USSO users and their profiles with caching."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aiocache import cached
from aiocache.base import BaseCache
from usso import UserData

from apps.accounts.clients import UssoAccountsClient, usso_accounts_client
from apps.accounts.schemas import Profile
from server.config import Settings

logger = logging.getLogger(__name__)

USSO_USER_CACHE_TTL = Settings.usso_user_cache_ttl_seconds


def usso_identifier_type_for_platform(platform: str) -> str:
    """Map messenger platform to USSO identifier type."""
    if platform == "bale":
        return "bale_id"
    return "telegram_id"


@asynccontextmanager
async def get_usso_client() -> AsyncGenerator[UssoAccountsClient]:
    """Yield an authenticated USSO client."""
    async with usso_accounts_client() as client:
        yield client


def _to_user_data(user_response: object) -> UserData:
    """
    Convert UserResponse to legacy UserData for compatibility.

    UserResponse (REST user record) keys its id as `uid`; UserData (JWT
    claims shape) keys it as `sub` (and exposes `.uid` as a property read
    off `sub`). Without this mapping, `sub` is left unset and every caller
    of `get_existing_usso_user`/`get_usso_user` silently gets an empty
    `.uid` back instead of the real user id.

    Also derives workspace_id from workspace_ids: a user's personal
    workspace is always created with uid == user.uid (USSO auto-provisions
    it on user creation), so its presence in workspace_ids -- already
    returned by this same lookup -- is enough to know it exists. This
    needs no extra call and no impersonation; a user with no personal
    workspace yet (e.g. created before it existed) just falls back to
    personal billing, same as today.
    """
    if isinstance(user_response, UserData):
        return user_response
    data = (
        user_response.model_dump()
        if hasattr(user_response, "model_dump")
        else dict(user_response)
    )
    data.setdefault("sub", data.get("uid"))
    uid = data.get("uid")
    if uid and uid in (data.get("workspace_ids") or []):
        data.setdefault("workspace_id", uid)
    return UserData(**data)


def _usso_cache_key(
    _fn: object,
    credentials: dict,
    **_kwargs: object,
) -> str:
    return f"mirza:usso:{credentials['identifier_type']}:{credentials['identifier']}"


@cached(ttl=USSO_USER_CACHE_TTL, key_builder=_usso_cache_key)
async def get_usso_user(credentials: dict) -> UserData:
    """Resolve a USSO user by identifier, creating it if missing."""
    async with get_usso_client() as client:
        user = await client.get_or_create_user_by_identifier(
            credentials["identifier_type"],
            credentials["identifier"],
        )
        return _to_user_data(user)


@cached(ttl=USSO_USER_CACHE_TTL, key_builder=_usso_cache_key)
async def get_existing_usso_user(credentials: dict) -> UserData | None:
    """Resolve a USSO user by identifier without creating it."""
    async with get_usso_client() as client:
        user = await client.get_user_by_identifier(
            credentials["identifier_type"],
            credentials["identifier"],
        )
        return _to_user_data(user) if user else None


async def get_personal_workspace_id(
    user_id: str, tenant_id: str | None = None
) -> str | None:
    """Resolve the real personal workspace through the service account."""
    async with get_usso_client() as client:
        workspace = await client.get_personal_workspace(
            user_id=user_id,
            tenant_id=tenant_id,
        )
    return str(workspace["uid"]) if workspace and workspace.get("uid") else None


@cached(ttl=USSO_USER_CACHE_TTL)
async def get_user_profile(user_id: str, **kwargs: object) -> Profile:
    """Return a cached user profile from USSO."""
    async with get_usso_client() as client:
        return await client.get_profile(user_id)


async def invalidate_usso_user_cache(credentials: dict) -> None:
    """Drop cached USSO lookups for an identifier after onboarding/link."""
    key = _usso_cache_key(None, credentials)
    for fn in (get_existing_usso_user, get_usso_user):
        cache: BaseCache | None = getattr(fn, "cache", None)
        if cache is None:
            continue
        try:
            await cache.delete(key)
        except Exception:
            logger.exception("Failed to invalidate USSO cache for %s", key)
