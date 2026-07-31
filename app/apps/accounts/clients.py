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

TELEGRAM_WORKSPACE_NAME = "Telegram"


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


async def ensure_telegram_workspace(usso_uid: str) -> str | None:
    """
    Ensure the given USSO user has a "Telegram" workspace; return its uid.

    Creates it if it doesn't exist yet. Every task mirza-bot submits to
    ai-toolkit on behalf of a Telegram user is authenticated with one
    shared service API key -- without an explicit workspace_id, it would
    inherit *that service account's own* workspace membership, leaking
    every Telegram user's task history into whatever workspace the
    service account happens to belong to. Each Telegram user gets their
    own dedicated workspace instead.

    Workspace creation has no "create on behalf of user_id" API -- the
    only way to create a workspace genuinely owned by a specific user is
    to impersonate them first (POST /users/{uid}/impersonate, which sets
    session cookies on the response) and act through that session. Uses
    a short-lived, single-purpose client dedicated to this one user's
    impersonation session -- never the shared, long-lived service client
    from usso_accounts_client() -- so an impersonated session can never
    leak into an unrelated request for a different user.

    Returns None (logs, doesn't raise) on any USSO failure -- workspace
    resolution must never block a user's actual request.
    """
    async with OfficialAsyncUssoClient(
        api_key=Settings.usso_api_key,
        usso_base_url=Settings.usso_base_url,
        timeout=20,
    ) as client:
        try:
            impersonate_resp = await client.post(
                f"/api/sso/v1/users/{usso_uid}/impersonate"
            )
            impersonate_resp.raise_for_status()
        except Exception:
            logger.exception(
                "Failed to impersonate user %s for workspace setup", usso_uid
            )
            return None

        try:
            mine_resp = await client.get("/api/sso/v1/workspaces/mine")
            mine_resp.raise_for_status()
            workspaces = mine_resp.json().get("items", [])
        except Exception:
            logger.exception("Failed to list workspaces for user %s", usso_uid)
            return None

        for workspace in workspaces:
            if workspace.get("name") == TELEGRAM_WORKSPACE_NAME:
                return workspace.get("uid")

        try:
            create_resp = await client.post(
                "/api/sso/v1/workspaces",
                json={"name": TELEGRAM_WORKSPACE_NAME},
            )
            create_resp.raise_for_status()
            return create_resp.json().get("uid")
        except Exception:
            logger.exception(
                "Failed to create Telegram workspace for user %s", usso_uid
            )
            return None
