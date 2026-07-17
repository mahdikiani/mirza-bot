"""
Redis-backed store for pending AI tasks (OCR / transcribe).

Replaces the old MongoDB PendingTask model with a lightweight Redis
implementation.  Each task is stored as a hash with automatic TTL so
timed-out tasks simply expire — no manual cleanup needed.

A Redis SET (``_INDEX_KEY``) keeps track of all active task UIDs so we
can iterate without ``SCAN``.
"""

from __future__ import annotations

import json
import logging
import time

from redis.asyncio import Redis

from server.db import get_redis

_KEY_PREFIX = "pending_task:"
_INDEX_KEY = "pending_tasks:index"
_DEFAULT_TTL = 3600  # 1 hour — matches MAX_TASK_AGE_SECONDS in poller


def _key(task_uid: str) -> str:
    return f"{_KEY_PREFIX}{task_uid}"


async def add(
    task_uid: str,
    task_type: str,
    user_id: str,
    meta_data: dict | None = None,
) -> None:
    """Register a new pending task."""
    redis: Redis = get_redis()
    key = _key(task_uid)
    value = {
        "task_uid": task_uid,
        "task_type": task_type,
        "user_id": user_id,
        "meta_data": json.dumps(meta_data) if meta_data else "null",
        "submitted_at": time.time(),
    }
    async with redis.pipeline(transaction=True) as pipe:
        pipe.hset(key, mapping=value)
        pipe.expire(key, _DEFAULT_TTL)
        pipe.sadd(_INDEX_KEY, task_uid)
        await pipe.execute()
    logging.debug("Pending task added: %s (%s)", task_uid, task_type)


async def get(task_uid: str) -> dict | None:
    """Fetch a single pending task, or ``None`` if expired / missing."""
    redis: Redis = get_redis()
    data = await redis.hgetall(_key(task_uid))
    if not data:
        return None
    data["meta_data"] = json.loads(data["meta_data"])
    data["submitted_at"] = float(data["submitted_at"])
    return data


async def remove(task_uid: str) -> None:
    """Delete a task (e.g. after completion or timeout notification)."""
    redis: Redis = get_redis()
    async with redis.pipeline(transaction=True) as pipe:
        pipe.delete(_key(task_uid))
        pipe.srem(_INDEX_KEY, task_uid)
        await pipe.execute()


async def all_pending() -> list[dict]:
    """Return every task that is still alive in Redis."""
    redis: Redis = get_redis()
    uids: set[str] = await redis.smembers(_INDEX_KEY)
    if not uids:
        return []

    tasks: list[dict] = []
    stale: list[str] = []

    for uid in uids:
        data = await redis.hgetall(_key(uid))
        if not data:
            # Key expired but index entry remains — clean up
            stale.append(uid)
            continue
        data["meta_data"] = json.loads(data["meta_data"])
        data["submitted_at"] = float(data["submitted_at"])
        tasks.append(data)

    if stale:
        await redis.srem(_INDEX_KEY, *stale)

    return tasks
