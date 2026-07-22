"""Tests for apps.ai.result_content_cache (Redis-backed raw-Markdown cache)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.ai import result_content_cache


class FakeRedis:
    """Minimal in-memory Redis replacement covering get/set with TTL."""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.expirations: dict[str, int] = {}

    async def set(self, name: str, value: str, ex: int | None = None) -> None:
        self.data[name] = value
        if ex is not None:
            self.expirations[name] = ex

    async def get(self, name: str) -> str | None:
        return self.data.get(name)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture(autouse=True)
def _patch_redis(fake_redis: FakeRedis):
    with patch("apps.ai.result_content_cache.get_redis", return_value=fake_redis):
        yield


@pytest.mark.asyncio
async def test_save_then_get_round_trips(fake_redis: FakeRedis) -> None:
    await result_content_cache.save(123, "**bold** markdown")

    assert await result_content_cache.get(123) == "**bold** markdown"


@pytest.mark.asyncio
async def test_save_sets_a_ttl(fake_redis: FakeRedis) -> None:
    await result_content_cache.save(123, "content")

    assert fake_redis.expirations["result_content:123"] == result_content_cache._DEFAULT_TTL


@pytest.mark.asyncio
async def test_get_missing_key_returns_none() -> None:
    assert await result_content_cache.get("nope") is None
