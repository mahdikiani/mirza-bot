"""Database initialization helpers."""

from __future__ import annotations

from fastapi_mongo_base.core import db
from redis.asyncio import Redis

from .config import Settings

"""Async Redis client singleton for the bot service."""
redis_sync, redis = db.init_redis(Settings())


def get_redis() -> Redis:
    """Return the shared async Redis client."""
    return redis
