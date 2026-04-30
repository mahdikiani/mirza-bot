"""Unit tests for apps.bots.base_bot.

Covers:
- BaseBot.send_message (UnboundLocalError fix, empty text, split text)
- TelegramBot.resolve_me (getMe caching, error fallback)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telebot.asyncio_helper import ApiTelegramException

from apps.bots.base_bot import TelegramBot

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bot() -> TelegramBot:
    """Create a fresh TelegramBot instance (bypass singleton for testing)."""
    bot = object.__new__(TelegramBot)
    bot.token = "test-token"
    bot.me = "uln_ai_bot"
    bot._me_resolved = False
    bot.lock = __import__("asyncio").Lock()
    return bot


def _api_error(description: str) -> ApiTelegramException:
    return ApiTelegramException(
        "send_message",
        400,
        {"error_code": 400, "description": description},
    )


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_empty_text_returns_none() -> None:
    """Empty string: split_text returns [] so send_message returns None."""
    bot = _make_bot()
    with patch("apps.bots.base_bot.split_text", return_value=[]):
        result = await bot.send_message(123, "")
    assert result is None


@pytest.mark.asyncio
async def test_send_message_single_chunk() -> None:
    """Normal short text → sends one message and returns it."""
    bot = _make_bot()
    sent_msg = MagicMock()

    with (
        patch("apps.bots.base_bot.split_text", return_value=["Hello"]),
        patch.object(
            bot.__class__.__bases__[0],
            "send_message",
            new_callable=AsyncMock,
            return_value=sent_msg,
        ),
    ):
        result = await bot.send_message(123, "Hello")

    assert result is sent_msg


@pytest.mark.asyncio
async def test_send_message_multiple_chunks_returns_last() -> None:
    """Long text split into multiple chunks → returns last sent message."""
    bot = _make_bot()
    msg1, msg2 = MagicMock(), MagicMock()

    async def fake_super_send(  # noqa: RUF029
        chat_id: object, text: object, *args: object, **kwargs: object
    ) -> MagicMock:
        return msg1 if text == "chunk1" else msg2

    with (
        patch("apps.bots.base_bot.split_text", return_value=["chunk1", "chunk2"]),
        patch(
            "telebot.async_telebot.AsyncTeleBot.send_message",
            new=fake_super_send,
        ),
    ):
        result = await bot.send_message(123, "long text")

    assert result is msg2


@pytest.mark.asyncio
async def test_send_message_message_too_long_logs_warning() -> None:
    """MESSAGE_TOO_LONG error is caught and logged, not re-raised."""
    bot = _make_bot()
    err = _api_error("MESSAGE_TOO_LONG")

    async def fake_super_send(*args: object, **kwargs: object) -> None:  # noqa: RUF029
        raise err

    with (
        patch("apps.bots.base_bot.split_text", return_value=["text"]),
        patch("telebot.async_telebot.AsyncTeleBot.send_message", new=fake_super_send),
    ):
        result = await bot.send_message(123, "text")

    assert result is None


# ---------------------------------------------------------------------------
# TelegramBot.resolve_me
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_me_sets_username() -> None:
    """Successful getMe sets self.me to the API username."""
    bot = _make_bot()
    bot_info = MagicMock()
    bot_info.username = "new_bot_name"

    with patch.object(bot, "get_me", new_callable=AsyncMock, return_value=bot_info):
        await bot.resolve_me()

    assert bot.me == "new_bot_name"
    assert bot._me_resolved is True


@pytest.mark.asyncio
async def test_resolve_me_caches_result() -> None:
    """Second call to resolve_me does not call getMe again."""
    bot = _make_bot()
    bot_info = MagicMock()
    bot_info.username = "cached_bot"

    mock_get_me = AsyncMock(return_value=bot_info)
    with patch.object(bot, "get_me", mock_get_me):
        await bot.resolve_me()
        await bot.resolve_me()  # second call

    mock_get_me.assert_awaited_once()  # only called once


@pytest.mark.asyncio
async def test_resolve_me_keeps_fallback_on_error() -> None:
    """getMe failure keeps the hardcoded fallback name."""
    bot = _make_bot()
    original_name = bot.me

    with patch.object(
        bot, "get_me", new_callable=AsyncMock, side_effect=Exception("API down")
    ):
        await bot.resolve_me()

    assert bot.me == original_name
    assert bot._me_resolved is False


@pytest.mark.asyncio
async def test_resolve_me_no_username_keeps_fallback() -> None:
    """getMe returns bot_info with no username → fallback preserved."""
    bot = _make_bot()
    original_name = bot.me
    bot_info = MagicMock()
    bot_info.username = None

    with patch.object(bot, "get_me", new_callable=AsyncMock, return_value=bot_info):
        await bot.resolve_me()

    assert bot.me == original_name
    assert bot._me_resolved is False
