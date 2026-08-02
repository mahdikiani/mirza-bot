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

_WEBHOOK_HEADERS = {"x-api-key": "test-webhook-key"}


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
            "webhook_custom_headers": _WEBHOOK_HEADERS,
        },
    )


@pytest.mark.asyncio
async def test_ocr_submit_includes_workspace_id_when_given() -> None:
    """
    Test that workspace_id, when given, is threaded into the payload.

    This is how the Telegram user's own workspace (not the shared
    service account's) bills for the task.
    """
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "ocr-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        await OCRClient.submit(
            file_url="https://files/doc.pdf",
            user_id="user-1",
            webhook_url="https://bot/ocr",
            workspace_id="ws-1",
        )

    sent_payload = client.post.call_args.kwargs["json"]
    assert sent_payload["workspace_id"] == "ws-1"


@pytest.mark.asyncio
async def test_ocr_submit_omits_workspace_id_when_absent() -> None:
    """
    Test that omitting workspace_id leaves the field out entirely.

    Falls back to the caller's personal quota on the ai-toolkit side.
    """
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "ocr-1"}))

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        await OCRClient.submit(
            file_url="https://files/doc.pdf",
            user_id="user-1",
            webhook_url="https://bot/ocr",
        )

    sent_payload = client.post.call_args.kwargs["json"]
    assert "workspace_id" not in sent_payload


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
            "webhook_custom_headers": _WEBHOOK_HEADERS,
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
            "user_id": "user-1",
            "webhook_custom_headers": _WEBHOOK_HEADERS,
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
        json={
            "video_id": "abc",
            "user_id": "user-1",
            "webhook_custom_headers": _WEBHOOK_HEADERS,
        },
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
    # Regression: ai-toolkit mounts this route under /openai/v1, not at the
    # bare toolkit base URL — calling "/chat/completions" 404s.
    client.post.assert_awaited_once()
    called_path = client.post.await_args.args[0]
    assert called_path == "/openai/v1/chat/completions"


@pytest.mark.asyncio
async def test_completion_complete_includes_user_and_workspace_id() -> None:
    """
    Without user_id, ai-toolkit bills chat against mirza-bot's own key.

    That's the shared service-key identity, not the actual Telegram user
    asking.
    """
    client = AsyncMock()
    client.post = AsyncMock(
        return_value=_response({"choices": [{"message": {"content": "hi"}}]})
    )

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        await CompletionClient.complete(
            messages=[{"role": "user", "content": "hi"}],
            user_id="telegram-user-1",
            workspace_id="ws-1",
        )

    sent_json = client.post.call_args.kwargs["json"]
    assert sent_json["user_id"] == "telegram-user-1"
    assert sent_json["workspace_id"] == "ws-1"


@pytest.mark.asyncio
async def test_completion_complete_omits_user_and_workspace_id_when_absent() -> None:
    client = AsyncMock()
    client.post = AsyncMock(
        return_value=_response({"choices": [{"message": {"content": "hi"}}]})
    )

    with patch("apps.ai.clients.toolkit_client", return_value=_client_ctx(client)):
        await CompletionClient.complete(messages=[{"role": "user", "content": "hi"}])

    sent_json = client.post.call_args.kwargs["json"]
    assert "user_id" not in sent_json
    assert "workspace_id" not in sent_json
