"""Database initialization helpers."""

from __future__ import annotations

from redis.asyncio import Redis

from .config import Settings


def _build_redis_client(redis_uri: str) -> Redis | None:
    """
    Build the async Redis client, or None if Redis isn't configured.

    decode_responses=True is required, not optional: fastapi_mongo_base's
    own init_redis() constructs a client without it, which makes
    hgetall()/smembers() return bytes keys/values -- pending_tasks.py and
    result_content_cache.py both index/compare those as plain str (e.g.
    data["meta_data"]), which raises KeyError/behaves wrong on every call
    with an undecoded client. Building our own client here instead of
    using that shared one is the fix. An empty redis_uri (as in the test
    environment, see conftest.py) means Redis-backed features are simply
    unavailable -- matches init_redis()'s own "not configured" behavior.
    """
    if not redis_uri:
        return None
    return Redis.from_url(
        redis_uri,
        socket_connect_timeout=1,
        socket_timeout=1,
        decode_responses=True,
    )


redis: Redis | None = _build_redis_client(Settings().redis_uri)


def get_redis() -> Redis | None:
    """Return the shared async Redis client, or None if Redis isn't configured."""
    return redis
