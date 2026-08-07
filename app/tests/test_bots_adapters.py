"""Tests for BaleBot helpers, Telegram config, and runtime registry."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telebot.asyncio_helper import ApiTelegramException

from apps.bots.bale.bot import BaleBot, BaleToken, raw_bale_token
from apps.bots.bale.renderer import BaleEventRenderer, _bale_safe_html
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


def test_bale_safe_html_removes_literal_code_tags() -> None:
    assert _bale_safe_html("Version: <code>0.1.26</code>") == "Version: `0.1.26`"
    assert _bale_safe_html("<pre>a &lt; b</pre>") == "```a < b```"
    assert _bale_safe_html("<pre><code>a &lt; b</code></pre>") == "```\na < b\n```"
    assert _bale_safe_html("<b>bold</b>") == "*bold*"
    assert _bale_safe_html("**already markdown**") == "**already markdown**"


@pytest.mark.asyncio
async def test_bale_renderer_converts_html_ui_copy_to_markdown() -> None:
    bot = AsyncMock()
    bot.send_message.return_value = "sent"
    renderer = BaleEventRenderer(bot)

    result = await renderer.send_text(1, "نسخه: <code>0.1.26</code>")

    assert result == "sent"
    bot.send_message.assert_awaited_once_with(1, "نسخه: `0.1.26`")


def test_bale_renderer_keeps_ai_markdown() -> None:
    rendered = BaleEventRenderer.render_markdown("# title\n\n**bold**")
    assert "*title*" in rendered
    assert "*bold*" in rendered
    assert "<b>" not in rendered


@pytest.mark.asyncio
async def test_bale_document_reply_uses_legacy_reply_field() -> None:
    bot = MagicMock()
    bot.token = "x" * 51
    renderer = BaleEventRenderer(bot)
    api_result = {
        "message_id": 22,
        "date": 0,
        "chat": {"id": 1, "type": "private"},
        "reply_to_message": {
            "message_id": 11,
            "date": 0,
            "chat": {"id": 1, "type": "private"},
        },
        "document": {"file_id": "file-1", "file_unique_id": "unique-1"},
    }

    with patch(
        "telebot.asyncio_helper._process_request",
        AsyncMock(return_value=api_result),
    ) as request:
        sent = await renderer.send_document(
            1,
            b"# result",
            "result.md",
            caption="result",
            reply_to=11,
        )

    params = request.await_args.kwargs["params"]
    assert params["reply_to_message_id"] == 11
    assert "reply_parameters" not in params
    assert request.await_args.kwargs["files"]["document"][0] == "result.md"
    assert sent.message_id == 22
    assert sent.reply_to_message.message_id == 11


@pytest.mark.asyncio
async def test_bale_document_without_reply_uses_library_client() -> None:
    bot = AsyncMock()
    bot.send_document.return_value = "sent"
    renderer = BaleEventRenderer(bot)

    result = await renderer.send_document(1, b"data", "result.md")

    assert result == "sent"
    bot.send_document.assert_awaited_once()


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

    async def fake_super(self, text=None, chat_id=None, message_id=None, **kwargs):
        raise ApiTelegramException(
            "editMessageText",
            None,
            {"error_code": 400, "description": "message is not modified: ok"},
        )

    from telebot.async_telebot import AsyncTeleBot

    with patch.object(AsyncTeleBot, "edit_message_text", fake_super):
        await bot.edit_message_text("same", chat_id=1, message_id=2)


@pytest.mark.asyncio
async def test_bale_edit_message_forwards_positional_chat_and_message_id() -> None:
    """
    Regression check.

    chat_id/message_id passed positionally (as the real caller in
    bale/renderer.py does) used to be silently dropped -- the wrapper
    only forwarded **kwargs to the real client, so every Bale
    edit_message call actually edited nothing (chat_id/message_id both
    defaulted to None), and the caller's blanket except-and-fallback
    masked it by silently sending a brand-new message every time
    instead of editing in place.
    """
    bot = BaleBot.__new__(BaleBot)
    bot.token = "x" * 51
    bot.me = "bale"

    calls: list[tuple] = []

    async def fake_super(self, *args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))

    from telebot.async_telebot import AsyncTeleBot

    with patch.object(AsyncTeleBot, "edit_message_text", fake_super):
        await bot.edit_message_text("updated", 111, 222, reply_markup=None)

    assert calls == [(("updated", 111, 222), {"reply_markup": None})]


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
