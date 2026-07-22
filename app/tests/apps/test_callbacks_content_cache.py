"""Regression: convert-to-file buttons must recover the original Markdown
even after the result was delivered as real rich text (which strips the
literal '#'/'**' syntax from the message's plain-text copy on Telegram)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common.callbacks import _get_content
from apps.bots.common.events import CallbackEvent, Sender


def _event(message_id: int | str = 42) -> CallbackEvent:
    return CallbackEvent(
        platform="telegram",
        chat_id=1,
        message_id=message_id,
        callback_id="cb-1",
        data="convert:docx",
        sender=Sender(id=2),
    )


class _RendererWithDownload:
    async def download_document(self, chat_id, message_id) -> bytes:
        return b"# Stripped Heading\nplain body without markdown markers"


@pytest.mark.asyncio
async def test_prefers_cached_raw_markdown_over_downloaded_message() -> None:
    ctx = type("Ctx", (), {"renderer": _RendererWithDownload()})()
    with patch(
        "apps.bots.common.callbacks.result_content_cache.get",
        AsyncMock(return_value="# Real Heading\n**bold** text"),
    ):
        content = await _get_content(_event(), ctx)

    assert content == "# Real Heading\n**bold** text"


@pytest.mark.asyncio
async def test_falls_back_to_download_document_when_cache_misses() -> None:
    ctx = type("Ctx", (), {"renderer": _RendererWithDownload()})()
    with patch(
        "apps.bots.common.callbacks.result_content_cache.get",
        AsyncMock(return_value=None),
    ):
        content = await _get_content(_event(), ctx)

    assert "Stripped Heading" in content
