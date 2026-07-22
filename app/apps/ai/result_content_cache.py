"""Redis-backed cache of raw Markdown result content, keyed by delivered
message_id.

"Convert to Word/Markdown" buttons need the original Markdown of a
previously delivered result. Re-reading it back from the Telegram/Bale
message itself doesn't work once the message is sent as real rich text
(bold/italic entities): the platform strips the literal ``**``/``#``
syntax from the message's plain-text copy, which the simple Markdown-to-
DOCX converter depends on to detect headings/lists. Caching the raw
Markdown at delivery time sidesteps that entirely.
"""

from __future__ import annotations

from redis.asyncio import Redis

from server.db import get_redis

_KEY_PREFIX = "result_content:"
_DEFAULT_TTL = 24 * 3600  # long enough for a user to come back and convert later


def _key(message_id: int | str) -> str:
    return f"{_KEY_PREFIX}{message_id}"


async def save(message_id: int | str, content: str) -> None:
    """Cache the raw Markdown for a delivered message."""
    redis: Redis = get_redis()
    await redis.set(_key(message_id), content, ex=_DEFAULT_TTL)


async def get(message_id: int | str) -> str | None:
    """Return the cached raw Markdown for a message, or None if missing/expired."""
    redis: Redis = get_redis()
    return await redis.get(_key(message_id))
