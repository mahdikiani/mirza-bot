"""Webhook endpoints called by internal services when async tasks complete."""


from __future__ import annotations

import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends

from apps.ai.schemas import TaskWebhookPayload
from apps.bots.common import keyboards as kb
from apps.bots.common.delivery import (
    deliver_docx_first_result,
    deliver_md_result,
    is_insufficient_credit_error,
)
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
    "_notify_task_progress",
    "_process_ocr_webhook",
    "_process_transcribe_webhook",
    "router",
]

_PAGE_PROGRESS_RE = re.compile(r"^(\d+)/(\d+)")


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


async def _resolve_delivery_meta(payload: TaskWebhookPayload) -> dict:
    """
    Delivery routing uses pending-task meta only.

    Missing pending meta for ``payload.uid`` rejects delivery — there is no
    fallback to ``payload.meta_data`` (fail-closed).
    """
    from apps.ai import pending_tasks

    try:
        pending = await pending_tasks.get(payload.uid)
    except Exception:
        logger.exception("Failed to load pending meta for %s", payload.uid)
        return {}

    if not pending:
        logger.error(
            "Webhook %s rejected: no pending meta (payload meta ignored)",
            payload.uid,
        )
        return {}

    pending_meta = dict(pending.get("meta_data") or {})
    if not pending_meta:
        logger.error(
            "Webhook %s rejected: pending record has empty meta_data",
            payload.uid,
        )
    return pending_meta


async def _empty_result_error(
    payload: TaskWebhookPayload, meta: dict, locale: str
) -> None:
    await _notify_task_error(
        TaskWebhookPayload(
            uid=payload.uid,
            task_status="error",
            meta_data=meta,
            task_report=text("messages.task_error", locale=str(locale)),
        )
    )


async def _apply_user_prompt(
    result: str,
    *,
    user_prompt: str,
    meta: dict,
    locale: str,
    renderer: object,
    chat_id: object,
) -> str:
    from apps.bots.common.context import (
        InsufficientCreditsError,
        extracted_content_completion,
        notify_admin_insufficient_credits,
    )

    try:
        return await extracted_content_completion(
            result,
            user_prompt,
            sender_id=meta.get("platform_user_id") or meta.get("telegram_user_id"),
            user_id=meta.get("user_id"),
            workspace_id=meta.get("workspace_id") or meta.get("user_id"),
            audit_source=f"{meta.get('content_type') or 'task'}_webhook_prompt",
            locale=str(locale),
        )
    except InsufficientCreditsError:
        await notify_admin_insufficient_credits(renderer, chat_id)
        return text("messages.insufficient_credits", locale=str(locale))


async def _store_completed_delivery(
    *,
    meta: dict,
    chat_id: object,
    delivered_message_id: object,
    result: str,
    user_id: object,
    content_type: str,
    message_content: str = "",
) -> None:
    from apps.bots.common.context import store_artifact_message

    workspace_id = str(meta.get("workspace_id") or user_id)
    file_name_hint = str(meta.get("file_name_hint") or "") or None
    base_name = None
    if file_name_hint:
        base_name = file_name_hint.rsplit(".", 1)[0]
    await store_artifact_message(
        platform=str(meta.get("platform") or "telegram"),
        platform_chat_id=str(chat_id),
        platform_message_id=str(delivered_message_id),
        reply_to_platform_message_id=(
            str(meta.get("reply_to_message_id"))
            if meta.get("reply_to_message_id") is not None
            else None
        ),
        user_id=str(user_id),
        workspace_id=workspace_id,
        source_type=content_type,
        artifact_content=result,
        message_content=message_content,
        original_name=file_name_hint,
        base_name=base_name,
        meta_data={"task_uid": meta.get("task_uid")},
    )


