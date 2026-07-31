"""Unit tests for apps.accounts.clients.ensure_telegram_workspace."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.accounts.clients import TELEGRAM_WORKSPACE_NAME, ensure_telegram_workspace


def _response(payload: object, *, raises: bool = False) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    if raises:
        resp.raise_for_status.side_effect = RuntimeError("http error")
    else:
        resp.raise_for_status.return_value = None
    return resp


@asynccontextmanager
async def _client_ctx(client: AsyncMock) -> AsyncGenerator[AsyncMock]:
    yield client


@pytest.mark.asyncio
async def test_reuses_existing_telegram_workspace() -> None:
    """An existing "Telegram" workspace is reused, not recreated."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "user-1"}))
    client.get = AsyncMock(
        return_value=_response({
            "items": [
                {"uid": "ws-other", "name": "Other"},
                {"uid": "ws-telegram", "name": TELEGRAM_WORKSPACE_NAME},
            ]
        })
    )

    with patch(
        "apps.accounts.clients.OfficialAsyncUssoClient",
        return_value=_client_ctx(client),
    ):
        workspace_id = await ensure_telegram_workspace("user-1")

    assert workspace_id == "ws-telegram"
    client.post.assert_awaited_once_with("/api/sso/v1/users/user-1/impersonate")
    client.get.assert_awaited_once_with("/api/sso/v1/workspaces/mine")


@pytest.mark.asyncio
async def test_creates_telegram_workspace_when_missing() -> None:
    """No existing "Telegram" workspace -> one is created."""
    client = AsyncMock()
    client.post = AsyncMock(
        side_effect=[
            _response({"uid": "user-1"}),  # impersonate
            _response({"uid": "ws-new", "name": TELEGRAM_WORKSPACE_NAME}),  # create
        ]
    )
    client.get = AsyncMock(return_value=_response({"items": []}))

    with patch(
        "apps.accounts.clients.OfficialAsyncUssoClient",
        return_value=_client_ctx(client),
    ):
        workspace_id = await ensure_telegram_workspace("user-1")

    assert workspace_id == "ws-new"
    assert client.post.await_count == 2
    client.post.assert_awaited_with(
        "/api/sso/v1/workspaces",
        json={"name": TELEGRAM_WORKSPACE_NAME},
    )


@pytest.mark.asyncio
async def test_returns_none_when_impersonation_fails() -> None:
    """Impersonation failure is logged, never raised -- must not block login."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({}, raises=True))
    client.get = AsyncMock()

    with patch(
        "apps.accounts.clients.OfficialAsyncUssoClient",
        return_value=_client_ctx(client),
    ):
        workspace_id = await ensure_telegram_workspace("user-1")

    assert workspace_id is None
    client.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_returns_none_when_listing_workspaces_fails() -> None:
    """A failure listing workspaces is logged, never raised."""
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "user-1"}))
    client.get = AsyncMock(return_value=_response({}, raises=True))

    with patch(
        "apps.accounts.clients.OfficialAsyncUssoClient",
        return_value=_client_ctx(client),
    ):
        workspace_id = await ensure_telegram_workspace("user-1")

    assert workspace_id is None


@pytest.mark.asyncio
async def test_returns_none_when_creation_fails() -> None:
    """A failure creating the workspace is logged, never raised."""
    client = AsyncMock()
    client.post = AsyncMock(
        side_effect=[
            _response({"uid": "user-1"}),
            _response({}, raises=True),
        ]
    )
    client.get = AsyncMock(return_value=_response({"items": []}))

    with patch(
        "apps.accounts.clients.OfficialAsyncUssoClient",
        return_value=_client_ctx(client),
    ):
        workspace_id = await ensure_telegram_workspace("user-1")

    assert workspace_id is None
