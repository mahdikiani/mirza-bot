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

        result = await client.get_or_create_user_by_identifier(
            "telegram_id", "123", referrer_code="ignored"
        )

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
        official.create_users.assert_awaited_once_with({
            "identifier_type": "telegram_id",
            "identifier": "456",
        })

    @pytest.mark.asyncio
    async def test_get_or_create_user_passes_referrer_on_creation(self) -> None:
        official = AsyncMock()
        official.get_users = AsyncMock(return_value=[])
        official.create_users = AsyncMock(return_value=MagicMock(uid="user-new"))
        client = UssoAccountsClient(official)

        await client.get_or_create_user_by_identifier(
            "telegram_id", "456", referrer_code="friend-code"
        )

        official.create_users.assert_awaited_once_with({
            "identifier_type": "telegram_id",
            "identifier": "456",
            "referral_code": "friend-code",
        })

    @pytest.mark.asyncio
    async def test_get_my_referral_code_returns_code(self) -> None:
        official = AsyncMock()
        resp = _mock_response(
            json_data={"items": [{"code": "mine-123"}], "total": 1}
        )
        official.get = AsyncMock(return_value=resp)
        official.post = AsyncMock()
        client = UssoAccountsClient(official)

        result = await client.get_my_referral_code("user-1")

        assert result == "mine-123"
        official.get.assert_awaited_once_with(
            "/api/sso/v1/referrals",
            params={"user_id": "user-1"},
            timeout=20,
        )
        official.post.assert_not_awaited()
        resp.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_my_referral_code_creates_when_missing(self) -> None:
        official = AsyncMock()
        get_resp = _mock_response(json_data={"items": [], "total": 0})
        post_resp = _mock_response(
            json_data={"code": "new-code-1", "user_id": "user-1"}
        )
        official.get = AsyncMock(return_value=get_resp)
        official.post = AsyncMock(return_value=post_resp)
        client = UssoAccountsClient(official)

        result = await client.get_my_referral_code("user-1")

        assert result == "new-code-1"
        official.get.assert_awaited_once_with(
            "/api/sso/v1/referrals",
            params={"user_id": "user-1"},
            timeout=20,
        )
        official.post.assert_awaited_once_with(
            "/api/sso/v1/referrals",
            json={"user_id": "user-1"},
        )
        get_resp.raise_for_status.assert_called_once()
        post_resp.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_my_referral_code_swallows_errors(self) -> None:
        official = AsyncMock()
        official.get = AsyncMock(side_effect=RuntimeError("usso down"))
        client = UssoAccountsClient(official)

        assert await client.get_my_referral_code("user-1") is None

    @pytest.mark.asyncio
    async def test_create_team_workspace_posts_name(self) -> None:
        official = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"uid": "ws-1", "name": "Team X"}
        official.post = AsyncMock(return_value=resp)
        client = UssoAccountsClient(official)

        result = await client.create_team_workspace("Team X")

        assert result == {"uid": "ws-1", "name": "Team X"}
        official.post.assert_awaited_once_with(
            "/api/sso/v1/workspaces", json={"name": "Team X"}
        )
        resp.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_add_workspace_member_posts_user_and_role(self) -> None:
        official = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"uid": "user-1", "roles": ["member"]}
        official.post = AsyncMock(return_value=resp)
        client = UssoAccountsClient(official)

        result = await client.add_workspace_member("ws-1", "user-1", role="member")

        assert result == {"uid": "user-1", "roles": ["member"]}
        official.post.assert_awaited_once_with(
            "/api/sso/v1/workspaces/ws-1/members",
            json={"user_id": "user-1", "role": "member"},
        )

    @pytest.mark.asyncio
    async def test_remove_workspace_member_deletes(self) -> None:
        official = AsyncMock()
        resp = MagicMock()
        official.delete = AsyncMock(return_value=resp)
        client = UssoAccountsClient(official)

        await client.remove_workspace_member("ws-1", "user-1")

        official.delete.assert_awaited_once_with(
            "/api/sso/v1/workspaces/ws-1/members/user-1"
        )
        resp.raise_for_status.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_workspace_members_returns_items(self) -> None:
        official = AsyncMock()
        resp = MagicMock()
        resp.json.return_value = {"items": [{"uid": "user-1"}], "total": 1}
        official.get = AsyncMock(return_value=resp)
        client = UssoAccountsClient(official)

        result = await client.list_workspace_members("ws-1")

        assert result == [{"uid": "user-1"}]
        official.get.assert_awaited_once_with(
            "/api/sso/v1/workspaces/ws-1/users", timeout=20
        )

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

    @pytest.mark.asyncio
    async def test_redeem_gift_code(self) -> None:
        client = _make_async_httpx_client(
            _mock_response(json_data={"status": "rewarded", "reward_coins": 10})
        )

        with patch(
            "utils.clients.finance.service_client", return_value=_client_ctx(client)
        ):
            result = await ShopClient.redeem_gift_code("gift-1", "user-1")

        assert result == {"status": "rewarded", "reward_coins": 10}
        client.post.assert_awaited_once_with(
            "/rewards/gift-codes/redeem",
            json={"code": "gift-1", "redeeming_user_id": "user-1"},
        )

    @pytest.mark.asyncio
    async def test_create_gift_code(self) -> None:
        client = _make_async_httpx_client(
            _mock_response(json_data={"code": "gift-1"})
        )

        with patch(
            "utils.clients.finance.service_client", return_value=_client_ctx(client)
        ):
            result = await ShopClient.create_gift_code(25)

        assert result == {"code": "gift-1"}
        client.post.assert_awaited_once_with(
            "/rewards/gift-codes",
            json={"max_uses": 25},
        )


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