async def _deliver_completed_content(
    *,
    payload: TaskWebhookPayload,
    content_type: str,
    meta: dict,
    renderer: object,
    chat_id: object,
    response_message_id: object,
    result: str,
    artifact_content: str,
    user_id: object,
    locale: str,
    user_prompt: str,
) -> None:
    from apps.ai import pending_tasks

    if content_type == "promptic" and meta.get("action_name") == "minutes":
        delivered_message_id = await deliver_docx_first_result(
            renderer,
            chat_id=chat_id,
            message_id=meta.get("reply_to_message_id") or response_message_id,
            result=result,
            content_type=content_type,
            user_id=str(user_id) if user_id else None,
            workspace_id=str(meta.get("workspace_id") or "") or None,
            locale=str(locale),
            file_name_hint=meta.get("file_name_hint"),
            include_actions=not user_prompt,
            processing_message_id=response_message_id,
            docx_title=text("buttons.minutes", locale=str(locale)),
        )
        if delivered_message_id and user_id:
            await _store_completed_delivery(
                meta=meta,
                chat_id=chat_id,
                delivered_message_id=delivered_message_id,
                result=artifact_content,
                user_id=user_id,
                content_type=content_type,
                message_content=result if user_prompt else "",
            )
        await pending_tasks.remove(payload.uid)
        return

    delivered_message_id = await deliver_md_result(
        renderer,
        chat_id=chat_id,
        message_id=response_message_id,
        result=result,
        content_type=content_type,
        user_id=str(user_id) if user_id else None,
        workspace_id=str(meta.get("workspace_id") or "") or None,
        locale=str(locale),
        file_name_hint=meta.get("file_name_hint"),
        reply_to=meta.get("reply_to_message_id"),
        include_actions=not user_prompt,
        processing_message_id=response_message_id,
        docx_url=(
            (payload.provider_meta or {}).get("docx_url")
            if payload.provider_meta
            else None
        ),
    )
    if delivered_message_id and user_id:
        await _store_completed_delivery(
            meta=meta,
            chat_id=chat_id,
            delivered_message_id=delivered_message_id,
            result=artifact_content,
            user_id=user_id,
            content_type=content_type,
            message_content=result if user_prompt else "",
        )
    await pending_tasks.remove(payload.uid)


def _apply_provider_file_name(
    meta: dict, payload: TaskWebhookPayload, content_type: str
) -> None:
    """Attach a stable visible filename from provider metadata."""
    if content_type not in {"youtube", "url"} or meta.get("file_name_hint"):
        return
    provider_meta = payload.provider_meta or {}
    title = str(provider_meta.get("title") or "").strip()
    if title:
        meta["file_name_hint"] = title
        return
    video_id = str(provider_meta.get("video_id") or "").strip()
    meta["file_name_hint"] = (
        f"youtube_{video_id}" if video_id else "webpage"
    )


async def _deliver_result(payload: TaskWebhookPayload, content_type: str) -> None:
    from apps.ai import pending_tasks

    if payload.task_status == "error":
        await _notify_task_error(payload)
        return

    if payload.task_status != "completed":
        if payload.task_status == "processing" and payload.task_progress is not None:
            await _notify_task_progress(payload)
            return
        logger.warning("Task %s status=%s ignored", payload.uid, payload.task_status)
        return

    meta = await _resolve_delivery_meta(payload)
    _apply_provider_file_name(meta, payload, content_type)
    chat_id = meta.get("chat_id")
    response_message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    user_id = meta.get("user_id")
    locale = meta.get("locale", "fa")
    user_prompt = str(meta.get("user_prompt") or "").strip()

    if not (chat_id and bot_name):
        logger.error("Webhook missing chat_id/bot_name for %s: %s", payload.uid, meta)
        await pending_tasks.remove(payload.uid)
        return

    result = payload.result or ""
    if not result:
        result = await _fetch_task_result(payload, content_type) or ""
    if not result:
        logger.error("Webhook completed but empty result for %s", payload.uid)
        await _empty_result_error(payload, meta, str(locale))
        return

    renderer = get_renderer(str(bot_name))
    if not renderer:
        logger.error("No renderer registered for bot %s", bot_name)
        try:
            await _empty_result_error(payload, meta, str(locale))
        except Exception:
            logger.exception("Failed to notify missing-renderer for %s", payload.uid)
            await pending_tasks.remove(payload.uid)
        return

    artifact_content = result
    if user_prompt:
        result = await _apply_user_prompt(
            result,
            user_prompt=user_prompt,
            meta=meta,
            locale=str(locale),
            renderer=renderer,
            chat_id=chat_id,
        )

    await _deliver_completed_content(
        payload=payload,
        content_type=content_type,
        meta=meta,
        renderer=renderer,
        chat_id=chat_id,
        response_message_id=response_message_id,
        result=result,
        artifact_content=artifact_content,
        user_id=user_id,
        locale=str(locale),
        user_prompt=user_prompt,
    )


