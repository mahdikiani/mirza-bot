"""Unit tests for AI Toolkit HTTP clients (apps.ai.clients)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.ai.clients import (
    CompletionClient,
    OCRClient,
    PrompticClient,
    TranscribeClient,
    WebpageClient,
    YoutubeClient,
)


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@asynccontextmanager
async def _client_ctx(client: AsyncMock) -> AsyncGenerator[AsyncMock]:
    yield client


@pytest.mark.asyncio
async def test_ocr_submit_uses_toolkit_ocrs_route() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "ocr-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await OCRClient.submit(
            file_url="https://files/doc.pdf",
            user_id="user-1",
            webhook_url="https://bot/ocr",
            meta_data={"chat_id": 10},
        )

    assert result == {"uid": "ocr-1"}
    client.post.assert_awaited_once_with(
        "/ocrs",
        json={
            "file_url": "https://files/doc.pdf",
            "user_id": "user-1",
            "webhook_url": "https://bot/ocr",
            "meta_data": {"chat_id": 10},
        },
    )


@pytest.mark.asyncio
async def test_transcribe_submit_forwards_user_and_metadata() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "tr-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await TranscribeClient.submit(
            file_url="https://files/audio.ogg",
            user_id="user-1",
            webhook_url="https://bot/transcribe",
            meta_data={"message_id": 20},
        )

    assert result == {"uid": "tr-1"}
    client.post.assert_awaited_once_with(
        "/transcribes",
        json={
            "file_url": "https://files/audio.ogg",
            "user_id": "user-1",
            "webhook_url": "https://bot/transcribe",
            "meta_data": {"message_id": 20},
        },
    )


@pytest.mark.asyncio
async def test_promptic_execute_uses_toolkit_promptic_route() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"result": "خلاصه"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await PrompticClient.execute_sync(
            prompt_name="summarize",
            input_variables={"content": "text"},
            user_id="user-1",
        )

    assert result == "خلاصه"
    client.post.assert_awaited_once_with(
        "/promptic",
        params={
            "prompt_name": "summarize",
            "blocking": "true",
            "stream": "false",
        },
        json={
            "input_variables": {"content": "text"},
            "meta_data": {"user_id": "user-1"},
        },
    )


@pytest.mark.asyncio
async def test_youtube_submit() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "yt-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await YoutubeClient.submit(video_id="abc", user_id="user-1")

    assert result == {"uid": "yt-1"}
    client.post.assert_awaited_once_with(
        "/youtube",
        json={"video_id": "abc", "user_id": "user-1"},
    )


@pytest.mark.asyncio
async def test_webpage_submit() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "web-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await WebpageClient.submit(
            url="https://example.com",
            user_id="user-1",
            webhook_url="https://bot/webpage",
        )

    assert result == {"uid": "web-1"}


@pytest.mark.asyncio
async def test_completion_complete() -> None:
    client = AsyncMock()
    client.post = AsyncMock(
        return_value=_response(
            {"choices": [{"message": {"content": "hello"}}]},
        )
    )

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        result = await CompletionClient.complete(
            messages=[{"role": "user", "content": "hi"}],
            model="test-model",
        )

    assert result == "hello"
