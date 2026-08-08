"""Deliver AI results to users via platform renderers."""

from __future__ import annotations

import logging
import re

from apps.ai import result_content_cache, result_media_cache
from apps.bots.common import keyboards as kb
from utils.clients.media import MediaClient
from utils.i18n import text
from utils.markdown_html import markdown_to_telegram_html

logger = logging.getLogger(__name__)

TEXT_CHUNK_LIMIT = 4096
FILE_THRESHOLD = 4096
_UNSAFE_DISPLAY_NAME_RE = re.compile(r"[\\/\x00-\x1f\x7f]+")


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


def _markdown_file_name(base_name: str) -> str:
    """Return one Markdown filename without duplicating its extension."""
    clean_name = _UNSAFE_DISPLAY_NAME_RE.sub("-", base_name).strip(" .-")
    clean_name = clean_name[:180].rstrip(" .-") or "result"
    if clean_name.lower().endswith(".md"):
        return clean_name
    stem = clean_name.rsplit(".", 1)[0] if "." in clean_name else clean_name
    return f"{stem}.md"


async def _try_delete(
    renderer: object, chat_id: int | str, msg_id: int | str | None
) -> None:
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
    workspace_id: str | None = None,
    locale: str = "fa",
    file_name_hint: str | None = None,
    include_actions: bool = True,
    processing_message_id: int | str | None = None,
    docx_url: str | None = None,
) -> int | str | None:
    """
    Send AI result — always as reply to the original user message.

    - Result ≤ 4096 chars → send as text (chunked if needed)
    - Result > 4096 chars  → upload as .md file and send as document
    - If docx_url is provided, send DOCX file along with the result
    - processing_message_id is deleted after successful delivery.
    """
    keyboard = kb.md_result_keyboard(content_type) if include_actions else None
    render_markdown = getattr(type(renderer), "render_markdown", None)
    rendered_result = (
        render_markdown(result)
        if callable(render_markdown)
        else markdown_to_telegram_html(result)
    )

    if len(result) <= FILE_THRESHOLD and len(rendered_result) <= TEXT_CHUNK_LIMIT:
        if keyboard:
            sent = await renderer.send_inline_text(
                chat_id,
                rendered_result,
                keyboard,
                reply_to=message_id,
            )
        else:
            sent = await renderer.send_text(
                chat_id,
                rendered_result,
                reply_to=message_id,
                reply_keyboard=None,
            )
        sent_id = getattr(sent, "id", None) or getattr(sent, "message_id", None)
        if sent_id is not None:
            try:
                await result_content_cache.save(sent_id, result)
            except Exception:
                logger.debug("Failed to cache result content for message %s", sent_id)

        await _try_delete(renderer, chat_id, processing_message_id)

        return sent_id

    return await _deliver_as_file(
        renderer,
        chat_id=chat_id,
        message_id=message_id,
        result=result,
        content_type=content_type,
        user_id=user_id,
        workspace_id=workspace_id,
        locale=locale,
        file_name_hint=file_name_hint,
        include_actions=include_actions,
        processing_message_id=processing_message_id,
        docx_url=docx_url,
    )


