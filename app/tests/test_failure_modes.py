"""Failure-mode tests for webhook auth and poller offset handling."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from apps.bots.runtime import poller
from server.config import Settings


@dataclass
class MockUpdate:
    update_id: int
    message: object | None = None
    callback_query: object | None = None


@pytest.mark.asyncio
async def test_ai_webhook_rejects_invalid_api_key(client: httpx.AsyncClient) -> None:
    with patch.object(Settings, "webhook_api_key", "secret-key"):
        resp = await client.post(
            "/ai/ocr/webhook/",
            json={"uid": "t1", "task_status": "completed", "result": "x"},
            headers={"x-api-key": "wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_ai_webhook_accepts_valid_api_key(client: httpx.AsyncClient) -> None:
    with (
        patch.object(Settings, "webhook_api_key", "secret-key"),
        patch("apps.ai.routes._deliver_result", AsyncMock()),
    ):
        resp = await client.post(
            "/ai/ocr/webhook/",
            json={"uid": "t1", "task_status": "completed", "result": "x"},
            headers={"x-api-key": "secret-key"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_bale_webhook_rejects_invalid_api_key(client: httpx.AsyncClient) -> None:
    with patch.object(Settings, "webhook_api_key", "secret-key"):
        resp = await client.post(
            "/bale/webhook/test_bot",
            json={"message": {"message_id": 1}},
            headers={"x-api-key": "wrong"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_poller_advances_offset_only_after_process() -> None:
    bot = AsyncMock()
    bot.last_update_id = None
    bot.me = "test_bot"
    bot.bot_type = "bale"
    update = MockUpdate(update_id=7)
    bot.get_updates = AsyncMock(return_value=[update])
    bot.process_new_updates = AsyncMock()

    process = AsyncMock()
    with patch("apps.bots.runtime.poller._process_updates", process):
        await poller._poll_once(bot)

    process.assert_awaited_once_with(bot, [update])
    assert bot.last_update_id == 7


@pytest.mark.asyncio
async def test_poller_does_not_advance_when_fetch_fails() -> None:
    bot = AsyncMock()
    bot.last_update_id = 3
    bot.me = "test_bot"
    bot.get_updates = AsyncMock(side_effect=Exception("network"))

    await poller._poll_once(bot)
    assert bot.last_update_id == 3
