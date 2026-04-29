"""Business logic layer — all external service calls go through internal clients."""

import logging

from apps.ai.clients import (
    AIChatClient,
    MediaClient,
    OCRClient,
    PrompticClient,
    TranscribeClient,
)
from apps.bots import base_bot, keyboards, models, schemas
from server.config import Settings

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


def _session_chat_id(message: schemas.MessageOwned) -> str:
    """Group chats use group ID; private chats use user ID."""
    if message.chat.type in ("group", "supergroup"):
        return f"group:{message.chat.id}"
    return str(message.user.uid) if message.user else str(message.chat.id)


async def _get_or_create_session(message: schemas.MessageOwned) -> str | None:
    if not message.user:
        return None
    engine_config = {}
    if message.profile and message.profile.profile_data:
        ec = message.profile.profile_data.engine_config
        engine_config = ec.model_dump()

    session = await AIChatClient.get_or_create_session(
        user_id=str(message.user.uid),
        chat_id=_session_chat_id(message),
        engine_config=engine_config,
    )
    session_id = session.get("uid") or session.get("id")
    if not session_id:
        logging.error("get_or_create_session returned no uid/id: %s", session)
        return None
    return session_id


async def reset_chat_session(
    message: schemas.MessageOwned, bot: base_bot.BaseBot
) -> None:
    if not message.user:
        return
    try:
        await AIChatClient.new_session(
            user_id=str(message.user.uid),
            chat_id=_session_chat_id(message),
        )
    except Exception:
        logging.exception("Failed to reset chat session")


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------


async def _build_reply_chain(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
) -> str:
    """Walk the reply chain and build a combined message string for the LLM."""
    parts: list[str] = []
    current = message

    while current:
        text = current.text or current.caption or ""
        attachment = await _extract_text_attachment(current, bot)
        if attachment:
            text = f"{text}\n\n[پیوست]:\n{attachment}".strip()
        if text:
            sender = "کاربر"
            if current.from_user and current.from_user.is_bot:
                sender = "دستیار"
            parts.append(f"[{sender}]: {text}")
        current = getattr(current, "reply_to_message", None)

    parts.reverse()
    return "\n\n".join(parts)


async def _extract_text_attachment(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
) -> str | None:
    """If the message has a text-like document (md/txt/etc.), download and return its content."""
    doc = getattr(message, "document", None)
    if not doc:
        return None

    file_name: str = doc.file_name or ""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    TEXT_EXTENSIONS = {
        "md",
        "txt",
        "csv",
        "json",
        "xml",
        "yaml",
        "yml",
        "html",
        "htm",
        "rst",
    }
    SKIP_EXTENSIONS = {
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
        "mp3",
        "ogg",
        "mp4",
        "mov",
        "avi",
        "mkv",
        "webm",
    }

    if ext in SKIP_EXTENSIONS:
        return None
    if ext not in TEXT_EXTENSIONS and ext:
        return None

    try:
        file_info = await bot.get_file(doc.file_id)
        raw = await bot.download_file(file_info.file_path)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        logging.exception("Failed to download text attachment %s", file_name)
        return None


async def ai_chat_response(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
) -> str | None:
    session_id = await _get_or_create_session(message)
    if not session_id:
        return "کاربر شناسایی نشد."
    try:
        if getattr(message, "reply_to_message", None):
            content = await _build_reply_chain(message, bot)
        else:
            text = message.text or message.caption or ""
            attachment = await _extract_text_attachment(message, bot)
            if attachment:
                text = f"{text}\n\n[پیوست]:\n{attachment}".strip()
            content = text

        return await AIChatClient.send_message(session_id, content)
    except Exception:
        logging.exception("AI chat error for session %s", session_id)
        return "خطایی در ارتباط با سرویس هوش مصنوعی رخ داد."


# ---------------------------------------------------------------------------
# Media upload helper
# ---------------------------------------------------------------------------


async def _upload_file(file_bytes: bytes, file_name: str) -> str:
    return await MediaClient.upload(file_bytes, file_name)


# ---------------------------------------------------------------------------
# OCR submission
# ---------------------------------------------------------------------------


async def submit_ocr(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_bytes: bytes,
    file_name: str,
    response_message_id: int,
    content_type: str,
) -> None:
    from apps.ai.routes import router as ai_router

    user_id = str(message.user.uid) if message.user else ""

    file_url = await _upload_file(file_bytes, file_name)

    webhook_path = ai_router.url_path_for("ocr_webhook")
    webhook_url = f"https://{Settings.root_url}{Settings.base_path}{webhook_path}"

    meta_data = {
        "chat_id": message.chat.id,
        "message_id": response_message_id,
        "bot_name": bot.me,
        "content_type": content_type,
        "user_id": user_id,
    }
    result = await OCRClient.submit(
        file_url=file_url,
        user_id=user_id,
        webhook_url=webhook_url,
        meta_data=meta_data,
    )

    task_uid = result.get("uid") or result.get("id") if result else None
    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=str(task_uid),
            task_type="ocr",
            user_id=user_id or "unknown",
            meta_data=meta_data,
        )
    else:
        logging.warning(
            "OCR submit returned no task uid; polling disabled for this task"
        )


