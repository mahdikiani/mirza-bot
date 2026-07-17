"""Tests for apps.ai.pending_tasks (Redis-backed async task store)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.ai import pending_tasks


class FakeRedisPipeline:
    """Mimics redis.asyncio.client.Pipeline — methods are sync (queue commands)."""

    def __init__(self, fake: FakeRedis) -> None:
        self._fake = fake
        self._commands: list[tuple[str, tuple, dict]] = []

    async def __aenter__(self) -> FakeRedisPipeline:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    def hset(self, name: str, mapping: dict) -> None:
        self._commands.append(("hset", (name,), {"mapping": mapping}))

    def expire(self, name: str, time: int) -> None:
        self._commands.append(("expire", (name,), {"time": time}))

    def sadd(self, name: str, member: str) -> None:
        self._commands.append(("sadd", (name,), {"member": member}))

    def delete(self, *names: str) -> None:
        self._commands.append(("delete", names, {}))

    def srem(self, name: str, member: str) -> None:
        self._commands.append(("srem", (name,), {"member": member}))

    async def execute(self) -> None:
        for cmd, args, kwargs in self._commands:
            method = getattr(self._fake, cmd)
            await method(*args, **kwargs)


class FakeRedis:
    """In-memory Redis replacement for pending_tasks tests."""

    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}
        self.sets: dict[str, set[str]] = {}
        self.expirations: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)

    async def hset(self, name: str, mapping: dict) -> None:
        self.data[name] = mapping

    async def hgetall(self, name: str) -> dict[str, str]:
        return self.data.get(name, {})

    async def expire(self, name: str, time: int) -> None:
        self.expirations[name] = time

    async def sadd(self, name: str, member: str) -> None:
        if name not in self.sets:
            self.sets[name] = set()
        self.sets[name].add(member)

    async def srem(self, name: str, member: str) -> None:
        if name in self.sets:
            self.sets[name].discard(member)

    async def smembers(self, name: str) -> set[str]:
        return self.sets.get(name, set())

    async def delete(self, *names: str) -> None:
        for name in names:
            self.data.pop(name, None)
            self.sets.pop(name, None)
            self.expirations.pop(name, None)


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


pytestmark = pytest.mark.usefixtures("_patch_redis")


@pytest.fixture
def _patch_redis(fake_redis: FakeRedis) -> None:
    with patch("apps.ai.pending_tasks.get_redis", return_value=fake_redis):
        yield


class TestPendingTasks:
    @pytest.mark.asyncio
    async def test_add_creates_task_in_redis(self, fake_redis: FakeRedis) -> None:
        await pending_tasks.add(
            task_uid="task-1",
            task_type="ocr",
            user_id="user-1",
            meta_data={"chat_id": 100, "bot_name": "test_bot"},
        )

        key = "pending_task:task-1"
        assert key in fake_redis.data
        assert fake_redis.data[key]["task_uid"] == "task-1"
        assert fake_redis.data[key]["task_type"] == "ocr"
        assert fake_redis.data[key]["user_id"] == "user-1"

    @pytest.mark.asyncio
    async def test_add_without_meta(self, fake_redis: FakeRedis) -> None:
        await pending_tasks.add(
            task_uid="task-2", task_type="transcribe", user_id="user-2"
        )

        data = fake_redis.data["pending_task:task-2"]
        assert data["meta_data"] == "null"

    @pytest.mark.asyncio
    async def test_add_indexes_task(self, fake_redis: FakeRedis) -> None:
        await pending_tasks.add("task-3", "ocr", "user-3")
        assert "task-3" in fake_redis.sets["pending_tasks:index"]

    @pytest.mark.asyncio
    async def test_add_sets_expiration(self, fake_redis: FakeRedis) -> None:
        await pending_tasks.add("task-4", "ocr", "user-4")
        assert "pending_task:task-4" in fake_redis.expirations

    @pytest.mark.asyncio
    async def test_get_returns_task(self) -> None:
        await pending_tasks.add("task-5", "ocr", "user-5", {"chat_id": 200})
        result = await pending_tasks.get("task-5")

        assert result is not None
        assert result["task_uid"] == "task-5"
        assert result["meta_data"] == {"chat_id": 200}

    @pytest.mark.asyncio
    async def test_get_returns_none_for_missing(self) -> None:
        assert await pending_tasks.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_remove_deletes_task(self, fake_redis: FakeRedis) -> None:
        await pending_tasks.add("task-6", "transcribe", "user-6")
        await pending_tasks.remove("task-6")

        assert "pending_task:task-6" not in fake_redis.data
        assert "task-6" not in fake_redis.sets.get("pending_tasks:index", set())

    @pytest.mark.asyncio
    async def test_all_pending_returns_active_tasks(
        self, fake_redis: FakeRedis
    ) -> None:
        await pending_tasks.add("t1", "ocr", "u1")
        await pending_tasks.add("t2", "transcribe", "u2")

        tasks = await pending_tasks.all_pending()

        assert len(tasks) == 2
        uids = {t["task_uid"] for t in tasks}
        assert uids == {"t1", "t2"}

    @pytest.mark.asyncio
    async def test_all_pending_returns_empty_when_no_tasks(self) -> None:
        assert await pending_tasks.all_pending() == []

    @pytest.mark.asyncio
    async def test_all_pending_cleans_stale_index(self, fake_redis: FakeRedis) -> None:
        # Add a task, then manually delete its data (simulating expiration)
        await pending_tasks.add("stale", "ocr", "u1")
        fake_redis.data.pop("pending_task:stale")

        tasks = await pending_tasks.all_pending()
        assert len(tasks) == 0
        assert "stale" not in fake_redis.sets.get("pending_tasks:index", set())

    @pytest.mark.asyncio
    async def test_all_pending_handles_set_missing(self, fake_redis: FakeRedis) -> None:
        fake_redis.sets.pop("pending_tasks:index", None)
        assert await pending_tasks.all_pending() == []
