"""Unit tests for Telethon gateway normalization and renderer."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.bots.common.keyboards import (
    InlineButton,
    InlineKeyboard,
    ReplyButton,
    ReplyKeyboard,
)
from apps.bots.telegram.gateway import (
    TelethonEventRenderer,
    TelethonGateway,
    _telethon_buttons,
)


class TestTelethonButtons:
    def test_inline_keyboard_buttons(self) -> None:
        keyboard = InlineKeyboard(
            rows=[[InlineButton("Go", callback_data="action:go")]]
        )
        rows = _telethon_buttons(keyboard)
        assert rows is not None
        assert len(rows) == 1

    def test_reply_keyboard_contact_button(self) -> None:
        keyboard = ReplyKeyboard(
            rows=[[ReplyButton("Share", request_contact=True)]],
            one_time=True,
        )
        rows = _telethon_buttons(keyboard)
        assert rows is not None


class TestTelethonGatewayNormalize:
    def test_normalize_message_text(self) -> None:
        gateway = TelethonGateway("bot", 1, "hash", "token")
        chat = SimpleNamespace(id=100, broadcast=False, megagroup=True)
        sender = SimpleNamespace(
            id=5, bot=False, username="u", first_name="A", last_name="B"
        )
        message = SimpleNamespace(
            id=11,
            text="hello",
            file=None,
            sender=sender,
            reply_to_msg_id=None,
            reply_to=None,
        )
        event = SimpleNamespace(
            message=message, chat=chat, chat_id=100, id=11, sender_id=5
        )

        normalized = gateway._normalize_message(event)
        assert normalized.text == "hello"
        assert normalized.chat_id == 100
        assert normalized.message_id == 11
        assert normalized.sender is not None
        assert normalized.sender.id == 5

    def test_normalize_callback_data(self) -> None:
        gateway = TelethonGateway("bot", 1, "hash", "token")
        event = SimpleNamespace(
            id="cb1",
            chat_id=100,
            msg_id=22,
            data=b"settings:lang:fa",
            sender_id=5,
            message=SimpleNamespace(message="result text"),
        )

        normalized = gateway._normalize_callback(event)
        assert normalized.data == "settings:lang:fa"
        assert normalized.message_text == "result text"
        assert normalized.chat_id == 100


class TestTelethonEventRenderer:
    @pytest.mark.asyncio
    async def test_send_text_with_reply_keyboard(self) -> None:
        client = AsyncMock()
        client.send_message = AsyncMock(return_value=MagicMock(id=1))
        renderer = TelethonEventRenderer(client, "bot")
        keyboard = ReplyKeyboard(rows=[[ReplyButton("Help")]])

        await renderer.send_text(100, "hi", reply_keyboard=keyboard)

        client.send_message.assert_awaited_once()
        assert "buttons" in client.send_message.await_args.kwargs

    @pytest.mark.asyncio
    async def test_send_inline_text(self) -> None:
        client = AsyncMock()
        client.send_message = AsyncMock(return_value=MagicMock(id=2))
        renderer = TelethonEventRenderer(client, "bot")
        keyboard = InlineKeyboard(rows=[[InlineButton("Pay", callback_data="buy:1")]])

        await renderer.send_inline_text(100, "products", keyboard, reply_to=9)

        client.send_message.assert_awaited_once()
        kwargs = client.send_message.await_args.kwargs
        assert kwargs["reply_to"] == 9
        assert kwargs["buttons"] is not None

    @pytest.mark.asyncio
    async def test_edit_message(self) -> None:
        client = AsyncMock()
        renderer = TelethonEventRenderer(client, "bot")
        keyboard = InlineKeyboard(rows=[[InlineButton("OK", callback_data="ok")]])

        await renderer.edit_message(100, 5, "done", inline_keyboard=keyboard)

        client.edit_message.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_send_typing_uses_mtproto_typing_request(self) -> None:
        from telethon import functions, types

        client = AsyncMock()
        renderer = TelethonEventRenderer(client, "bot")

        await renderer.send_typing(100)

        request = client.await_args.args[0]
        assert isinstance(request, functions.messages.SetTypingRequest)
        assert isinstance(request.action, types.SendMessageTypingAction)

    @pytest.mark.asyncio
    async def test_answer_callback_with_raw_event(self) -> None:
        client = AsyncMock()
        renderer = TelethonEventRenderer(client, "bot")
        raw = AsyncMock()
        await renderer.answer_callback("cb", "ok", raw_event=raw)
        raw.answer.assert_awaited_once_with("ok")
