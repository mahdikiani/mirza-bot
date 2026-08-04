"""USSO client wrappers using the official ``usso`` package."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from usso.client import AsyncUssoClient as OfficialAsyncUssoClient
from usso.schemas import UserResponse

from apps.accounts.schemas import Profile
from server.config import Settings

logger = logging.getLogger(__name__)


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

    async def create_team_workspace(self, name: str) -> dict:
        """
        Create an org-style shared workspace (admin-scoped, no KYC).

        Requires the configured API key to hold ``admin:sso/workspace``;
        USSO's create_workspace() routes admin-scoped callers straight to
        create_workspace_by_admin(), skipping company-registry verification.
        Does not add anyone as a member -- follow up with add_workspace_member.
        """
        resp = await self._client.post(
            "/api/sso/v1/workspaces", json={"name": name}
        )
        resp.raise_for_status()
        return resp.json()

    async def add_workspace_member(
        self, workspace_id: str, user_id: str, role: str = "member"
    ) -> dict:
        """Add a user to a workspace with the given role."""
        resp = await self._client.post(
            f"/api/sso/v1/workspaces/{workspace_id}/members",
            json={"user_id": user_id, "role": role},
        )
        resp.raise_for_status()
        return resp.json()

    async def remove_workspace_member(self, workspace_id: str, user_id: str) -> None:
        """Remove a user from a workspace."""
        resp = await self._client.delete(
            f"/api/sso/v1/workspaces/{workspace_id}/members/{user_id}"
        )
        resp.raise_for_status()

    async def list_workspace_members(self, workspace_id: str) -> list[dict]:
        """List members of a workspace."""
        resp = await self._client.get(
            f"/api/sso/v1/workspaces/{workspace_id}/users", timeout=20
        )
        resp.raise_for_status()
        return resp.json().get("items", [])

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