async def _insufficient_quota_message(user_id: str | None, locale: str) -> str:
    """Friendly, actionable message for an insufficient-quota task failure."""
    if not user_id:
        return text("messages.insufficient_credits", locale=locale)
    from utils.clients.finance import SaasClient

    try:
        data = await SaasClient.get_quota("coin", user_id)
        quota = data.get("quota", 0)
        unit = data.get("unit") or text("labels.coin_unit", locale=locale)
    except Exception:
        logger.exception("Failed to fetch quota for insufficient-quota message")
        return text("messages.insufficient_credits", locale=locale)
    return text(
        "messages.insufficient_quota_task", locale=locale, quota=quota, unit=unit
    )


async def _notify_task_error(payload: TaskWebhookPayload) -> None:
    from apps.ai import pending_tasks

    meta = await _resolve_delivery_meta(payload)

    chat_id = meta.get("chat_id")
    message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    user_id = meta.get("user_id")
    locale = meta.get("locale", "fa")

    # task_report/error come straight from the processing service as raw
    # codes (e.g. "insufficient_quota"), not user-facing text -- showing
    # them verbatim is meaningless to a user. Swap in a real explanation
    # (with their actual current balance) for that one recognizable case;
    # anything else still falls back to the generic task_error message
    # rather than an unexplained internal string.
    raw_error = payload.task_report or payload.error or ""
    insufficient = bool(raw_error) and is_insufficient_credit_error(raw_error)
    error_text = (
        await _insufficient_quota_message(user_id, locale)
        if insufficient
        else (raw_error or text("messages.task_error", locale=locale))
    )

    renderer = get_renderer(str(bot_name)) if bot_name else None
    if chat_id and bot_name and renderer:
        try:
            keyboard = kb.buy_credits_keyboard() if insufficient else None
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


async def _notify_task_progress(payload: TaskWebhookPayload) -> None:
    """
    Edit the "processing..." message to show progress on a long task.

    Unlike ``_notify_task_error``, the task is still running -- the
    pending record must survive (touched, not removed) so the eventual
    completed/error webhook can still find its routing meta.
    """
    from apps.ai import pending_tasks

    meta = await _resolve_delivery_meta(payload)
    chat_id = meta.get("chat_id")
    message_id = meta.get("message_id")
    bot_name = meta.get("bot_name")
    locale = str(meta.get("locale", "fa"))

    renderer = get_renderer(str(bot_name)) if bot_name else None
    if chat_id and bot_name and renderer:
        match = _PAGE_PROGRESS_RE.match(payload.task_report or "")
        progress_text = (
            text(
                "messages.processing_progress",
                locale=locale,
                completed=match.group(1),
                total=match.group(2),
            )
            if match
            else text(
                "messages.processing_progress_percent",
                locale=locale,
                progress=payload.task_progress,
            )
        )
        try:
            await renderer.edit_message(chat_id, message_id, progress_text)
        except Exception:
            logger.exception("Failed to notify task progress for %s", payload.uid)
    elif chat_id and bot_name:
        logger.error("No renderer registered for bot %s (task progress)", bot_name)

    await pending_tasks.touch(payload.uid)


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
    background_tasks.add_task(_deliver_result, payload, "youtube")
    return {"status": "accepted"}


@router.post("/promptic/webhook/")
async def promptic_webhook(
    payload: TaskWebhookPayload, background_tasks: BackgroundTasks
) -> dict:
    background_tasks.add_task(_deliver_result, payload, "promptic")
    return {"status": "accepted"}