# ---------------------------------------------------------------------------
# Transcribe submission
# ---------------------------------------------------------------------------


async def submit_transcribe(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_bytes: bytes,
    file_name: str,
    response_message_id: int,
    content_type: str,
) -> None:
    from apps.ai.routes import router as ai_router

    user_id = str(message.user.uid) if message.user else ""

    file_url = await _upload_file(file_bytes, file_name)

    webhook_path = ai_router.url_path_for("transcribe_webhook")
    webhook_url = f"https://{Settings.root_url}{Settings.base_path}{webhook_path}"

    meta_data = {
        "chat_id": message.chat.id,
        "message_id": response_message_id,
        "bot_name": bot.me,
        "content_type": content_type,
        "user_id": user_id,
    }

    result = await TranscribeClient.submit(
        file_url=file_url,
        user_id=user_id,
        webhook_url=webhook_url,
        meta_data=meta_data,
    )

    msg = models.Message(
        user_id=user_id or "unknown",
        content="",
        content_type=content_type,
        source_chat_id=str(message.chat.id),
        meta_data=meta_data,
    )
    await msg.save()

    task_uid = result.get("uid") or result.get("id") if result else None
    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=str(task_uid),
            task_type="transcribe",
            user_id=user_id or "unknown",
            meta_data=meta_data,
        )
    else:
        logging.warning(
            "Transcribe submit returned no task uid; polling disabled for this task"
        )


# ---------------------------------------------------------------------------
# Sending MD results (length-aware)
# ---------------------------------------------------------------------------

# Voice/transcribe: send as text if fits in 2 Telegram messages
TRANSCRIBE_TEXT_THRESHOLD_CHARS = 2 * 4096
# OCR/action results: send as text if fits in one viewer-page worth
MD_FILE_THRESHOLD_CHARS = 8192


async def send_md_result(
    bot: base_bot.BaseBot,
    chat_id: int | str,
    response_message_id: int,
    result: str,
    content_id: str,
    content_type: str,
    user_id: str | None = None,
) -> None:
    threshold = (
        TRANSCRIBE_TEXT_THRESHOLD_CHARS
        if content_type in ("voice", "audio", "video")
        else MD_FILE_THRESHOLD_CHARS
    )

    if len(result) <= threshold:
        keyboard = keyboards.md_result_keyboard(
            content_id, content_type, media_url=None
        )
        await bot.edit_message_text(
            text=result[:4096],
            chat_id=chat_id,
            message_id=response_message_id,
            reply_markup=keyboard,
        )
        remaining = result[4096:]
        while remaining:
            await bot.send_message(chat_id, remaining[:4096])
            remaining = remaining[4096:]
    else:
        md_bytes = result.encode("utf-8")
        file_name = f"result_{content_id[:8]}.md"
        try:
            media_url = await _upload_file(md_bytes, file_name)
        except Exception:
            logging.exception("Failed to upload MD result to media service")
            media_url = None

        keyboard = keyboards.md_result_keyboard(
            content_id, content_type, media_url=media_url
        )
        await bot.edit_message_text(
            text="نتیجه آماده شد. برای مشاهده کامل روی دکمه زیر کلیک کنید:",
            chat_id=chat_id,
            message_id=response_message_id,
            reply_markup=keyboard,
        )


# ---------------------------------------------------------------------------
# Content action callbacks (summarize / structure / translate / chat)
# ---------------------------------------------------------------------------


async def handle_content_action(
    action: str,
    content_id: str,
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
) -> str | None:
    import uuid

    user_id = str(message.user.uid) if message.user else None

    try:
        uid = uuid.UUID(content_id)
        saved_msg: models.Message = await models.Message.get_item(
            uid=uid, user_id=user_id
        )
        content = saved_msg.content
    except Exception:
        logging.exception("Content not found: %s", content_id)
        return "محتوا یافت نشد."

    language = "fa"
    if message.profile and message.profile.profile_data:
        language = message.profile.profile_data.engine_config.language

    if action == "chat":
        session_id = await _get_or_create_session(message)
        if session_id:
            await AIChatClient.set_context(session_id, content, "document")
        return "محتوا به مکالمه اضافه شد. اکنون می‌توانید سوال بپرسید."

    template_map = {
        "summarize": "summarize",
        "structure": "structure",
        "translate": "translate",
    }
    template = template_map.get(action)
    if not template:
        return None

    return await PrompticClient.execute(
        template=template,
        variables={"content": content, "language": language},
        user_id=user_id,
    )
