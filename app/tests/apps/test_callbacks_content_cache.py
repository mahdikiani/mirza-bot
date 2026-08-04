"""
Regression: convert-to-file buttons must recover the original Markdown.

Even after the result was delivered as real rich text (which strips the
literal '#'/'**' syntax from the message's plain-text copy on Telegram).
"""


from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common.callbacks import _get_content
from apps.bots.common.events import CallbackEvent, FileRef, Sender


def _event(message_id: int | str = 42, file: FileRef | None = None) -> CallbackEvent:
    return CallbackEvent(
        platform="telegram",
        chat_id=1,
        message_id=message_id,
        callback_id="cb-1",
        data="convert:docx",
        sender=Sender(id=2),
        file=file,
    )


class _RendererWithDownload:
    async def download_document(self, chat_id, message_id) -> bytes:
        return b"# Stripped Heading\nplain body without markdown markers"


@pytest.mark.asyncio
async def test_prefers_cached_raw_markdown_over_downloaded_message() -> None:
    ctx = type("Ctx", (), {"renderer": _RendererWithDownload()})()
    with patch(
        "apps.bots.common.callbacks.content.result_content_cache.get",
        AsyncMock(return_value="# Real Heading\n**bold** text"),
    ):
        content = await _get_content(_event(), ctx)

    assert content == "# Real Heading\n**bold** text"


@pytest.mark.asyncio
async def test_falls_back_to_download_document_when_cache_misses() -> None:
    ctx = type("Ctx", (), {"renderer": _RendererWithDownload()})()
    with patch(
        "apps.bots.common.callbacks.content.result_content_cache.get",
        AsyncMock(return_value=None),
    ):
        content = await _get_content(_event(), ctx)

    assert "Stripped Heading" in content


class _RendererWithAttachedFile:
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def download_attached_file(self, event) -> tuple[bytes, str]:
        return self._data, "result.md"

    async def download_document(self, chat_id, message_id) -> bytes:
        raise AssertionError("should not reach download_document")


@pytest.mark.asyncio
async def test_falls_back_to_attached_file_when_cache_misses() -> None:
    """
    On Bale (no generic get-message-by-id), re-download by file_id instead.

    Preferred over download_document once the callback carries a file_id
    (see CallbackEvent.file / normalize_bale_callback).
    """
    file_ref = FileRef(file_id="file-abc", file_name="result.md")
    ctx = type(
        "Ctx", (), {"renderer": _RendererWithAttachedFile(b"# Real content")}
    )()
    with patch(
        "apps.bots.common.callbacks.content.result_content_cache.get",
        AsyncMock(return_value=None),
    ):
        content = await _get_content(_event(file=file_ref), ctx)

    assert content == "# Real content"


class _RendererWithFailingAttachedFile:
    async def download_attached_file(self, event):
        raise RuntimeError("network error")

    async def download_document(self, chat_id, message_id) -> bytes:
        return b"fallback via download_document"


@pytest.mark.asyncio
async def test_falls_back_to_download_document_when_attached_file_fails() -> None:
    file_ref = FileRef(file_id="file-abc", file_name="result.md")
    ctx = type("Ctx", (), {"renderer": _RendererWithFailingAttachedFile()})()
    with patch(
        "apps.bots.common.callbacks.content.result_content_cache.get",
        AsyncMock(return_value=None),
    ):
        content = await _get_content(_event(file=file_ref), ctx)

    assert content == "fallback via download_document"
