"""Bale webhook routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request

from apps.bots.bale.handler import handle_bale_update
from utils.webhook_auth import require_webhook_api_key

router = APIRouter(prefix="/bale", tags=["Bale"])
_background_tasks: set[asyncio.Task[None]] = set()


@router.post("/webhook/{bot_name}", dependencies=[Depends(require_webhook_api_key)])
async def bale_webhook(bot_name: str, request: Request) -> dict[str, str]:
    """Receive Bale webhook updates and dispatch to shared handlers."""
    payload = await request.json()
    task = asyncio.create_task(handle_bale_update(payload, bot_name))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"status": "ok"}
