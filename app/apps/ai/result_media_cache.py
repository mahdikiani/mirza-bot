"""Short-lived cache of signed media URLs for delivered result messages."""

from __future__ import annotations

import json

from redis.asyncio import Redis

from server.db import get_redis

_KEY_PREFIX = "result_media:"
_DEFAULT_TTL = 24 * 3600


def _key(message_id: int | str) -> str:
    return f"{_KEY_PREFIX}{message_id}"


async def save(message_id: int | str, media_url: str) -> None:
    """Cache the signed media URL associated with a delivered result."""
    redis: Redis = get_redis()
    await redis.set(_key(message_id), media_url, ex=_DEFAULT_TTL)


async def get(message_id: int | str) -> str | None:
    """Return a cached media URL, if it is still available."""
    redis: Redis = get_redis()
    return await redis.get(_key(message_id))


async def save_metadata(
    message_id: int | str,
    *,
    content_type: str,
    media_url: str | None = None,
    docx_url: str | None = None,
    file_id: str | None = None,
) -> None:
    """Cache result metadata needed to rebuild its action keyboard."""
    redis: Redis = get_redis()
    await redis.set(
        _key(message_id),
        json.dumps(
            {
                "content_type": content_type,
                "media_url": media_url,
                "docx_url": docx_url,
                "file_id": file_id,
            }
        ),
        ex=_DEFAULT_TTL,
    )


async def get_metadata(message_id: int | str) -> dict[str, str | None] | None:
    """Return cached result metadata, supporting legacy URL-only entries."""
    redis: Redis = get_redis()
    value = await redis.get(_key(message_id))
    if not value:
        return None
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {"content_type": None, "media_url": value, "docx_url": None}
    return parsed if isinstance(parsed, dict) else None
