"""
Unit tests for apps.ai.clients.MediaClient.upload.

Validates: Requirements 16.1, 16.2, 16.3
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from utils.clients import MediaClient


def _mock_response(
    *, status_code: int = 200, json_data: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_mock_httpx_client(upload_resp: MagicMock, signed_resp: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=upload_resp)
    mock_client.get = AsyncMock(return_value=signed_resp)
    mock_client.head = AsyncMock(return_value=_mock_response())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_upload_returns_media_signed_url_without_public_patch() -> None:
    upload_resp = _mock_response(
        json_data={"uid": "file-123", "url": "https://media.example.com/old-url"},
    )
    signed_resp = _mock_response(status_code=307)
    signed_resp.headers = {"location": "https://storage.example.com/signed"}
    mock_client = _make_mock_httpx_client(upload_resp, signed_resp)

    with patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client):
        result = await MediaClient.upload(
            b"file-content", "test.pdf", user_id="user-1"
        )

    assert result == "https://storage.example.com/signed"
    mock_client.get.assert_awaited_once_with(
        "/f/file-123", params={"signed_url": True}
    )
    mock_client.head.assert_awaited_once_with(
        "https://storage.example.com/signed", follow_redirects=True
    )
    mock_client.patch.assert_not_called()


@pytest.mark.asyncio
async def test_upload_raises_value_error_when_no_signed_url() -> None:
    upload_resp = _mock_response(json_data={"uid": "file-789"})
    signed_resp = _mock_response(status_code=307)
    signed_resp.headers = {}
    mock_client = _make_mock_httpx_client(upload_resp, signed_resp)

    with (
        patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="no signed URL returned for file"),
    ):
        await MediaClient.upload(b"file-content", "missing.pdf", user_id="user-1")


@pytest.mark.asyncio
async def test_upload_includes_user_and_workspace_id() -> None:
    """
    Without user_id, media attributes every upload to mirza-bot's own key.

    That's the shared service-key identity, not the actual Telegram user
    uploading -- no user/workspace ever owns the file.
    """
    upload_resp = _mock_response(
        json_data={"uid": "file-1", "url": "https://media.example.com/f"},
    )
    signed_resp = _mock_response(status_code=307)
    signed_resp.headers = {"location": "https://storage.example.com/signed"}
    mock_client = _make_mock_httpx_client(upload_resp, signed_resp)

    with patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client):
        await MediaClient.upload(
            b"file-content",
            "test.pdf",
            user_id="telegram-user-1",
            workspace_id="ws-1",
        )

    sent_data = mock_client.post.call_args.kwargs["data"]
    assert sent_data["user_id"] == "telegram-user-1"
    assert sent_data["workspace_id"] == "ws-1"


@pytest.mark.asyncio
async def test_upload_rejects_missing_owner() -> None:
    with pytest.raises(ValueError, match="requires an owner user_id"):
        await MediaClient.upload(b"file-content", "test.pdf")
