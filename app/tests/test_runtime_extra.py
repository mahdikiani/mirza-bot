"""Extra coverage for runtime handlers, poller, and Bale renderer."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.bale.bot import BaleBot
from apps.bots.bale.renderer import BaleEventRenderer
from apps.bots.common.events import FileRef, MessageEvent, Sender
from apps.bots.common.keyboards import InlineButton, InlineKeyboard
from apps.bots.runtime import poller, registry
from apps.bots.runtime.handlers import BotHandler
from server.config import Settings


@pytest.fixture(autouse=True)
def _clear_registry() -> None:
    registry.clear()
    yield
    registry.clear()


@pytest.mark.asyncio
async def test_start_telegram_gateway_registers_and_starts() -> None:
    handler = BotHandler()
    handler._runtime_tasks = []
    bot = MagicMock()
    bot.token = "tg-token"
    bot.me = "tg_bot"

    fake_gateway = MagicMock()
    fake_gateway.on_message = MagicMock()
    fake_gateway.on_callback = MagicMock()
    fake_gateway.on_inline_query = MagicMock()
    fake_gateway.on_started = MagicMock()
    fake_gateway.start = AsyncMock()
    fake_task = MagicMock()

    with (
        patch.object(Settings, "telegram_api_id", 123),
        patch.object(Settings, "telegram_api_hash", "hash"),
        patch(
            "apps.bots.runtime.handlers.TelethonGateway",
            return_value=fake_gateway,
        ),
        patch(
            "apps.bots.runtime.handlers.asyncio.create_task",
            return_value=fake_task,
        ) as create_task,
    ):
        await handler._start_telegram_gateway(bot)

    create_task.assert_called_once()
    fake_gateway.on_message.assert_called_once()
    fake_gateway.on_callback.assert_called_once()
    assert fake_task in handler._runtime_tasks


@pytest.mark.asyncio
async def test_setup_bale_bot_registers_renderer() -> None:
    handler = BotHandler()
    bot = BaleBot.__new__(BaleBot)
    bot.token = "bale-token"
    bot.me = "bale_bot"
    bot.resolve_me = AsyncMock()

    with (
        patch("apps.bots.bale.bot.BaleBot.is_configured", return_value=True),
        patch.object(handler, "_clear_webhook", AsyncMock()) as clear_wh,
        patch.object(handler, "_notify_admin_started", AsyncMock()),
        patch(
            "apps.bots.common.renderer_registry.register_renderer"
        ) as register_renderer,
    ):
        await handler._setup_bale_bot(bot)

    clear_wh.assert_awaited_once()
    register_renderer.assert_called_once()


@pytest.mark.asyncio
async def test_poller_bale_bots_from_registry() -> None:
    bot = MagicMock()
    bot.bot_type = "bale"
    bot.me = "b1"
    registry.register(bot)

    with patch("apps.bots.bale.bot.BaleBot.is_configured", return_value=True):
        bots = await poller._bale_bots()
    assert bot in bots


@pytest.mark.asyncio
async def test_poller_full_loop_one_iteration() -> None:
    bot = MagicMock()
    bot.bot_type = "bale"
    bot.me = "b1"
    bot.last_update_id = None
    bot.get_updates = AsyncMock(return_value=[])
    bot.process_new_updates = AsyncMock()

    call_count = 0

    async def fake_sleep(_seconds: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            raise asyncio.CancelledError

    with (
        patch("apps.bots.runtime.poller._bale_bots", AsyncMock(return_value=[bot])),
        patch("apps.bots.runtime.poller.asyncio.sleep", fake_sleep),
        pytest.raises(asyncio.CancelledError),
    ):
        await poller._polling_loop(0.01)

    bot.get_updates.assert_awaited()


@pytest.mark.asyncio
async def test_bale_renderer_send_and_edit() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value="sent")
    bot.edit_message_text = AsyncMock()
    bot.send_chat_action = AsyncMock()
    bot.answer_callback_query = AsyncMock()
    renderer = BaleEventRenderer(bot)

    await renderer.send_typing(1)
    result = await renderer.send_text(1, "hi", reply_to=2)
    assert result == "sent"
    await renderer.edit_message(1, 2, "edited")
    await renderer.answer_callback("cb1", "ok")
    await renderer.send_upload_action(1)
    await renderer.answer_inline_query("q1", "text")


@pytest.mark.asyncio
async def test_bale_renderer_send_inline_and_contact() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value="sent")
    renderer = BaleEventRenderer(bot)
    kb = InlineKeyboard(rows=[[InlineButton(label="A", callback_data="a")]])
    await renderer.send_inline_text(1, "hi", kb, reply_to=3)
    await renderer.send_contact_request(1, "share phone")
    bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_bale_renderer_download_file() -> None:
    bot = AsyncMock()
    bot.get_file = AsyncMock(return_value=MagicMock(file_path="path"))
    bot.download_file = AsyncMock(return_value=b"data")
    renderer = BaleEventRenderer(bot)
    event = MessageEvent(
        platform="bale",
        chat_id=1,
        message_id=2,
        content_type="document",
        file=FileRef(file_id="fid", file_name="a.bin"),
        sender=Sender(id="1"),
    )
    result = await renderer.download_attached_file(event)
    assert result == (b"data", "a.bin")


@pytest.mark.asyncio
async def test_clear_webhook() -> None:
    handler = BotHandler()
    bot = AsyncMock()
    bot.me = "b"
    bot.delete_webhook = AsyncMock()
    await handler._clear_webhook(bot)
    bot.delete_webhook.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_bale_polling_when_configured() -> None:
    handler = BotHandler()
    with patch(
        "apps.bots.runtime.poller.start_bale_polling", return_value=MagicMock()
    ) as start:
        await handler._start_bale_polling()
    start.assert_called_once()
