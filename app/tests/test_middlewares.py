"""Unit tests for UserMiddleware.pre_process_callback_query.

Validates: Requirements 18.1, 18.2, 18.3
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.middlewares import UserMiddleware


def _make_bot_mock() -> MagicMock:
    bot = MagicMock()
    bot.bot_type = "telegram"
    return bot


def _make_from_user(user_id: int = 12345) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _make_user(uid: str = "aaaa-bbbb-cccc") -> SimpleNamespace:
    return SimpleNamespace(uid=uid)


def _make_profile() -> SimpleNamespace:
    return SimpleNamespace(
        profile_data=SimpleNamespace(
            engine_config=SimpleNamespace(model="openai/gpt-4o-mini")
        )
    )


def _make_callback_query(
    *,
    from_user: SimpleNamespace | None = None,
    message: object | None = "SENTINEL",
) -> SimpleNamespace:
    if message == "SENTINEL":
        message = SimpleNamespace(user=None, profile=None)
    return SimpleNamespace(
        from_user=from_user or _make_from_user(),
        message=message,
        user=None,
        profile=None,
    )


@pytest.mark.asyncio
async def test_user_resolved_from_call_from_user() -> None:
    """Req 18.1: User is resolved from call.from_user, not call.message.from_user."""
    fake_user = _make_user(uid="user-from-call")
    fake_profile = _make_profile()
    call = _make_callback_query(from_user=_make_from_user(user_id=99999))

    mw = UserMiddleware(bot=_make_bot_mock())

    with (
        patch(
            "apps.bots.middlewares.get_usso_user",
            new_callable=AsyncMock,
            return_value=fake_user,
        ) as mock_get_user,
        patch(
            "apps.bots.middlewares.get_user_profile",
            new_callable=AsyncMock,
            return_value=fake_profile,
        ),
    ):
        await mw.pre_process_callback_query(call, {})

    mock_get_user.assert_awaited_once()
    creds = mock_get_user.call_args[0][0]
    assert creds["identifier"] == "99999"
    assert creds["identifier_type"] == "telegram_id"
    assert call.user is fake_user
    assert call.profile is fake_profile


@pytest.mark.asyncio
async def test_call_message_none_does_not_raise() -> None:
    """Req 18.2: call.message = None does not raise AttributeError."""
    fake_user = _make_user()
    call = _make_callback_query(message=None)

    mw = UserMiddleware(bot=_make_bot_mock())

    with (
        patch(
            "apps.bots.middlewares.get_usso_user",
            new_callable=AsyncMock,
            return_value=fake_user,
        ),
        patch(
            "apps.bots.middlewares.get_user_profile",
            new_callable=AsyncMock,
            return_value=_make_profile(),
        ),
    ):
        await mw.pre_process_callback_query(call, {})

    assert call.user is fake_user
    assert call.message is None  # still None, no crash


@pytest.mark.asyncio
async def test_user_and_profile_propagated_to_message() -> None:
    """Req 18.3: user and profile are propagated to call.message when it exists."""
    fake_user = _make_user(uid="propagated-uid")
    fake_profile = _make_profile()
    msg = SimpleNamespace(user=None, profile=None)
    call = _make_callback_query(from_user=_make_from_user(), message=msg)

    mw = UserMiddleware(bot=_make_bot_mock())

    with (
        patch(
            "apps.bots.middlewares.get_usso_user",
            new_callable=AsyncMock,
            return_value=fake_user,
        ),
        patch(
            "apps.bots.middlewares.get_user_profile",
            new_callable=AsyncMock,
            return_value=fake_profile,
        ),
    ):
        await mw.pre_process_callback_query(call, {})

    assert call.user is fake_user
    assert call.profile is fake_profile
    assert msg.user is fake_user
    assert msg.profile is fake_profile


@pytest.mark.asyncio
async def test_usso_failure_sets_user_none() -> None:
    """When get_usso_user raises, user is set to None and no crash occurs."""
    call = _make_callback_query(message=None)
    mw = UserMiddleware(bot=_make_bot_mock())

    with patch(
        "apps.bots.middlewares.get_usso_user",
        new_callable=AsyncMock,
        side_effect=Exception("USSO down"),
    ):
        await mw.pre_process_callback_query(call, {})

    assert call.user is None
    assert call.profile is None


@pytest.mark.asyncio
async def test_profile_failure_sets_profile_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When get_user_profile raises, profile is None but user is still set."""
    fake_user = _make_user(uid="profile-fail-uid")
    call = _make_callback_query()
    mw = UserMiddleware(bot=_make_bot_mock())

    with (
        patch(
            "apps.bots.middlewares.get_usso_user",
            new_callable=AsyncMock,
            return_value=fake_user,
        ),
        patch(
            "apps.bots.middlewares.get_user_profile",
            new_callable=AsyncMock,
            side_effect=Exception("Profile service down"),
        ),
        caplog.at_level(logging.ERROR),
    ):
        await mw.pre_process_callback_query(call, {})

    assert call.user is fake_user
    assert call.profile is None
