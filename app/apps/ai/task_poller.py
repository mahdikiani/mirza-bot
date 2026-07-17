"""Background poller — fallback for when AI-service webhooks fail to fire."""

from __future__ import annotations

import asyncio
import logging
import time

from apps.ai import pending_tasks
from apps.ai.schemas import TaskWebhookPayload
from utils.i18n import text

POLL_INTERVAL = 30
MAX_TASK_AGE_SECONDS = 3600

logger = logging.getLogger(__name__)


async def _handle_completed_task(task: dict) -> None:
    from apps.ai.clients import (
        OCRClient,
        PrompticClient,
        TranscribeClient,
        WebpageClient,
        YoutubeClient,
    )
    from apps.ai.routes import _deliver_result

    meta = task.get("meta_data") or {}
    task_uid = task["task_uid"]
    task_type = task["task_type"]

    try:
        if task_type == "ocr":
            result = await OCRClient.get_result(task_uid)
            content_type = "document"
        elif task_type == "transcribe":
            result = await TranscribeClient.get_result(task_uid)
            content_type = "voice"
        elif task_type == "youtube":
            result = await YoutubeClient.get_result(task_uid)
            content_type = "url"
        elif task_type == "webpage":
            result = await WebpageClient.get_result(task_uid)
            content_type = "url"
        elif task_type == "promptic":
            result = await PrompticClient.get_result(task_uid)
            content_type = "promptic"
        else:
            logger.warning("Unknown task type %s for task %s", task_type, task_uid)
            return

        payload = TaskWebhookPayload(
            uid=task_uid,
            task_status="completed",
            meta_data=meta,
            result=result,
        )
        await _deliver_result(payload, content_type)
        await pending_tasks.remove(task_uid)
        logger.info("Poller: task %s (%s) completed", task_uid, task_type)

    except Exception:
        logger.exception("Poller: failed to process completed task %s", task_uid)


async def _notify_timeout(task: dict) -> None:
    from apps.bots.common.renderer_registry import get_renderer

    meta = task.get("meta_data") or {}
    task_uid = task["task_uid"]
    chat_id = meta.get("chat_id")
    message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    locale = meta.get("locale", "fa")

    if chat_id and bot_name:
        renderer = get_renderer(str(bot_name))
        if renderer:
            try:
                await renderer.edit_message(
                    chat_id,
                    message_id,
                    text("messages.task_timeout", locale=locale),
                )
            except Exception:
                logger.exception("Poller: failed to send timeout for task %s", task_uid)
        else:
            logger.error("Poller: no renderer for bot %s (timeout)", bot_name)

    await pending_tasks.remove(task_uid)
    logger.warning("Poller: task %s timed out", task_uid)


async def _poll_once() -> None:
    from apps.ai.routes import _deliver_result
    from utils.clients.toolkit import toolkit_client

    try:
        tasks = await pending_tasks.all_pending()
    except Exception:
        logger.exception("Poller: failed to fetch pending tasks")
        return

    if not tasks:
        return

    now = time.time()

    ct_map = {
        "ocr": "document",
        "transcribe": "voice",
        "youtube": "url",
        "webpage": "url",
        "promptic": "promptic",
    }
    fetch_map = {
        "ocr": ("/ocrs", "OCR"),
        "transcribe": ("/transcribes", "Transcribe"),
        "youtube": ("/youtube", "YouTube"),
        "webpage": ("/webpages", "Webpage"),
        "promptic": ("/promptic", "Promptic"),
    }

    for task in tasks:
        submitted_at = task.get("submitted_at", now)
        if now - submitted_at > MAX_TASK_AGE_SECONDS:
            await _notify_timeout(task)
            continue

        endpoint, label = fetch_map.get(task["task_type"], (None, None))
        if not endpoint:
            continue

        try:
            async with toolkit_client() as c:
                resp = await c.get(f"{endpoint}/{task['task_uid']}")
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.debug("Poller: failed to fetch %s task %s", label, task["task_uid"])
            continue

        status = data.get("task_status")
        if status == "completed":
            result = data.get("result") or ""
            if result:
                task_meta = task.get("meta_data") or {}
                payload = TaskWebhookPayload(
                    uid=task["task_uid"],
                    task_status="completed",
                    meta_data=task_meta,
                    result=result,
                )
                ct = ct_map.get(task["task_type"], "document")
                await _deliver_result(payload, ct)
                await pending_tasks.remove(task["task_uid"])
                logger.info("Poller: %s task %s completed", label, task["task_uid"])
        elif status == "error":
            task_meta = task.get("meta_data") or {}
            error_result = data.get("result") or data.get("error") or "Unknown error"
            logger.warning(
                "Poller: %s task %s error: %s",
                label,
                task["task_uid"],
                error_result[:200],
            )
            payload = TaskWebhookPayload(
                uid=task["task_uid"],
                task_status="error",
                meta_data=task_meta,
                result=error_result,
            )
            ct = ct_map.get(task["task_type"], "document")
            await _deliver_result(payload, ct)
            await pending_tasks.remove(task["task_uid"])


async def run_task_poller() -> None:
    """Long-running coroutine — call from app lifespan."""
    logger.info(
        "Task poller started (interval=%ds, max_age=%ds)",
        POLL_INTERVAL,
        MAX_TASK_AGE_SECONDS,
    )
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        await _poll_once()


def start_task_poller() -> None:
    """Start the long-running task poller without blocking app startup."""
    task = asyncio.create_task(run_task_poller(), name="ai-task-poller")

    def _log_result(done: asyncio.Task) -> None:
        if done.cancelled():
            return
        try:
            done.result()
        except Exception:
            logger.exception("Task poller failed")

    task.add_done_callback(_log_result)
