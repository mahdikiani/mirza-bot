"""Identity resolution: USSO SoT + TTL cache + outage fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common.auth_gate import VerifiedUserStatus, resolve_verified_user
from apps.bots.common.events import MessageEvent, Sender
from apps.bots.common.models import BotUser


def _event(user_id: str = "123") -> MessageEvent:
    return MessageEvent(
        platform="telegram",
        chat_id=1,
        message_id=1,
        text="hi",
        sender=Sender(id=user_id),
    )


def _bot_user(**kwargs: object) -> BotUser:
    defaults: dict[str, object] = {
        "user_id": "usso-1",
        "telegram_user_id": "123",
        "usso_user_id": "usso-1",
        "usso_synced": True,
        "phone_verified": True,
    }
    defaults.update(kwargs)
    return BotUser(**defaults)


@pytest.mark.asyncio
async def test_resolve_needs_contact_when_no_local_user() -> None:
    with patch(
        "apps.bots.common.auth_gate.get_bot_user",
        AsyncMock(return_value=None),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.needs_contact
    assert verified is None


@pytest.mark.asyncio
async def test_resolve_ok_when_usso_returns_user() -> None:
    bot_user = _bot_user()
    usso = SimpleNamespace(uid="usso-1")
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(return_value=usso),
        ),
        patch(
            "apps.bots.common.auth_gate.ensure_telegram_workspace",
            AsyncMock(return_value="ws-1"),
        ) as mock_ensure_workspace,
        patch.object(BotUser, "save", AsyncMock()),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.ok
    assert verified is not None
    assert verified.usso_uid == "usso-1"
    mock_ensure_workspace.assert_awaited_once_with("usso-1")
    assert bot_user.telegram_workspace_id == "ws-1"


@pytest.mark.asyncio
async def test_resolve_skips_workspace_ensure_when_already_cached() -> None:
    """
    Test that a cached workspace_id skips the impersonation round-trip.

    A user who already has telegram_workspace_id set costs no extra
    impersonation round-trip on later calls.
    """
    bot_user = _bot_user(telegram_workspace_id="ws-cached")
    usso = SimpleNamespace(uid="usso-1")
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(return_value=usso),
        ),
        patch(
            "apps.bots.common.auth_gate.ensure_telegram_workspace",
            AsyncMock(),
        ) as mock_ensure_workspace,
        patch.object(BotUser, "save", AsyncMock()) as mock_save,
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.ok
    assert verified is not None
    mock_ensure_workspace.assert_not_awaited()
    mock_save.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_workspace_ensure_failure_does_not_block_login() -> None:
    """A failed/None workspace resolution must not fail the whole request."""
    bot_user = _bot_user()
    usso = SimpleNamespace(uid="usso-1")
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(return_value=usso),
        ),
        patch(
            "apps.bots.common.auth_gate.ensure_telegram_workspace",
            AsyncMock(return_value=None),
        ),
        patch.object(BotUser, "save", AsyncMock()),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.ok
    assert verified is not None
    assert bot_user.telegram_workspace_id is None


@pytest.mark.asyncio
async def test_resolve_outage_allows_last_known() -> None:
    bot_user = _bot_user(usso_synced=False)
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(side_effect=RuntimeError("usso down")),
        ),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.ok
    assert verified is not None
    assert verified.usso_revalidate_pending is True


@pytest.mark.asyncio
async def test_resolve_outage_without_last_known_needs_contact() -> None:
    bot_user = _bot_user(usso_user_id="", usso_synced=False)
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(side_effect=RuntimeError("usso down")),
        ),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.needs_contact
    assert verified is None


@pytest.mark.asyncio
async def test_resolve_usso_not_found_for_synced_user_needs_contact() -> None:
    bot_user = _bot_user(usso_synced=True)
    with (
        patch(
            "apps.bots.common.auth_gate.get_bot_user",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.auth_gate.get_existing_usso_user",
            AsyncMock(return_value=None),
        ),
    ):
        status, verified = await resolve_verified_user(_event())
    assert status == VerifiedUserStatus.needs_contact
    assert verified is None
