"""USSO client wrappers using the official ``usso`` package."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from usso.client import AsyncUssoClient as OfficialAsyncUssoClient
from usso.schemas import UserResponse

from apps.accounts.schemas import Profile
from server.config import Settings


class UssoAccountsClient:
    """Thin composition over the official USSO async client."""

    def __init__(self, client: OfficialAsyncUssoClient) -> None:
        """Wrap the official USSO async client."""
        self._client = client

    async def get_user_by_identifier(
        self,
        identifier_type: str,
        identifier: str,
    ) -> UserResponse | None:
        """Look up a user by identifier without creating one."""
        users = await self._client.get_users({
            "identifier_type": identifier_type,
            "identifier": identifier,
        })
        return users[0] if users else None

    async def get_or_create_user_by_identifier(
        self,
        identifier_type: str,
        identifier: str,
    ) -> UserResponse:
        """Look up or create a user by identifier."""
        existing = await self.get_user_by_identifier(identifier_type, identifier)
        if existing:
            return existing
        return await self._client.create_users({
            "identifier_type": identifier_type,
            "identifier": identifier,
        })

    async def link_identifier(
        self,
        user_uid: str,
        identifier_type: str,
        identifier: str,
    ) -> None:
        """Attach an additional identifier (e.g. phone) to a user."""
        resp = await self._client.post(
            f"/api/sso/v1/users/{user_uid}/identifiers",
            json={"type": identifier_type, "identifier": identifier},
        )
        resp.raise_for_status()

    async def get_profile(self, user_id: str) -> Profile:
        """Return a user profile from USSO."""
        resp = await self._client.get(f"/api/sso/v1/profiles/{user_id}", timeout=20)
        resp.raise_for_status()
        return Profile(**resp.json())

    async def patch_profile(self, user_id: str, data: dict) -> Profile:
        """Update a user profile."""
        resp = await self._client.patch(
            f"/api/sso/v1/profiles/{user_id}",
            json=data,
            timeout=20,
        )
        resp.raise_for_status()
        return Profile(**resp.json())


@asynccontextmanager
async def usso_accounts_client() -> AsyncGenerator[UssoAccountsClient]:
    """Yield a USSO accounts client authenticated with the configured API key."""
    async with OfficialAsyncUssoClient(
        api_key=Settings.usso_api_key,
        usso_base_url=Settings.usso_base_url,
        timeout=20,
    ) as client:
        yield UssoAccountsClient(client)
