"""Background poller — fallback for when AI-service webhooks fail to fire.

Every POLL_INTERVAL seconds (default 60 s) we iterate all pending tasks
stored in Redis.  Tasks that have exceeded their TTL are automatically
expired by Redis, so we only need to handle the "still alive but maybe
completed" case.  If a task *is* completed we process it exactly as the
webhook handler would and then remove it from Redis.

Tasks whose submitted_at is older than MAX_TASK_AGE_SECONDS get a timeout
notification sent to the user before removal.
"""

from __future__ import annotations

import asyncio
import logging
import time

from apps.ai import pending_tasks

POLL_INTERVAL = 60  # seconds between each poll sweep
MAX_TASK_AGE_SECONDS = 3600  # 1 hour


async def _handle_completed_task(task: dict) -> None:
    """Fetch the result and deliver it to the user, then remove from Redis."""
    from apps.ai.clients import OCRClient, TranscribeClient
    from apps.ai.routes import (
        TaskWebhookPayload,
        _process_ocr_webhook,
        _process_transcribe_webhook,
    )

    meta = task.get("meta_data") or {}
    task_uid = task["task_uid"]
    task_type = task["task_type"]

    try:
        if task_type == "ocr":
            result = await OCRClient.get_result(task_uid)
            payload = TaskWebhookPayload(
                uid=task_uid,
                task_status="completed",
                meta_data=meta,
                result=result,
            )
            await _process_ocr_webhook(payload)
        elif task_type == "transcribe":
            result = await TranscribeClient.get_result(task_uid)
            payload = TaskWebhookPayload(
                uid=task_uid,
                task_status="completed",
                meta_data=meta,
                result=result,
            )
            await _process_transcribe_webhook(payload)
        else:
            logging.warning("Unknown task type %s for task %s", task_type, task_uid)
            return

        await pending_tasks.remove(task_uid)
        logging.info("Poller: task %s (%s) completed successfully", task_uid, task_type)

    except Exception:
        logging.exception("Poller: failed to process completed task %s", task_uid)


async def _notify_timeout(task: dict) -> None:
    """Send a timeout error message to the user and remove from Redis."""
    from apps.bots import handlers

    meta = task.get("meta_data") or {}
    task_uid = task["task_uid"]
    task_type = task["task_type"]
    chat_id = meta.get("chat_id")
    message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")

    if chat_id and bot_name:
        try:
            bot = handlers.get_bot(bot_name)
            await bot.edit_message_text(
                text=(
                    "متأسفانه پردازش درخواست شما بیش از حد طول کشید. "
                    "لطفاً دوباره امتحان کنید."
                ),
                chat_id=chat_id,
                message_id=message_id,
            )
        except Exception:
            logging.exception(
                "Poller: failed to send timeout message for task %s", task_uid
            )

    await pending_tasks.remove(task_uid)
    logging.warning("Poller: task %s (%s) timed out", task_uid, task_type)


async def _poll_once() -> None:
    """Single sweep: check all pending tasks."""
    from apps.ai.clients import OCRClient, TranscribeClient

    try:
        tasks = await pending_tasks.all_pending()
    except Exception:
        logging.exception("Poller: failed to fetch pending tasks")
        return

    if not tasks:
        return

    logging.debug("Poller: checking %d pending task(s)", len(tasks))
    now = time.time()

    for task in tasks:
        submitted_at = task.get("submitted_at", now)

        # Timeout check
        if now - submitted_at > MAX_TASK_AGE_SECONDS:
            await _notify_timeout(task)
            continue

        # Try to fetch the result — if the service raises, the task is still running
        try:
            if task["task_type"] == "ocr":
                await OCRClient.get_result(task["task_uid"])
            elif task["task_type"] == "transcribe":
                await TranscribeClient.get_result(task["task_uid"])
            else:
                continue

            # If we got here without an exception the task is done
            await _handle_completed_task(task)

        except Exception as exc:
            # A 4xx/5xx likely means still processing — log at debug level
            logging.debug("Poller: task %s still pending (%s)", task["task_uid"], exc)


async def run_task_poller() -> None:
    """Long-running coroutine — call from app lifespan."""
    logging.info(
        "Task poller started (interval=%ds, max_age=%ds)",
        POLL_INTERVAL,
        MAX_TASK_AGE_SECONDS,
    )
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        await _poll_once()
