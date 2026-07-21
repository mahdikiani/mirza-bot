"""Async media processing: OCR, transcribe, YouTube, webpage links."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from apps.ai.clients import OCRClient, TranscribeClient, WebpageClient, YoutubeClient
from apps.bots.common import models
from apps.bots.common.events import MessageEvent
from apps.bots.common.link_router import LinkKind, classify_url, is_audio_video_url
from server.config import Settings
from utils.clients.media import MediaClient

logger = logging.getLogger(__name__)

_CONTENT_EXT: dict[str, str] = {
    "voice": "ogg",
    "audio": "mp3",
    "video": "mp4",
    "photo": "jpg",
    "document": "bin",
    "animation": "gif",
}


def _safe_filename(content_type: str, original_name: str) -> str:
    if original_name:
        return original_name
    ext = _CONTENT_EXT.get(content_type, "bin")
    ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return f"{content_type}_{ts}.{ext}"


TRANSCRIBE_TEXT_THRESHOLD_CHARS = 2 * 4096
MD_FILE_THRESHOLD_CHARS = 8192
JINA_READER_BASE = "https://r.jina.ai/"


async def fetch_webpage_content(url: str) -> str:
    """Fetch readable webpage content via Jina Reader (free tier)."""
    reader_url = f"{JINA_READER_BASE}{url}"
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(reader_url)
        response.raise_for_status()
        return response.text


async def fetch_webpages_parallel(urls: list[str]) -> list[str]:
    """Fetch multiple webpages concurrently."""
    if not urls:
        return []
    results = await asyncio.gather(
        *[fetch_webpage_content(url) for url in urls],
        return_exceptions=True,
    )
    contents: list[str] = []
    for url, item in zip(urls, results, strict=True):
        if isinstance(item, Exception):
            logger.exception("Failed to fetch webpage %s", url)
            continue
        if item and str(item).strip():
            contents.append(str(item).strip())
    return contents


def toolkit_task_meta(
    *,
    event: MessageEvent,
    bot_name: str,
    response_message_id: int | str,
    content_type: str,
    user_id: str,
    locale: str = "fa",
    file_name_hint: str | None = None,
    user_prompt: str | None = None,
) -> dict:
    """Build trace metadata for AI Toolkit tasks."""
    return {
        "platform": event.platform,
        "source": "mirza-bot",
        "chat_id": event.chat_id,
        "message_id": response_message_id,
        "reply_to_message_id": event.message_id,
        "bot_name": bot_name,
        "content_type": content_type,
        "user_id": user_id,
        "locale": locale,
        "platform_user_id": str(event.sender.id) if event.sender else None,
        "telegram_user_id": str(event.sender.id) if event.sender else None,
        "file_name_hint": file_name_hint,
        "user_prompt": user_prompt,
    }


async def upload_bytes(file_bytes: bytes, file_name: str) -> str:
    """Upload file bytes to Media service."""
    return await MediaClient.upload(file_bytes, file_name)


def webhook_url_for(route_name: str) -> str:
    """Build absolute webhook URL for an AI route."""
    from apps.ai.routes import router as ai_router

    path = ai_router.url_path_for(route_name)
    return f"https://{Settings.root_url}{Settings.base_path}{path}"


async def submit_ocr_url(
    file_url: str,
    user_id: str,
    meta_data: dict,
) -> str | None:
    """Submit OCR for a remote file URL."""
    result = await OCRClient.submit(
        file_url=file_url,
        user_id=user_id,
        webhook_url=webhook_url_for("ocr_webhook"),
        meta_data=meta_data,
    )
    return str(result.get("uid") or result.get("id") or "") or None


async def submit_transcribe_url(
    file_url: str,
    user_id: str,
    meta_data: dict,
) -> str | None:
    """Submit transcribe for a remote file URL."""
    result = await TranscribeClient.submit(
        file_url=file_url,
        user_id=user_id,
        webhook_url=webhook_url_for("transcribe_webhook"),
        meta_data=meta_data,
    )
    return str(result.get("uid") or result.get("id") or "") or None


async def submit_youtube(
    video_url: str,
    user_id: str,
    meta_data: dict,
) -> str | None:
    """Submit YouTube transcript task."""
    webhook_path = webhook_url_for("youtube_webhook")
    result = await YoutubeClient.submit(
        video_id=video_url,
        user_id=user_id,
        webhook_url=webhook_path,
        meta_data=meta_data,
    )
    task_uid = str(result.get("uid") or result.get("id") or "") or None
    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=task_uid,
            task_type="youtube",
            user_id=user_id,
            meta_data=meta_data,
        )
    return task_uid


async def submit_webpage(
    url: str,
    user_id: str,
    meta_data: dict,
) -> str | None:
    """Submit webpage extraction task."""
    result = await WebpageClient.submit(
        url=url,
        user_id=user_id,
        webhook_url=webhook_url_for("webpage_webhook"),
        meta_data=meta_data,
    )
    return str(result.get("uid") or result.get("id") or "") or None


async def submit_file_bytes(
    *,
    event: MessageEvent,
    bot_name: str,
    file_bytes: bytes,
    file_name: str,
    response_message_id: int | str,
    content_type: str,
    user_id: str,
    locale: str = "fa",
    user_prompt: str | None = None,
) -> str | None:
    """Upload bytes and dispatch OCR or transcribe."""
    file_name = _safe_filename(content_type, file_name)
    meta = toolkit_task_meta(
        event=event,
        bot_name=bot_name,
        response_message_id=response_message_id,
        content_type=content_type,
        user_id=user_id,
        locale=locale,
        file_name_hint=file_name,
        user_prompt=user_prompt,
    )
    file_url = await upload_bytes(file_bytes, file_name)

    audio_video_ct = {"voice", "audio", "video"}
    if content_type in audio_video_ct:
        task_uid = await submit_transcribe_url(file_url, user_id, meta)
        task_type = "transcribe"
    else:
        task_uid = await submit_ocr_url(file_url, user_id, meta)
        task_type = "ocr"

    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=task_uid,
            task_type=task_type,
            user_id=user_id,
            meta_data=meta,
        )
    return task_uid


async def submit_url(
    *,
    event: MessageEvent,
    bot_name: str,
    url: str,
    response_message_id: int | str,
    user_id: str,
    locale: str = "fa",
    user_prompt: str | None = None,
) -> str | None:
    """Route a URL to the correct AI Toolkit task."""
    meta = toolkit_task_meta(
        event=event,
        bot_name=bot_name,
        response_message_id=response_message_id,
        content_type="url",
        user_id=user_id,
        locale=locale,
        user_prompt=user_prompt,
    )
    kind = classify_url(url)

    if kind == LinkKind.youtube:
        return await submit_youtube(url, user_id, meta)

    if kind in {LinkKind.file, LinkKind.gdrive}:
        if is_audio_video_url(url):
            task_uid = await submit_transcribe_url(url, user_id, meta)
            task_type = "transcribe"
        else:
            task_uid = await submit_ocr_url(url, user_id, meta)
            task_type = "ocr"
        if task_uid:
            from apps.ai.pending_tasks import add as add_pending_task

            await add_pending_task(
                task_uid=task_uid,
                task_type=task_type,
                user_id=user_id,
                meta_data=meta,
            )
        return task_uid

    task_uid = await submit_webpage(url, user_id, meta)
    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=task_uid,
            task_type="webpage",
            user_id=user_id,
            meta_data=meta,
        )
    return task_uid


async def save_artifact(
    *,
    user_id: str,
    source_type: str,
    content: str,
    meta_data: dict | None = None,
) -> models.Artifact:
    """Persist extracted content as an artifact."""
    artifact = models.Artifact(
        user_id=user_id,
        source_type=source_type,
        content=content,
        meta_data=meta_data,
    )
    await artifact.save()
    return artifact
