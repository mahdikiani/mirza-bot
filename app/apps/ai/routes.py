"""Webhook endpoints called by internal services when async tasks complete."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

router = APIRouter(prefix="/ai", tags=["AI Webhooks"])


class TaskWebhookPayload(BaseModel):
    uid: str
    task_status: str | None = None
    meta_data: dict | None = None
    result: str | None = None
    file_url: str | None = None


# ---------------------------------------------------------------------------
# OCR webhook
# ---------------------------------------------------------------------------


async def _process_ocr_webhook(payload: TaskWebhookPayload) -> None:
    from apps.bots import handlers
    from utils.clients import OCRClient

    logging.info(
        "OCR webhook received for task %s status=%s", payload.uid, payload.task_status
    )

    if payload.task_status != "completed":
        logging.warning(
            "OCR task %s is not completed: %s", payload.uid, payload.task_status
        )
        return

    meta = payload.meta_data or {}
    chat_id = meta.get("chat_id")
    response_message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    content_type = meta.get("content_type", "document")
    user_id = meta.get("user_id")

    if not (chat_id and bot_name):
        logging.error("OCR webhook missing chat_id/bot_name in meta_data: %s", meta)
        return

    try:
        result = payload.result or await OCRClient.get_result(payload.uid)
    except Exception:
        logging.exception("Failed to fetch OCR result for task %s", payload.uid)
        return

    bot = handlers.get_bot(bot_name)
    from apps.bots.services import send_md_result

    await send_md_result(
        bot=bot,
        chat_id=chat_id,
        response_message_id=response_message_id,
        result=result,
        content_type=content_type,
        user_id=user_id,
    )


@router.post("/ocr/webhook/")
async def ocr_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_process_ocr_webhook, payload)
    return {"status": "accepted"}


# ---------------------------------------------------------------------------
# Transcribe webhook
# ---------------------------------------------------------------------------


async def _process_transcribe_webhook(payload: TaskWebhookPayload) -> None:
    from apps.bots import handlers
    from utils.clients import TranscribeClient

    logging.info(
        "Transcribe webhook received for task %s status=%s",
        payload.uid,
        payload.task_status,
    )

    if payload.task_status != "completed":
        logging.warning(
            "Transcribe task %s is not completed: %s", payload.uid, payload.task_status
        )
        return

    meta = payload.meta_data or {}
    chat_id = meta.get("chat_id")
    response_message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    content_type = meta.get("content_type", "voice")
    user_id = meta.get("user_id")

    if not (chat_id and bot_name):
        logging.error("Transcribe webhook missing chat_id/bot_name: %s", meta)
        return

    try:
        result = payload.result or await TranscribeClient.get_result(payload.uid)
    except Exception:
        logging.exception("Failed to fetch transcribe result for task %s", payload.uid)
        return

    bot = handlers.get_bot(bot_name)
    from apps.bots.services import send_md_result

    await send_md_result(
        bot=bot,
        chat_id=chat_id,
        response_message_id=response_message_id,
        result=result,
        content_type=content_type,
        user_id=user_id,
    )


@router.post("/transcribe/webhook/")
async def transcribe_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_process_transcribe_webhook, payload)
    return {"status": "accepted"}
