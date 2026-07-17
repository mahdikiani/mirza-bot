"""Tests for BaleBot helpers, Telegram config, and runtime registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telebot.asyncio_helper import ApiTelegramException

from apps.bots.bale.bot import BaleBot, BaleToken, raw_bale_token
from apps.bots.runtime import registry
from apps.bots.telegram.bot import TelegramBot


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    registry.clear()
    yield
    registry.clear()


def test_raw_bale_token_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BALE_BOT_TOKEN", "  tok  ")
    assert raw_bale_token() == "tok"


def test_bale_token_len_always_51() -> None:
    assert len(BaleToken("short")) == 51


def test_bale_bot_unconfigured_skips_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BALE_BOT_TOKEN", raising=False)
    # Bypass singleton so we get a fresh instance
    BaleBot._instances = {}  # type: ignore[attr-defined]
    bot = BaleBot.__new__(BaleBot)
    BaleBot.__init__(bot, token="")
    assert bot.token == ""
    assert bot._client_ready is False
    assert bot.bot_type == "bale"
    assert bot.needs_polling is True
    assert "ble.ir" in bot.link


@pytest.mark.asyncio
async def test_bale_send_message_splits_and_sends() -> None:
    bot = BaleBot.__new__(BaleBot)
    bot.token = "x" * 51
    bot.me = "bale"
    bot._client_ready = True
    with (
        patch("apps.bots.bale.bot.split_text", return_value=["a", "b"]),
        patch.object(
            BaleBot.__mro__[1], "send_message", new_callable=AsyncMock
        ) as super_send,
    ):
        super_send.return_value = "ok"
        result = await BaleBot.send_message(bot, 1, "hello")
    assert result == "ok"
    assert super_send.await_count == 2


@pytest.mark.asyncio
async def test_bale_send_message_retries_on_parse_error() -> None:
    bot = BaleBot.__new__(BaleBot)
    bot.token = "x" * 51
    bot.me = "bale"
    calls: list[dict] = []

    async def fake_super(self, chat_id, text, *args, **kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise ApiTelegramException(
                "sendMessage",
                None,
                {"error_code": 400, "description": "can't parse entities"},
            )
        return "ok"

    from telebot.async_telebot import AsyncTeleBot

    with (
        patch("apps.bots.bale.bot.split_text", return_value=["chunk"]),
        patch.object(AsyncTeleBot, "send_message", fake_super),
    ):
        await bot.send_message(1, "bad *md")
    assert len(calls) == 2
    assert calls[1].get("parse_mode") == ""


@pytest.mark.asyncio
async def test_bale_edit_message_ignores_not_modified() -> None:
    bot = BaleBot.__new__(BaleBot)
    bot.token = "x" * 51
    bot.me = "bale"

    async def fake_super(self, *, text=None, **kwargs):
        raise ApiTelegramException(
            "editMessageText",
            None,
            {"error_code": 400, "description": "message is not modified: ok"},
        )

    from telebot.async_telebot import AsyncTeleBot

    with patch.object(AsyncTeleBot, "edit_message_text", fake_super):
        await bot.edit_message_text("same", chat_id=1, message_id=2)


@pytest.mark.asyncio
async def test_bale_resolve_me_sets_username() -> None:
    bot = BaleBot.__new__(BaleBot)
    bot.token = "x" * 51
    bot.me = "old"
    bot.webhook_route = "old"
    bot._me_resolved = False
    bot._client_ready = True
    bot.get_me = AsyncMock(return_value=MagicMock(username="new_bale"))

    await bot.resolve_me()
    assert bot.me == "new_bale"
    assert bot.webhook_route == "new_bale"
    assert bot._me_resolved is True


def test_telegram_bot_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "tg-token")
    TelegramBot._instances = {}  # type: ignore[attr-defined]
    bot = TelegramBot()
    assert bot.bot_type == "telegram"
    assert "t.me" in bot.link
    assert TelegramBot.is_configured() is True


def test_registry_register_and_lookup() -> None:
    bot = MagicMock()
    bot.me = "mybot"
    bot.webhook_route = "route1"
    registry.register(bot)
    assert registry.get_by_name("mybot") is bot
    assert registry.get_by_route("route1") is bot
    assert registry.all_bots() == [bot]


def test_registry_requires_me() -> None:
    with pytest.raises(ValueError, match=r"bot.me"):
        registry.register(MagicMock(me=""))
