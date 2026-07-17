from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.runtime import registry
from apps.bots.runtime.handlers import (
    BotHandler,
    app_version,
    get_bot,
    get_bot_by_route,
)
from apps.bots.telegram.gateway import TelethonEventRenderer, TelethonGateway
from server.config import Settings


class FakeTelegramBot:
    bot_type = "telegram"
    token = "telegram-token"
    me = "telegram_bot"
    webhook_route = "telegram_route"


class FakeBaleBot:
    bot_type = "bale"
    token = "x" * 51
    me = "bale_bot"
    webhook_route = "bale_route"


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    registry.clear()
    yield
    registry.clear()


def test_app_version_from_installed_metadata() -> None:
    with patch("apps.bots.runtime.handlers.version", return_value="9.9.9"):
        assert app_version() == "9.9.9"


def test_app_version_falls_back_to_pyproject() -> None:
    with patch(
        "apps.bots.runtime.handlers.version",
        side_effect=PackageNotFoundError,
    ):
        assert app_version() == "0.1.3"


def test_get_bot_returns_matching_bot() -> None:
    registry.register(FakeTelegramBot())
    bot = get_bot("telegram_bot")
    assert bot.me == "telegram_bot"


def test_get_bot_raises_for_unknown_bot() -> None:
    with pytest.raises(ValueError, match="bot not found"):
        get_bot("missing")


def test_get_bot_by_route_returns_matching_bot() -> None:
    registry.register(FakeBaleBot())
    bot = get_bot_by_route("bale_route")
    assert bot.me == "bale_bot"


def test_get_bot_by_route_raises_for_unknown_route() -> None:
    with pytest.raises(ValueError, match="bot not found"):
        get_bot_by_route("missing")


@pytest.mark.asyncio
async def test_bot_handler_uses_telethon_for_telegram() -> None:
    handler = BotHandler()
    handler.is_setup = False
    handler._runtime_tasks = []

    with (
        patch("apps.bots.telegram.bot.TelegramBot.is_configured", return_value=True),
        patch("apps.bots.bale.bot.BaleBot.is_configured", return_value=False),
        patch(
            "apps.bots.telegram.bot.TelegramBot",
            return_value=FakeTelegramBot(),
        ),
        patch.object(handler, "_start_telegram_gateway", AsyncMock()) as gateway,
    ):
        await handler.setup()

    gateway.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_handler_starts_bale_polling() -> None:
    handler = BotHandler()
    handler.is_setup = False
    handler._runtime_tasks = []

    with (
        patch("apps.bots.telegram.bot.TelegramBot.is_configured", return_value=False),
        patch("apps.bots.bale.bot.BaleBot.is_configured", return_value=True),
        patch("apps.bots.bale.bot.BaleBot", return_value=FakeBaleBot()),
        patch.object(handler, "_start_telegram_gateway", AsyncMock()) as gateway,
        patch.object(handler, "_setup_bale_bot", AsyncMock()) as setup_bale,
        patch.object(handler, "_start_bale_polling", AsyncMock()) as start_poll,
    ):
        await handler.setup()

    gateway.assert_not_awaited()
    setup_bale.assert_awaited_once()
    start_poll.assert_awaited_once()


@pytest.mark.asyncio
async def test_telethon_gateway_start_skips_missing_credentials() -> None:
    handler = BotHandler()
    handler._runtime_tasks = []
    bot = FakeTelegramBot()

    with (
        patch.object(Settings, "telegram_api_id", 0),
        patch.object(Settings, "telegram_api_hash", None),
        patch("apps.bots.runtime.handlers.asyncio.create_task") as create_task,
    ):
        await handler._start_telegram_gateway(bot)

    create_task.assert_not_called()


@pytest.mark.asyncio
async def test_startup_notification_sends_version_to_admin() -> None:
    handler = BotHandler()
    bot = AsyncMock()
    bot.send_message = AsyncMock()

    with (
        patch.object(Settings, "admin_chat_id", "47719525"),
        patch("apps.bots.runtime.handlers.app_version", return_value="1.2.3"),
    ):
        await handler._notify_admin_started("test_bot", "telethon", bot=bot)

    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.args[0] == "47719525"
    assert "1.2.3" in bot.send_message.await_args.args[1]


@pytest.mark.asyncio
async def test_startup_notification_skips_without_admin_chat_id() -> None:
    handler = BotHandler()
    bot = AsyncMock()

    with patch.object(Settings, "admin_chat_id", None):
        await handler._notify_admin_started("test_bot", "telethon", bot=bot)

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_startup_notification_uses_telethon_renderer() -> None:
    handler = BotHandler()
    renderer = AsyncMock()
    renderer.send_text = AsyncMock()

    with (
        patch.object(Settings, "admin_chat_id", "47719525"),
        patch("apps.bots.runtime.handlers.app_version", return_value="1.2.3"),
    ):
        await handler._notify_admin_started(
            "test_bot",
            "telethon",
            renderer=renderer,
        )

    renderer.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_telethon_event_renderer_sends_text() -> None:
    client = AsyncMock()
    client.send_message = AsyncMock(return_value="sent")
    renderer = TelethonEventRenderer(client)

    result = await renderer.send_text(100, "hello", reply_to=10)

    assert result == "sent"
    client.send_message.assert_awaited_once_with(100, "hello", reply_to=10)


@pytest.mark.asyncio
async def test_telethon_event_renderer_answers_callback_noop() -> None:
    renderer = TelethonEventRenderer(AsyncMock())

    await renderer.answer_callback("cb-1", "done")


def test_telethon_normalize_message_uses_event_ids_without_loaded_chat() -> None:
    gateway = TelethonGateway("test_bot", 1, "hash", "token")
    message = SimpleNamespace(
        id=290,
        file=None,
        sender=None,
        reply_to_msg_id=None,
        text="/start",
    )
    event = SimpleNamespace(
        message=message,
        chat=None,
        chat_id=47719525,
        sender_id=47719525,
    )

    normalized = gateway._normalize_message(event)

    assert normalized.chat_id == 47719525
    assert normalized.message_id == 290
    assert normalized.sender is not None
    assert normalized.sender.id == 47719525


@pytest.mark.asyncio
async def test_setup_bale_bot_skips_when_not_configured() -> None:
    handler = BotHandler()
    bot = AsyncMock()
    bot.token = ""
    bot.me = "bale_bot"

    with (
        patch("apps.bots.bale.bot.BaleBot.is_configured", return_value=False),
        patch(
            "apps.bots.common.renderer_registry.register_renderer"
        ) as register_renderer,
    ):
        await handler._setup_bale_bot(bot)

    register_renderer.assert_not_called()
