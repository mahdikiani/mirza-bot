"""Async Redis client singleton for the bot service."""

from __future__ import annotations

import logging

from redis.asyncio import Redis

from .config import Settings

_client: Redis | None = None


async def get_redis() -> Redis:
    """Return the shared async Redis client, creating it on first call."""
    global _client
    if _client is None:
        uri = Settings().redis_uri
        _client = Redis.from_url(uri, decode_responses=True)
        try:
            await _client.ping()
            logging.info("Redis connected: %s", uri)
        except Exception:
            logging.exception("Redis connection failed: %s", uri)
            raise
    return _client


async def close_redis() -> None:
    """Gracefully close the Redis connection."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
