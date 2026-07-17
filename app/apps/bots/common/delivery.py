"""Deliver AI results to users via platform renderers."""

from __future__ import annotations

import logging

from apps.bots.common import keyboards as kb
from apps.bots.common.media_flow import (
    MD_FILE_THRESHOLD_CHARS,
    TRANSCRIBE_TEXT_THRESHOLD_CHARS,
)
from utils.clients.media import MediaClient
from utils.i18n import text

logger = logging.getLogger(__name__)


async def deliver_md_result(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None = None,
    locale: str = "fa",
) -> int | str | None:
    """Edit a processing message with OCR/transcribe output and action buttons."""
    threshold = (
        TRANSCRIBE_TEXT_THRESHOLD_CHARS
        if content_type in ("voice", "audio", "video")
        else MD_FILE_THRESHOLD_CHARS
    )
    keyboard = kb.md_result_keyboard(content_type)

    if len(result) <= threshold:
        await renderer.edit_message(
            chat_id=chat_id,
            message_id=message_id,
            text=result[:4096],
            inline_keyboard=keyboard,
        )
        remaining = result[4096:]
        while remaining:
            chunk = remaining[:4096]
            await renderer.send_text(chat_id, chunk, reply_to=None)
            remaining = remaining[4096:]
        return message_id

    file_name = f"result_{(user_id or 'unknown')[:8]}.md"
    file_bytes = result.encode("utf-8")
    media_url: str | None = None
    try:
        media_url = await MediaClient.upload(file_bytes, file_name)
    except Exception:
        logger.exception("Failed to upload MD result")

    keyboard = kb.md_result_keyboard(content_type, media_url=media_url)
    await renderer.edit_message(
        chat_id=chat_id,
        message_id=message_id,
        text=text("messages.result_sent_as_file", locale=locale),
    )
    try:
        sent = await renderer.send_document(
            chat_id=chat_id,
            file_data=file_bytes,
            file_name=file_name,
            caption=text("messages.result_document_caption", locale=locale),
            inline_keyboard=keyboard,
        )
        return getattr(sent, "id", None) if sent else None
    except Exception:
        logger.exception("Failed to send result document")
        return None


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
