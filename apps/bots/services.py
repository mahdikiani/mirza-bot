"""Business logic layer — all external service calls go through internal clients."""

import logging
from io import BytesIO

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
    return session.get("uid") or session.get("id")


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


async def ai_chat_response(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
) -> str | None:
    session_id = await _get_or_create_session(message)
    if not session_id:
        return "کاربر شناسایی نشد."
    try:
        return await AIChatClient.send_message(session_id, message.text or "")
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
    )

    # Persist metadata so the webhook knows where to send the result
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
    keyboard = keyboards.md_result_keyboard(content_id, content_type)

    if len(result) <= MD_FILE_THRESHOLD_CHARS:
        await bot.edit_message_text(
            text=result[:4096],
            chat_id=chat_id,
            message_id=response_message_id,
            reply_markup=keyboard,
        )
        if len(result) > 4096:
            # Send the rest as additional messages without keyboard
            remaining = result[4096:]
            while remaining:
                await bot.send_message(chat_id, remaining[:4096])
                remaining = remaining[4096:]
    else:
        # Send as .md file attachment
        md_bytes = BytesIO(result.encode("utf-8"))
        md_bytes.name = f"result_{content_id[:8]}.md"
        await bot.edit_message_text(
            text="نتیجه آماده شد:",
            chat_id=chat_id,
            message_id=response_message_id,
        )
        await bot.send_document(
            chat_id,
            md_bytes,
            caption="فایل نتیجه",
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

    # Load the saved message content
    try:
        uid = uuid.UUID(content_id)
        saved_msg: models.Message = await models.Message.get_item(uid=uid)
        content = saved_msg.content
    except Exception:
        logging.exception("Content not found: %s", content_id)
        return "محتوا یافت نشد."

    language = "fa"
    if message.profile and message.profile.profile_data:
        language = message.profile.profile_data.engine_config.language

    if action == "chat":
        # Set content as context in the chat session and notify user
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
