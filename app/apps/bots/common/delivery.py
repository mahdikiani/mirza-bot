"""Deliver AI results to users via platform renderers."""

from __future__ import annotations

import logging

from apps.bots.common import keyboards as kb
from utils.clients.media import MediaClient
from utils.i18n import text

logger = logging.getLogger(__name__)

TEXT_CHUNK_LIMIT = 4096
FILE_THRESHOLD = 4096


def _result_name(content_type: str, user_id: str | None, hint: str | None) -> str:
    if hint:
        return hint
    name_map = {
        "document": "ocr",
        "voice": "transcribe",
        "audio": "transcribe",
        "video": "transcribe",
        "url": "webpage",
        "youtube": "youtube",
        "promptic": "action",
    }
    prefix = name_map.get(content_type, content_type)
    suffix = (user_id or "unknown")[:8]
    return f"{prefix}_{suffix}"


async def _try_delete(renderer: object, chat_id: int | str, msg_id: int | str | None) -> None:
    if msg_id is None:
        return
    try:
        await renderer.delete_message(chat_id, msg_id)
    except Exception:
        logger.debug("Failed to delete message %s in chat %s", msg_id, chat_id)


async def deliver_result(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None = None,
    locale: str = "fa",
    file_name_hint: str | None = None,
    include_actions: bool = True,
    processing_message_id: int | str | None = None,
) -> int | str | None:
    """Send AI result — always as reply to the original user message.

    - Result ≤ 4096 chars → send as text (chunked if needed)
    - Result > 4096 chars  → upload as .md file and send as document
    - processing_message_id is deleted after successful delivery.
    """
    keyboard = kb.md_result_keyboard(content_type) if include_actions else None

    if len(result) <= FILE_THRESHOLD:
        if keyboard:
            sent = await renderer.send_inline_text(
                chat_id,
                result[:TEXT_CHUNK_LIMIT],
                keyboard,
                reply_to=message_id,
            )
        else:
            sent = await renderer.send_text(
                chat_id,
                result[:TEXT_CHUNK_LIMIT],
                reply_to=message_id,
                reply_keyboard=None,
            )
        sent_id = getattr(sent, "id", None) or getattr(sent, "message_id", None)

        await _try_delete(renderer, chat_id, processing_message_id)

        remaining = result[TEXT_CHUNK_LIMIT:]
        while remaining:
            chunk = remaining[:TEXT_CHUNK_LIMIT]
            await renderer.send_text(chat_id, chunk, reply_to=message_id)
            remaining = remaining[TEXT_CHUNK_LIMIT:]
        return sent_id

    base_name = _result_name(content_type, user_id, file_name_hint)
    if not base_name.lower().endswith(".md"):
        base_name = base_name.rsplit(".", 1)[0] if "." in base_name else base_name
    file_name = f"{base_name}.md"
    file_bytes = result.encode("utf-8")

    media_url: str | None = None
    try:
        media_url = await MediaClient.upload(file_bytes, file_name)
    except Exception:
        logger.exception("Failed to upload MD result")

    keyboard = (
        kb.md_result_keyboard(content_type, media_url=media_url)
        if include_actions
        else None
    )
    try:
        sent = await renderer.send_document(
            chat_id=chat_id,
            file_data=file_bytes,
            file_name=file_name,
            caption=text("messages.result_document_caption", locale=locale),
            inline_keyboard=keyboard,
            reply_to=message_id,
        )
        await _try_delete(renderer, chat_id, processing_message_id)
        return getattr(sent, "id", None) if sent else None
    except Exception:
        logger.exception("Failed to send result document")
        return None


async def deliver_md_result(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None = None,
    locale: str = "fa",
    file_name_hint: str | None = None,
    reply_to: int | str | None = None,
    include_actions: bool = True,
    processing_message_id: int | str | None = None,
) -> int | str | None:
    """Legacy wrapper; delegates to deliver_result."""
    return await deliver_result(
        renderer,
        chat_id=chat_id,
        message_id=reply_to or message_id,
        result=result,
        content_type=content_type,
        user_id=user_id,
        locale=locale,
        file_name_hint=file_name_hint,
        include_actions=include_actions,
        processing_message_id=processing_message_id,
    )


def is_insufficient_credit_error(error_text: str) -> bool:
    """Detect quota/credit errors from AI Toolkit."""
    lowered = error_text.lower()
    markers = (
        "insufficient",
        "quota",
        "credit",
        "not enough",
        "موجودی",
        "اعتبار",
        "کافی نیست",
    )
    return any(marker in lowered for marker in markers)
