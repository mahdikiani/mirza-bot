"""Polling workers for bots.

Two modes:

1. **Bale fallback poller** (always-on in webhook mode):
   Runs every 60 s for bots with `needs_polling=True` (Bale).
   Acts as a safety net when Bale fails to deliver webhooks.

2. **Full polling mode** (`POLLING_MODE=1`):
   Replaces webhooks entirely. Polls ALL bots at a configurable
   interval (default 2 s). Use this for local development or
   environments where inbound HTTPS is not available.

Both modes use the same `bot.process_new_updates()` pipeline as the
webhook handler, so all handlers, middleware, and callbacks work
identically regardless of transport.

Double-processing is prevented by tracking `bot.last_update_id` and
passing `offset = last_update_id + 1` to `getUpdates`.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi_mongo_base.utils import basic

_BALE_FALLBACK_INTERVAL = 60  # seconds between Bale safety polls


# ---------------------------------------------------------------------------
# Shared low-level helper
# ---------------------------------------------------------------------------


async def _poll_once(bot: object) -> None:
    """Fetch and process pending updates for a single bot."""
    from apps.bots.base_bot import BaseBot

    if not isinstance(bot, BaseBot):
        return

    try:
        updates = await bot.get_updates(
            offset=bot.last_update_id + 1 if bot.last_update_id is not None else None,
            timeout=10,
            limit=100,
        )
    except Exception:
        logging.exception("Polling: failed to get updates for %s", bot.me)
        return

    if not updates:
        return

    for update in updates:
        if update.update_id > (bot.last_update_id or 0):
            bot.last_update_id = update.update_id

    logging.debug("Polling: %d updates for %s", len(updates), bot.me)
    await bot.process_new_updates(updates)


# ---------------------------------------------------------------------------
# Mode 1 — Bale fallback (60 s, only bots with needs_polling=True)
# ---------------------------------------------------------------------------


async def _bale_fallback_loop() -> None:
    from apps.bots.base_bot import BaseBot

    logging.info("Bale fallback poller started (interval=%ds)", _BALE_FALLBACK_INTERVAL)
    while True:
        await asyncio.sleep(_BALE_FALLBACK_INTERVAL)
        for bot_cls in basic.get_all_subclasses(BaseBot):
            try:
                bot = bot_cls()
                if bot.needs_polling:
                    await _poll_once(bot)
            except Exception:
                logging.exception("Bale fallback poller: error for %s", bot_cls)


def start_polling_worker() -> asyncio.Task:
    """Start the Bale fallback poller as a background task."""
    return asyncio.create_task(_bale_fallback_loop(), name="bale-fallback-poller")


# ---------------------------------------------------------------------------
# Mode 2 — Full polling mode (replaces webhooks, polls all bots)
# ---------------------------------------------------------------------------


async def _full_polling_loop(interval: float) -> None:
    from apps.bots.base_bot import BaseBot

    logging.info("Full polling mode active — polling all bots every %.1f s", interval)
    while True:
        for bot_cls in basic.get_all_subclasses(BaseBot):
            try:
                await _poll_once(bot_cls())
            except Exception:
                logging.exception("Full polling: error for %s", bot_cls)
        await asyncio.sleep(interval)


def start_full_polling_mode(interval: float = 2.0) -> asyncio.Task:
    """Start full polling mode as a background task (replaces webhooks)."""
    return asyncio.create_task(_full_polling_loop(interval), name="full-poller")
