"""Unit tests for apps.ai.clients.MediaClient.upload.

Validates: Requirements 16.1, 16.2, 16.3
"""

from __future__ import annotations

import logging
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


def _make_mock_httpx_client(upload_resp: MagicMock, patch_resp: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=upload_resp)
    mock_client.patch = AsyncMock(return_value=patch_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


@pytest.mark.asyncio
async def test_upload_url_from_patch_resp() -> None:
    """Req 16.1: URL is taken from patch_resp when available."""
    upload_resp = _mock_response(
        json_data={"uid": "file-123", "url": "https://media.example.com/old-url"},
    )
    patch_resp = _mock_response(
        json_data={"url": "https://media.example.com/final-url"},
    )
    mock_client = _make_mock_httpx_client(upload_resp, patch_resp)

    with patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client):
        result = await MediaClient.upload(b"file-content", "test.pdf")

    assert result == "https://media.example.com/final-url"


@pytest.mark.asyncio
async def test_upload_fallback_to_upload_resp_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Req 16.2: Falls back to upload_resp URL when patch_resp has no url, with warning.
    """
    upload_resp = _mock_response(
        json_data={"uid": "file-456", "url": "https://media.example.com/upload-url"},
    )
    patch_resp = _mock_response(json_data={})  # no "url" field
    mock_client = _make_mock_httpx_client(upload_resp, patch_resp)

    with (
        patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client),
        caplog.at_level(logging.WARNING),
    ):
        result = await MediaClient.upload(b"file-content", "test.pdf")

    assert result == "https://media.example.com/upload-url"
    assert any("patch_resp missing url field" in rec.message for rec in caplog.records)


@pytest.mark.asyncio
async def test_upload_raises_value_error_when_no_url() -> None:
    """Req 16.3: ValueError raised when both responses have no URL."""
    upload_resp = _mock_response(json_data={"uid": "file-789"})  # no "url"
    patch_resp = _mock_response(json_data={})  # no "url"
    mock_client = _make_mock_httpx_client(upload_resp, patch_resp)

    with (
        patch("utils.clients.media.httpx.AsyncClient", return_value=mock_client),
        pytest.raises(ValueError, match="no URL returned for file"),
    ):
        await MediaClient.upload(b"file-content", "missing.pdf")
