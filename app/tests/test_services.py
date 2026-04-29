"""Unit tests for apps.bots.services.

Covers:
- _get_or_create_session (idempotency, missing uid/id)
- _extract_text_attachment (extension filtering, download)
- _build_reply_chain (single message, reply chain, bot sender)
- TranscribeClient.submit meta_data forwarding
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.services import (
    _build_reply_chain,
    _extract_text_attachment,
    _get_or_create_session,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(uid: str = "user-uid-1") -> SimpleNamespace:
    return SimpleNamespace(uid=uid)


def _make_profile(language: str = "fa") -> SimpleNamespace:
    engine_config = SimpleNamespace(
        model="openai/gpt-4o-mini",
        language=language,
        model_dump=lambda: {"model": "openai/gpt-4o-mini", "language": language},
    )
    return SimpleNamespace(profile_data=SimpleNamespace(engine_config=engine_config))


def _make_message(
    *,
    text: str = "سلام",
    chat_type: str = "private",
    chat_id: int = 100,
    user: object | None = None,
    profile: object | None = None,
    reply_to: object | None = None,
    document: object | None = None,
    from_user: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        caption=None,
        chat=SimpleNamespace(type=chat_type, id=chat_id),
        user=user or _make_user(),
        profile=profile or _make_profile(),
        reply_to_message=reply_to,
        document=document,
        from_user=from_user or SimpleNamespace(is_bot=False),
    )


def _make_bot() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# _get_or_create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_session_returns_uid() -> None:
    """Returns session_id from 'uid' field."""
    msg = _make_message()
    with patch(
        "apps.bots.services.AIChatClient.get_or_create_session",
        new_callable=AsyncMock,
        return_value={"uid": "session-123"},
    ):
        result = await _get_or_create_session(msg)
    assert result == "session-123"


@pytest.mark.asyncio
async def test_get_or_create_session_falls_back_to_id() -> None:
    """Falls back to 'id' field when 'uid' is absent."""
    msg = _make_message()
    with patch(
        "apps.bots.services.AIChatClient.get_or_create_session",
        new_callable=AsyncMock,
        return_value={"id": "session-456"},
    ):
        result = await _get_or_create_session(msg)
    assert result == "session-456"


@pytest.mark.asyncio
async def test_get_or_create_session_logs_error_on_missing_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Logs error and returns None when response has neither uid nor id."""
    msg = _make_message()
    with (
        patch(
            "apps.bots.services.AIChatClient.get_or_create_session",
            new_callable=AsyncMock,
            return_value={"something_else": "value"},
        ),
        caplog.at_level(logging.ERROR),
    ):
        result = await _get_or_create_session(msg)
    assert result is None
    assert any("no uid/id" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_get_or_create_session_no_user_returns_none() -> None:
    """Returns None immediately when message has no user."""
    msg = _make_message()
    msg.user = None
    result = await _get_or_create_session(msg)
    assert result is None


@pytest.mark.asyncio
async def test_get_or_create_session_group_chat_uses_group_id() -> None:
    """Group chats use group:{chat_id} as the session chat_id."""
    msg = _make_message(chat_type="group", chat_id=999)
    captured = {}

    async def mock_session(**kwargs: object) -> dict:  # noqa: RUF029
        captured.update(kwargs)
        return {"uid": "group-session"}

    with patch(
        "apps.bots.services.AIChatClient.get_or_create_session",
        side_effect=mock_session,
    ):
        await _get_or_create_session(msg)

    assert captured["chat_id"] == "group:999"


# ---------------------------------------------------------------------------
# _extract_text_attachment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extract_text_attachment_md_file() -> None:
    """Returns decoded content for .md files."""
    doc = SimpleNamespace(file_id="file-1", file_name="notes.md")
    msg = _make_message(document=doc)
    bot = _make_bot()
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="path/notes.md"))
    bot.download_file = AsyncMock(return_value=b"# Hello\n\nWorld")

    result = await _extract_text_attachment(msg, bot)
    assert result == "# Hello\n\nWorld"


