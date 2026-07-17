"""Handlers for resolving USSO users and their profiles with caching."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aiocache import cached
from usso import UserData

from apps.accounts.clients import UssoAccountsClient, usso_accounts_client
from apps.accounts.schemas import Profile


@asynccontextmanager
async def get_usso_client() -> AsyncGenerator[UssoAccountsClient]:
    """Yield an authenticated USSO client."""
    async with usso_accounts_client() as client:
        yield client


def _to_user_data(user_response: object) -> UserData:
    """Convert UserResponse to legacy UserData for compatibility."""
    if isinstance(user_response, UserData):
        return user_response
    data = (
        user_response.model_dump()
        if hasattr(user_response, "model_dump")
        else dict(user_response)
    )
    return UserData(**data)


@cached(ttl=60 * 60)
async def get_usso_user(credentials: dict) -> UserData:
    """Resolve a USSO user by identifier, creating it if missing."""
    async with get_usso_client() as client:
        user = await client.get_or_create_user_by_identifier(
            credentials["identifier_type"],
            credentials["identifier"],
        )
        return _to_user_data(user)


@cached(ttl=60 * 5)
async def get_existing_usso_user(credentials: dict) -> UserData | None:
    """Resolve a USSO user by identifier without creating it."""
    async with get_usso_client() as client:
        user = await client.get_user_by_identifier(
            credentials["identifier_type"],
            credentials["identifier"],
        )
        return _to_user_data(user) if user else None


@cached(ttl=60 * 5)
async def get_user_profile(user_id: str, **kwargs: object) -> Profile:
    """Return a cached user profile from USSO."""
    async with get_usso_client() as client:
        return await client.get_profile(user_id)
