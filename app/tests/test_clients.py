"""Tests for internal service clients (accounts, finance, toolkit)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.accounts.clients import UssoAccountsClient, usso_accounts_client
from utils.clients.finance import SaasClient, ShopClient
from utils.clients.toolkit import (
    ToolkitTaskNotCompletedError,
    completed_result_or_raise,
)


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


def _make_async_httpx_client(
    upload_resp: MagicMock, patch_resp: MagicMock | None = None
) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value=upload_resp)
    client.patch = AsyncMock(return_value=patch_resp or upload_resp)
    client.get = AsyncMock(return_value=upload_resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@asynccontextmanager
async def _client_ctx(client: AsyncMock) -> AsyncGenerator[AsyncMock]:
    yield client


class TestToolkit:
    def test_completed_result_or_raise_returns_result(self) -> None:
        data = {"task_status": "completed", "result": "some result"}
        assert completed_result_or_raise(data, "task-1", "OCR") == "some result"

    def test_completed_result_or_raise_raises_when_not_completed(self) -> None:
        data = {"task_status": "pending", "result": None}
        with pytest.raises(
            ToolkitTaskNotCompletedError, match="OCR task task-1 not completed: pending"
        ):
            completed_result_or_raise(data, "task-1", "OCR")

    def test_completed_result_or_raise_empty_result(self) -> None:
        data = {"task_status": "completed"}
        assert completed_result_or_raise(data, "task-2", "Transcribe") == ""


class TestUssoClient:
    @pytest.mark.asyncio
    async def test_get_or_create_user_finds_existing(self) -> None:
        official = AsyncMock()
        official.get_users = AsyncMock(
            return_value=[MagicMock(uid="user-1")],
        )
        official.create_users = AsyncMock()
        client = UssoAccountsClient(official)

        result = await client.get_or_create_user_by_identifier("telegram_id", "123")

        assert result.uid == "user-1"
        official.get_users.assert_awaited_once()
        official.create_users.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_or_create_user_creates_new(self) -> None:
        official = AsyncMock()
        official.get_users = AsyncMock(return_value=[])
        official.create_users = AsyncMock(return_value=MagicMock(uid="user-new"))
        client = UssoAccountsClient(official)

        result = await client.get_or_create_user_by_identifier("telegram_id", "456")

        assert result.uid == "user-new"
        official.create_users.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_usso_client_context_manager(self) -> None:
        with (
            patch("apps.accounts.clients.OfficialAsyncUssoClient") as mock_official,
            patch("apps.accounts.clients.Settings") as mock_settings,
        ):
            mock_settings.usso_base_url = "https://usso.test"
            mock_settings.usso_api_key = "test-key"
            mock_official.return_value.__aenter__.return_value = AsyncMock()

            async with usso_accounts_client() as client:
                assert isinstance(client, UssoAccountsClient)


class TestShopClient:
    @pytest.mark.asyncio
    async def test_list_products(self) -> None:
        client = _make_async_httpx_client(
            _mock_response(
                json_data={"items": [{"uid": "p1", "name": "Product"}], "total": 1},
            )
        )

        with patch(
            "utils.clients.finance.service_client", return_value=_client_ctx(client)
        ):
            result = await ShopClient.list_products(offset=0, limit=5)

        assert result["items"][0]["uid"] == "p1"
        assert result["total"] == 1
        client.get.assert_awaited_once_with(
            "/products", params={"offset": 0, "limit": 5}
        )

    @pytest.mark.asyncio
    async def test_purchase_returns_redirect_url(self) -> None:
        client = _make_async_httpx_client(
            _mock_response(
                json_data={"redirect_url": "https://pay.example.com/checkout"},
            )
        )

        with patch(
            "utils.clients.finance.service_client", return_value=_client_ctx(client)
        ):
            url = await ShopClient.purchase("prod-1", "user-1", "https://t.me/bot")

        assert url == "https://pay.example.com/checkout"
        client.post.assert_awaited_once()


class TestSaasClient:
    @pytest.mark.asyncio
    async def test_get_quota(self) -> None:
        client = _make_async_httpx_client(
            _mock_response(
                json_data={"asset": "token", "quota": "100", "unit": "coins"},
            )
        )

        with patch(
            "utils.clients.finance.service_client", return_value=_client_ctx(client)
        ):
            result = await SaasClient.get_quota(asset="token", user_id="user-1")

        assert result["quota"] == "100"
        assert result["asset"] == "token"