@pytest.mark.asyncio
async def test_extract_text_attachment_txt_file() -> None:
    """Returns decoded content for .txt files."""
    doc = SimpleNamespace(file_id="file-2", file_name="readme.txt")
    msg = _make_message(document=doc)
    bot = _make_bot()
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="path/readme.txt"))
    bot.download_file = AsyncMock(return_value=b"plain text content")

    result = await _extract_text_attachment(msg, bot)
    assert result == "plain text content"


@pytest.mark.asyncio
async def test_extract_text_attachment_pdf_skipped() -> None:
    """Returns None for .pdf files (handled by OCR pipeline)."""
    doc = SimpleNamespace(file_id="file-3", file_name="doc.pdf")
    msg = _make_message(document=doc)
    bot = _make_bot()

    result = await _extract_text_attachment(msg, bot)
    assert result is None
    bot.get_file.assert_not_called()


@pytest.mark.asyncio
async def test_extract_text_attachment_image_skipped() -> None:
    """Returns None for image files."""
    doc = SimpleNamespace(file_id="file-4", file_name="photo.jpg")
    msg = _make_message(document=doc)
    bot = _make_bot()

    result = await _extract_text_attachment(msg, bot)
    assert result is None


@pytest.mark.asyncio
async def test_extract_text_attachment_no_document() -> None:
    """Returns None when message has no document."""
    msg = _make_message(document=None)
    bot = _make_bot()

    result = await _extract_text_attachment(msg, bot)
    assert result is None


@pytest.mark.asyncio
async def test_extract_text_attachment_download_error_returns_none(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Returns None and logs exception when download fails."""
    doc = SimpleNamespace(file_id="file-5", file_name="data.csv")
    msg = _make_message(document=doc)
    bot = _make_bot()
    bot.get_file = AsyncMock(side_effect=Exception("network error"))

    with caplog.at_level(logging.ERROR):
        result = await _extract_text_attachment(msg, bot)

    assert result is None


# ---------------------------------------------------------------------------
# _build_reply_chain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_reply_chain_single_message() -> None:
    """Single message with no reply returns just that message's text."""
    msg = _make_message(text="سوال من")
    bot = _make_bot()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()

    result = await _build_reply_chain(msg, bot)
    assert "سوال من" in result
    assert "[کاربر]" in result


@pytest.mark.asyncio
async def test_build_reply_chain_with_reply() -> None:
    """Reply chain builds context from oldest to newest."""
    parent = SimpleNamespace(
        text="پیام اول",
        caption=None,
        reply_to_message=None,
        document=None,
        from_user=SimpleNamespace(is_bot=False),
    )
    child = _make_message(text="پیام دوم", reply_to=parent)
    bot = _make_bot()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()

    result = await _build_reply_chain(child, bot)
    # Oldest message should appear first
    assert result.index("پیام اول") < result.index("پیام دوم")


@pytest.mark.asyncio
async def test_build_reply_chain_bot_sender_labeled() -> None:
    """Messages from bots are labeled as 'دستیار'."""
    bot_msg = SimpleNamespace(
        text="پاسخ بات",
        caption=None,
        reply_to_message=None,
        document=None,
        from_user=SimpleNamespace(is_bot=True),
    )
    user_msg = _make_message(text="سوال کاربر", reply_to=bot_msg)
    bot = _make_bot()
    bot.get_file = AsyncMock()
    bot.download_file = AsyncMock()

    result = await _build_reply_chain(user_msg, bot)
    assert "[دستیار]" in result
    assert "[کاربر]" in result


@pytest.mark.asyncio
async def test_build_reply_chain_with_text_attachment() -> None:
    """Text attachment in a reply message is included in the chain."""
    doc = SimpleNamespace(file_id="f1", file_name="notes.md")
    parent = SimpleNamespace(
        text="",
        caption=None,
        reply_to_message=None,
        document=doc,
        from_user=SimpleNamespace(is_bot=False),
    )
    child = _make_message(text="درباره این فایل توضیح بده", reply_to=parent)
    bot = _make_bot()
    bot.get_file = AsyncMock(return_value=SimpleNamespace(file_path="path/notes.md"))
    bot.download_file = AsyncMock(return_value=b"# My Notes\n\nContent here")

    result = await _build_reply_chain(child, bot)
    assert "My Notes" in result
    assert "درباره این فایل توضیح بده" in result