async def _deliver_as_file(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None,
    workspace_id: str | None,
    locale: str,
    file_name_hint: str | None,
    include_actions: bool,
    processing_message_id: int | str | None,
    docx_url: str | None,
) -> int | str | None:
    base_name = _result_name(content_type, user_id, file_name_hint)
    file_name = _markdown_file_name(base_name)
    file_bytes = result.encode("utf-8")

    media_url: str | None = None
    try:
        media_url = await MediaClient.upload(
            file_bytes,
            file_name,
            user_id=user_id,
            workspace_id=workspace_id,
        )
    except Exception:
        logger.exception("Failed to upload MD result")

    keyboard = (
        kb.md_result_keyboard(content_type, media_url=media_url, docx_url=docx_url)
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
    except Exception:
        logger.exception("Failed to send result document")
        return None

    await _try_delete(renderer, chat_id, processing_message_id)
    sent_id = getattr(sent, "id", None) or getattr(sent, "message_id", None)
    if sent_id is not None:
        try:
            # Same as the inline-text branch above: action buttons on this
            # message need the raw Markdown back later, and re-reading a
            # sent document's caption/text never recovers it (that's the
            # short "processing" caption, not the actual result).
            await result_content_cache.save(sent_id, result)
        except Exception:
            logger.debug("Failed to cache result content for message %s", sent_id)
        if media_url:
            try:
                await result_media_cache.save_metadata(
                    sent_id,
                    content_type=content_type,
                    media_url=media_url,
                    docx_url=docx_url,
                )
            except Exception:
                logger.debug("Failed to cache media URL for message %s", sent_id)
    return sent_id


async def deliver_docx_first_result(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
    locale: str = "fa",
    file_name_hint: str | None = None,
    include_actions: bool = True,
    processing_message_id: int | str | None = None,
    docx_title: str = "",
) -> int | str | None:
    """
    Deliver a result as a .docx file by default instead of Markdown text.

    Used for the "minutes" action: unlike every other action (which returns
    Markdown, with a convert-to-Word button as an extra step), minutes
    should hand back a ready-to-use Word document directly, with convert
    still available to get the Markdown/other formats instead. Falls back
    to the normal Markdown delivery if DOCX conversion fails, so a toolkit
    hiccup never means the user gets nothing.
    """
    from utils.clients.toolkit import convert_markdown_to_docx

    try:
        docx_bytes = await convert_markdown_to_docx(result, title=docx_title)
    except Exception:
        logger.exception("Minutes DOCX conversion failed, falling back to Markdown")
        return await deliver_result(
            renderer,
            chat_id=chat_id,
            message_id=message_id,
            result=result,
            content_type=content_type,
            user_id=user_id,
            workspace_id=workspace_id,
            locale=locale,
            file_name_hint=file_name_hint,
            include_actions=include_actions,
            processing_message_id=processing_message_id,
        )

    base_name = _result_name(content_type, user_id, file_name_hint)
    file_name = (
        f"{base_name}.docx" if not base_name.lower().endswith(".docx") else base_name
    )
    keyboard = kb.md_result_keyboard(content_type) if include_actions else None

    try:
        sent = await renderer.send_document(
            chat_id=chat_id,
            file_data=docx_bytes,
            file_name=file_name,
            caption=text("messages.result_document_caption", locale=locale),
            inline_keyboard=keyboard,
            reply_to=message_id,
        )
    except Exception:
        logger.exception("Failed to send minutes DOCX")
        return None

    await _try_delete(renderer, chat_id, processing_message_id)

    sent_id = getattr(sent, "id", None) or getattr(sent, "message_id", None)
    if sent_id is not None:
        try:
            # Cache the raw Markdown (not the DOCX) so convert:docx/markdown
            # buttons on this message keep working exactly as on every other
            # result.
            await result_content_cache.save(sent_id, result)
        except Exception:
            logger.debug("Failed to cache result content for message %s", sent_id)
    return sent_id


async def deliver_md_result(
    renderer: object,
    *,
    chat_id: int | str,
    message_id: int | str,
    result: str,
    content_type: str,
    user_id: str | None = None,
    workspace_id: str | None = None,
    locale: str = "fa",
    file_name_hint: str | None = None,
    reply_to: int | str | None = None,
    include_actions: bool = True,
    processing_message_id: int | str | None = None,
    docx_url: str | None = None,
) -> int | str | None:
    """Legacy wrapper; delegates to deliver_result."""
    return await deliver_result(
        renderer,
        chat_id=chat_id,
        message_id=reply_to or message_id,
        result=result,
        content_type=content_type,
        user_id=user_id,
        workspace_id=workspace_id,
        locale=locale,
        file_name_hint=file_name_hint,
        include_actions=include_actions,
        processing_message_id=processing_message_id,
        docx_url=docx_url,
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
