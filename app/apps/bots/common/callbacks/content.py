"""Shared content lookup for callback handlers."""

from __future__ import annotations

import logging

from apps.ai import result_content_cache
from apps.bots.common.events import CallbackEvent
from apps.bots.common.handler_context import BotRuntimeContext

logger = logging.getLogger(__name__)


async def get_content(event: CallbackEvent, ctx: BotRuntimeContext) -> str:
    """
    Get the raw Markdown content the callback's message was delivered with.

    Prefers the cache saved at delivery time (see result_content_cache):
    once a result is sent as real rich text (bold/italic entities), the
    platform strips the literal Markdown syntax from the message's plain
    text, so re-reading it back via download_document no longer contains
    the "# "/"**" markers the convert-to-file handlers depend on.
    """
    if event.message_id:
        try:
            cached = await result_content_cache.get(event.message_id)
        except Exception:
            logger.debug("Result content cache lookup failed for %s", event.message_id)
            cached = None
        if cached:
            return cached
        doc_bytes = await ctx.renderer.download_document(
            event.chat_id, event.message_id
        )
        if doc_bytes:
            return doc_bytes.decode("utf-8", errors="replace")
    return event.message_text or ""
