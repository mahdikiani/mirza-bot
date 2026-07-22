"""Tests for docx extraction and Bale adapter modules."""

from __future__ import annotations

import asyncio
import io
import zipfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.bale.markup import to_inline_markup, to_reply_markup
from apps.bots.bale.normalizer import normalize_bale_callback, normalize_bale_message
from apps.bots.bale.renderer import BaleEventRenderer
from apps.bots.common.docx import extract_docx_text
from apps.bots.common.keyboards import (
    InlineButton,
    InlineKeyboard,
    ReplyButton,
    ReplyKeyboard,
)


def _minimal_docx(text: str) -> bytes:
    buffer = io.BytesIO()
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_extract_docx_text() -> None:
    data = _minimal_docx("سلام docx")
    assert extract_docx_text(data) == "سلام docx"


def test_bale_markup_converters() -> None:
    reply = to_reply_markup(ReplyKeyboard(rows=[[ReplyButton("Help")]], one_time=True))
    assert reply is not None
    inline = to_inline_markup(
        InlineKeyboard(rows=[[InlineButton("View", url="https://example.com")]])
    )
    assert inline is not None


def test_normalize_bale_document_message() -> None:
    event = normalize_bale_message(
        {
            "message_id": 3,
            "chat": {"id": 10, "type": "private"},
            "from": {"id": 1, "first_name": "Ali"},
            "document": {
                "file_id": "doc-1",
                "file_name": "notes.docx",
                "mime_type": (
                    "application/vnd.openxmlformats-officedocument"
                    ".wordprocessingml.document"
                ),
            },
        },
        "bale_bot",
    )
    assert event.platform == "bale"
    assert event.file is not None
    assert event.file.file_name == "notes.docx"
    assert event.content_type == "document"


def test_normalize_bale_contact() -> None:
    from apps.bots.bale.normalizer import normalize_bale_contact

    event, phone, user_id = normalize_bale_contact(
        {
            "message_id": 4,
            "chat": {"id": 10, "type": "private"},
            "from": {"id": 1},
            "contact": {"phone_number": "+989121234567", "user_id": 1},
        },
        "bale_bot",
    )
    assert phone == "+989121234567"
    assert user_id == 1
    assert event.platform == "bale"


def test_normalize_bale_callback() -> None:
    event = normalize_bale_callback(
        {
            "id": "cb1",
            "data": "action:summarize",
            "message": {
                "message_id": 2,
                "chat": {"id": 10},
                "text": "result body",
            },
        },
        "bale_bot",
    )
    assert event.data == "action:summarize"
    assert event.message_text == "result body"


@pytest.mark.asyncio
async def test_process_bale_poll_updates() -> None:
    from apps.bots.runtime.poller import _process_updates

    bot = MagicMock()
    bot.me = "bale_bot"
    update = MagicMock()
    update.message = MagicMock(
        message_id=1,
        text="hi",
        chat=MagicMock(id=2, type="private"),
        from_user=MagicMock(id=3),
        caption=None,
        contact=None,
        voice=None,
        audio=None,
        video=None,
        document=None,
        sticker=None,
        animation=None,
        photo=None,
        reply_to_message=None,
        date=0,
    )
    update.callback_query = None
    with patch(
        "apps.bots.bale.handler.handle_bale_update",
        AsyncMock(),
    ) as handle_mock:
        _process_updates(bot, [update])
        await asyncio.sleep(0)
    handle_mock.assert_awaited_once()


def test_bot_return_url_bale() -> None:
    from apps.bots.common.events import PlatformCapabilities
    from apps.bots.common.handler_context import BotRuntimeContext, bot_return_url

    ctx = BotRuntimeContext(
        bot_name="bot",
        platform="bale",
        renderer=MagicMock(),
        capabilities=PlatformCapabilities(),
        bot_username="mybale",
    )
    assert bot_return_url(ctx) == "https://ble.ir/mybale"


@pytest.mark.asyncio
async def test_bale_renderer_edit_and_download() -> None:
    bot = AsyncMock()
    bot.edit_message_text = AsyncMock()
    renderer = BaleEventRenderer(bot)

    from apps.bots.common.events import FileRef, MessageEvent

    await renderer.edit_message(1, 2, "done")
    bot.edit_message_text.assert_awaited_once()

    event = MessageEvent(
        platform="bale",
        file=FileRef(file_id="f1", file_name="a.docx"),
    )
    with patch.object(
        renderer, "_download_bale_file", AsyncMock(return_value=b"bytes")
    ):
        result = await renderer.download_attached_file(event)
    assert result == (b"bytes", "a.docx")


@pytest.mark.asyncio
async def test_handle_bale_update_message() -> None:
    from apps.bots.bale.handler import handle_bale_update

    bot = AsyncMock()
    bot.me = "bale_bot"
    with (
        patch("apps.bots.bale.handler._get_bot", return_value=bot),
        patch(
            "apps.bots.bale.handler.handle_message_event",
            AsyncMock(),
        ) as message_mock,
    ):
        await handle_bale_update(
            {
                "message": {
                    "message_id": 1,
                    "text": "hello",
                    "chat": {"id": 10, "type": "private"},
                    "from": {"id": 2},
                }
            },
            "bale_bot",
        )
    message_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_bale_update_callback() -> None:
    from apps.bots.bale.handler import handle_bale_update

    bot = AsyncMock()
    bot.me = "bale_bot"
    with (
        patch("apps.bots.bale.handler._get_bot", return_value=bot),
        patch(
            "apps.bots.bale.handler.handle_callback_event",
            AsyncMock(),
        ) as callback_mock,
    ):
        await handle_bale_update(
            {
                "callback_query": {
                    "id": "cb1",
                    "data": "menu:purchase",
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 10},
                        "text": "products",
                    },
                }
            },
            "bale_bot",
        )
    callback_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_bale_renderer_contact_and_upload() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    bot.send_chat_action = AsyncMock()
    renderer = BaleEventRenderer(bot)
    await renderer.send_contact_request(10, "share phone")
    await renderer.send_upload_action(10)
    bot.send_message.assert_awaited_once()
    bot.send_chat_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_bale_renderer_send_text() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
    renderer = BaleEventRenderer(bot)
    await renderer.send_text(10, "hello", reply_to=3)
    bot.send_message.assert_awaited_once()
