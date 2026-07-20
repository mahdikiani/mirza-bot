"""Webhook endpoints called by internal services when async tasks complete."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends

from apps.ai.schemas import TaskWebhookPayload
from apps.bots.common import keyboards as kb
from apps.bots.common.delivery import deliver_md_result, is_insufficient_credit_error
from apps.bots.common.renderer_registry import get_renderer
from utils.i18n import text
from utils.webhook_auth import require_webhook_api_key

router = APIRouter(
    prefix="/ai",
    tags=["AI Webhooks"],
    dependencies=[Depends(require_webhook_api_key)],
)
logger = logging.getLogger(__name__)

__all__ = [
    "TaskWebhookPayload",
    "_deliver_result",
    "_notify_task_error",
    "_process_ocr_webhook",
    "_process_transcribe_webhook",
    "router",
]


async def _fetch_task_result(
    payload: TaskWebhookPayload, content_type: str
) -> str | None:
    try:
        if content_type == "document":
            from apps.ai.clients import OCRClient

            return await OCRClient.get_result(payload.uid)
        if content_type == "voice":
            from apps.ai.clients import TranscribeClient

            return await TranscribeClient.get_result(payload.uid)
    except Exception:
        logger.exception("Failed to fetch %s result for %s", content_type, payload.uid)
    return None


async def _deliver_result(payload: TaskWebhookPayload, content_type: str) -> None:
    from apps.ai import pending_tasks

    if payload.task_status == "error":
        await _notify_task_error(payload)
        return

    if payload.task_status != "completed":
        logger.warning("Task %s status=%s ignored", payload.uid, payload.task_status)
        return

    meta = payload.meta_data or {}
    if not meta:
        pending = await pending_tasks.get(payload.uid)
        meta = pending.get("meta_data") if pending else {}

    chat_id = meta.get("chat_id")
    response_message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    user_id = meta.get("user_id")
    locale = meta.get("locale", "fa")

    if not (chat_id and bot_name):
        logger.error("Webhook missing chat_id/bot_name: %s", meta)
        return

    result = payload.result or ""
    if not result:
        result = await _fetch_task_result(payload, content_type) or ""
    if not result:
        logger.error("Webhook completed but empty result for %s", payload.uid)
        return

    renderer = get_renderer(str(bot_name))
    if not renderer:
        logger.error("No renderer registered for bot %s", bot_name)
        return

    await deliver_md_result(
        renderer,
        chat_id=chat_id,
        message_id=response_message_id,
        result=result,
        content_type=content_type,
        user_id=str(user_id) if user_id else None,
        locale=str(locale),
        file_name_hint=meta.get("file_name_hint"),
        reply_to=meta.get("reply_to_message_id"),
    )
    await pending_tasks.remove(payload.uid)


async def _notify_task_error(payload: TaskWebhookPayload) -> None:
    from apps.ai import pending_tasks

    meta = payload.meta_data or {}
    if not meta:
        pending = await pending_tasks.get(payload.uid)
        meta = pending.get("meta_data") if pending else {}

    chat_id = meta.get("chat_id")
    message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    locale = meta.get("locale", "fa")

    error_text = (
        payload.task_report
        or payload.error
        or text("messages.task_error", locale=locale)
    )

    renderer = get_renderer(str(bot_name)) if bot_name else None
    if chat_id and bot_name and renderer:
        try:
            keyboard = (
                kb.buy_credits_keyboard()
                if is_insufficient_credit_error(error_text)
                else None
            )
            await renderer.edit_message(
                chat_id,
                message_id,
                error_text,
                inline_keyboard=keyboard,
            )
        except Exception:
            logger.exception("Failed to notify task error for %s", payload.uid)
    elif chat_id and bot_name:
        logger.error("No renderer registered for bot %s (task error)", bot_name)

    await pending_tasks.remove(payload.uid)


async def _process_ocr_webhook(payload: TaskWebhookPayload) -> None:
    await _deliver_result(payload, "document")


async def _process_transcribe_webhook(payload: TaskWebhookPayload) -> None:
    await _deliver_result(payload, "voice")


@router.post("/ocr/webhook/")
async def ocr_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "document")
    return {"status": "accepted"}


@router.post("/transcribe/webhook/")
async def transcribe_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "voice")
    return {"status": "accepted"}


@router.post("/webpage/webhook/")
async def webpage_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "url")
    return {"status": "accepted"}


@router.post("/youtube/webhook/")
async def youtube_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "url")
    return {"status": "accepted"}


@router.post("/promptic/webhook/")
async def promptic_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "promptic")
    return {"status": "accepted"}
