"""Tests for server.redis and other remaining uncovered modules."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import server.db as redis_module
from apps.ai.clients import OCRClient, TranscribeClient
from server.db import get_redis
from utils.clients._base import (
    MAX_RETRIES,
    _admin_headers,
    _request_with_retry,
    generate_trace_id,
    service_client,
)
from utils.media import get_media_client, upload_file

# ---------------------------------------------------------------------------
# server.redis
# ---------------------------------------------------------------------------


class TestRedis:
    def test_get_redis_returns_initialized_client(self) -> None:
        assert get_redis() is redis_module.redis

    def test_redis_sync_attribute_exists(self) -> None:
        assert hasattr(redis_module, "redis_sync")


# ---------------------------------------------------------------------------
# utils.clients._base
# ---------------------------------------------------------------------------


class TestServiceClient:
    @pytest.mark.asyncio
    async def test_service_client_yields_authenticated_client(self) -> None:
        mock_httpx = AsyncMock()
        mock_httpx.__aenter__ = AsyncMock(return_value=mock_httpx)
        mock_httpx.__aexit__ = AsyncMock(return_value=False)
        mock_httpx.base_url = "https://test.api"

        with (
            patch("utils.clients._base.Settings") as mock_settings,
            patch("utils.clients._base.httpx.AsyncClient", return_value=mock_httpx),
        ):
            mock_settings.ai_api_key = "test-key"

            async with service_client("https://test.api") as client:
                assert client.base_url == "https://test.api"

    @pytest.mark.asyncio
    async def test_service_client_custom_api_key(self) -> None:
        mock_httpx = AsyncMock()
        mock_httpx.__aenter__ = AsyncMock(return_value=mock_httpx)
        mock_httpx.__aexit__ = AsyncMock(return_value=False)
        mock_get = AsyncMock(return_value=MagicMock())
        mock_httpx.get = mock_get

        with (
            patch("utils.clients._base.Settings") as mock_settings,
            patch("utils.clients._base.httpx.AsyncClient", return_value=mock_httpx),
        ):
            mock_settings.ai_api_key = "default-key"

            async with service_client(
                "https://test.api", api_key="custom-key"
            ) as client:
                resp = await client.get("/test")
                assert resp is not None

    def test_generate_trace_id_returns_string(self) -> None:
        tid = generate_trace_id()
        assert isinstance(tid, str)
        assert len(tid) == 12

    def test_admin_headers_with_trace_id(self) -> None:
        headers = _admin_headers(api_key="k1", trace_id="abc123")
        assert headers["x-api-key"] == "k1"
        assert headers["x-trace-id"] == "abc123"

    def test_admin_headers_default_key(self) -> None:
        with patch("utils.clients._base.Settings") as mock_settings:
            mock_settings.ai_api_key = "default-key"
            headers = _admin_headers()
        assert headers["x-api-key"] == "default-key"
        assert "x-trace-id" not in headers


# ---------------------------------------------------------------------------
# utils.clients._base — retry logic
# ---------------------------------------------------------------------------


class TestRequestWithRetry:
    @pytest.mark.asyncio
    async def test_retry_succeeds_on_retryable_status(self) -> None:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock()
        mock_client.request.side_effect = [
            MagicMock(status_code=503),
            MagicMock(status_code=200),
        ]

        with patch("utils.clients._base.asyncio.sleep", AsyncMock()):
            resp = await _request_with_retry(mock_client, "GET", "/test", "trace1")

        assert resp.status_code == 200
        assert mock_client.request.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_fails_after_max_attempts(self) -> None:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock()
        mock_client.request.return_value = MagicMock(status_code=503)

        with (
            patch("utils.clients._base.asyncio.sleep", AsyncMock()),
            pytest.raises(httpx.TransportError),
        ):
            await _request_with_retry(mock_client, "GET", "/test", "trace2")

        assert mock_client.request.await_count == MAX_RETRIES + 1

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_network_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.request = AsyncMock()
        mock_client.request.side_effect = [
            httpx.TransportError("conn reset"),
            MagicMock(status_code=200),
        ]

        with patch("utils.clients._base.asyncio.sleep", AsyncMock()):
            resp = await _request_with_retry(mock_client, "GET", "/test", "trace3")

        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# apps.ai.clients — additional coverage for get_result methods
# ---------------------------------------------------------------------------


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class FakeAsyncClient:
    """Minimal async context manager that returns the same mock for all HTTP methods."""

    def __init__(self, resp: MagicMock) -> None:
        self._resp = resp

    async def get(self, *args: object, **kwargs: object) -> MagicMock:
        return self._resp

    async def post(self, *args: object, **kwargs: object) -> MagicMock:
        return self._resp

    async def __aenter__(self) -> FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass


class TestAIClientsAdditional:
    @pytest.mark.asyncio
    async def test_ocr_get_result_returns_text(self) -> None:
        resp = _response({"task_status": "completed", "result": "OCR text result"})
        client = FakeAsyncClient(resp)

        with patch("apps.ai.clients.toolkit_client", return_value=client):
            result = await OCRClient.get_result("task-ocr-1")

        assert result == "OCR text result"

    @pytest.mark.asyncio
    async def test_transcribe_get_result_returns_text(self) -> None:
        resp = _response({"task_status": "completed", "result": "Transcription text"})
        client = FakeAsyncClient(resp)

        with patch("apps.ai.clients.toolkit_client", return_value=client):
            result = await TranscribeClient.get_result("task-tr-1")

        assert result == "Transcription text"


# ---------------------------------------------------------------------------
# utils.media (legacy module)
# ---------------------------------------------------------------------------


class TestLegacyMedia:
    @pytest.mark.asyncio
    async def test_get_media_client_yields_client(self) -> None:
        with patch("utils.media.Settings") as mock_settings:
            mock_settings.media_api_key = "media-key"

            async with get_media_client() as client:
                assert client is not None

    @pytest.mark.asyncio
    async def test_upload_file_returns_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"uid": "file-1", "url": "https://media.test/file-1"},
                raise_for_status=lambda: None,
            )
        )
        mock_client.patch = AsyncMock(
            return_value=MagicMock(
                json=lambda: {"url": "https://media.test/file-1"},
                raise_for_status=lambda: None,
            )
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        from io import BytesIO

        with patch("utils.media.get_media_client", return_value=mock_client):
            url = await upload_file(BytesIO(b"test content"), "test.txt")

        assert url == "https://media.test/file-1"
