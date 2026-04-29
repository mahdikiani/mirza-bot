"""High-level bot action handlers.

Message routing:
  text           -> AI Chat (per-user or per-group session)
  voice/audio    -> Transcribe -> MD result with inline keyboard
  video          -> Transcribe -> MD result with inline keyboard
  photo/document -> OCR       -> MD result with inline keyboard
  URL            -> AI Chat with the URL as context

Group chats: bot only responds when mentioned (@bot_username) or replied to.
"""

from __future__ import annotations

import logging
from io import BytesIO

from fastapi_mongo_base.utils import basic
from telebot import async_telebot

from apps.bots import base_bot, keyboards, schemas, services
from utils import texttools

LARGE_FILE_THRESHOLD_BYTES = 20 * 1024 * 1024  # 20 MB

# Maximum characters before sending an .md file instead of inline text
# (~2 Telegram messages worth of text)
MD_FILE_THRESHOLD_CHARS = 8192

COMMAND_KEY: dict[str, str] = {
    "/start": "start",
    "/help": "help",
    "راهنما": "help",
    "/getuserid": "getuserid",
    "مکالمه جدید": "new_conversation",
    "نمایش مکالمه": "show_conversation",
    "مکالمه‌های قبلی": "conversations",
    "ناحیه کاربری": "profile",
    "خرید اعتبار": "purchase",
    "/profile": "profile",
    "profile": "profile",
    "/sessions": "conversations",
    "/purchase": "purchase",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_group(message: schemas.MessageOwned) -> bool:
    return message.chat.type in ("group", "supergroup")


def _bot_is_mentioned(message: schemas.MessageOwned, bot_username: str) -> bool:
    if message.reply_to_message:
        return True
    if message.text and f"@{bot_username}" in message.text:
        return True
    return message.caption and f"@{bot_username}" in message.caption


def _session_key(message: schemas.MessageOwned) -> str:
    """Group chats share a session; private chats are per-user."""
    if _is_group(message):
        return f"group:{message.chat.id}"
    return f"user:{message.user.uid}" if message.user else f"chat:{message.chat.id}"


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


async def command(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    format_dict = {
        "username": message.from_user.username if message.from_user else "",
        "id": message.chat.id,
        "first": message.from_user.first_name if message.from_user else "",
        "last": message.from_user.last_name if message.from_user else "",
        "language": message.from_user.language_code if message.from_user else "",
    }

    query = message.text if message.text in COMMAND_KEY else "/start"
    match COMMAND_KEY[query]:
        case "start":
            await bot.reply_to(
                message,
                "به بات خوش آمدید! می‌توانید متن، صدا، تصویر یا سند بفرستید.",
                reply_markup=keyboards.main_keyboard(),
            )
        case "help":
            await bot.reply_to(
                message,
                "متن، صدا، تصویر یا PDF بفرستید. در گروه‌ها بات را منشن کنید.",  # noqa: RUF001
                reply_markup=keyboards.main_keyboard(),
            )
        case "getuserid" | "profile":
            template = "\n".join([
                "username: `{username}`",
                "id: `{id}`",
                "first name: {first}",
                "last name: {last}",
                "language: {language}",
            ])
            await bot.reply_to(
                message,
                template.format(**format_dict),
                parse_mode="markdownV2",
            )
        case "new_conversation":
            if message.user:
                await services.reset_chat_session(message, bot)
            await bot.reply_to(message, "مکالمه جدید آغاز شد.")
        case _:
            await bot.reply_to(
                message,
                "دستور شناخته نشد.",
                reply_markup=keyboards.main_keyboard(),
            )


# ---------------------------------------------------------------------------
# Text / AI Chat
# ---------------------------------------------------------------------------


async def prompt(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    response = await bot.reply_to(message, "لطفاً صبر کنید...")
    result = await services.ai_chat_response(
        message=message,
        bot=bot,
    )
    if result:
        await bot.edit_message_text(
            text=result[:4096],
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


# ---------------------------------------------------------------------------
# Voice / Audio / Video
# ---------------------------------------------------------------------------


async def _download_file(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_id: str,
    file_name: str,
) -> tuple[BytesIO, bool]:
    """Return (file_bytes, used_telethon)."""
    file_info = await bot.get_file(file_id)
    if file_info.file_size and file_info.file_size > LARGE_FILE_THRESHOLD_BYTES:
        data = await bot.get_file_telethon(message.chat.id, message.message_id)
        return data, True
    raw = await bot.download_file(file_info.file_path)
    return BytesIO(raw), False


async def media_transcribe(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_id: str,
    file_name: str,
    content_type: str,
) -> None:
    response = await bot.reply_to(message, "در حال پردازش فایل صوتی/تصویری...")
    try:
        file_bytes, _ = await _download_file(message, bot, file_id, file_name)
        await services.submit_transcribe(
            message=message,
            bot=bot,
            file_bytes=file_bytes.read(),
            file_name=file_name,
            response_message_id=response.message_id,
            content_type=content_type,
        )
    except Exception:
        logging.exception("Error in media_transcribe")
        await bot.edit_message_text(
            text="خطایی در پردازش فایل رخ داد.",
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


async def voice(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    file_id = message.voice.file_id
    await media_transcribe(message, bot, file_id, "voice.ogg", "voice")


async def audio(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    file_id = message.audio.file_id
    file_name = getattr(message.audio, "file_name", None) or "audio.mp3"
    await media_transcribe(message, bot, file_id, file_name, "audio")


async def video(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    file_id = message.video.file_id
    file_name = getattr(message.video, "file_name", None) or "video.mp4"
    await media_transcribe(message, bot, file_id, file_name, "video")


# ---------------------------------------------------------------------------
# Photo / Document -> OCR
# ---------------------------------------------------------------------------


async def media_ocr(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_id: str,
    file_name: str,
    content_type: str,
) -> None:
    response = await bot.reply_to(message, "در حال پردازش سند/تصویر...")
    try:
        file_bytes, _ = await _download_file(message, bot, file_id, file_name)
        await services.submit_ocr(
            message=message,
            bot=bot,
            file_bytes=file_bytes.read(),
            file_name=file_name,
            response_message_id=response.message_id,
            content_type=content_type,
        )
    except Exception:
        logging.exception("Error in media_ocr")
        await bot.edit_message_text(
            text="خطایی در پردازش فایل رخ داد.",
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


async def photo(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    photo_info = message.photo[-1]
    await media_ocr(message, bot, photo_info.file_id, "photo.jpg", "photo")


async def document(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    doc = message.document
    file_name = doc.file_name or "document.pdf"
    ext = file_name.rsplit(".", 1)[-1].lower()
    # Videos uploaded as documents also go through transcribe
    if ext in ("mp4", "mov", "avi", "mkv", "webm"):
        await media_transcribe(message, bot, doc.file_id, file_name, "video")
    else:
        await media_ocr(message, bot, doc.file_id, file_name, "document")


# ---------------------------------------------------------------------------
# Top-level message router
# ---------------------------------------------------------------------------


@basic.try_except_wrapper
async def message(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    # Guard: group chats only respond when mentioned
    if _is_group(message):
        bot_me = await bot.get_me()
        if not _bot_is_mentioned(message, bot_me.username or bot.me):
            return

    # Strip bot mention from text before processing
    bot_me = await bot.get_me()
    if message.text and bot_me.username:
        message.text = message.text.replace(f"@{bot_me.username}", "").strip()

    if not message.user:
        logging.warning("No user resolved for message in chat %s", message.chat.id)
        return

    if message.document:
        return await document(message, bot)
    if message.voice:
        return await voice(message, bot)
    if message.audio:
        return await audio(message, bot)
    if message.video:
        return await video(message, bot)
    if message.photo:
        return await photo(message, bot)

    text = message.text or ""
    if not text:
        return

    if text.startswith("/") or text in COMMAND_KEY or text in COMMAND_KEY.values():
        return await command(message, bot)

    if texttools.is_valid_url(text):
        # Treat URLs as chat context
        message.text = f"اطلاعاتی درباره این لینک بده: {text}"
        return await prompt(message, bot)

    return await prompt(message, bot)


# ---------------------------------------------------------------------------
# Callback query router
# ---------------------------------------------------------------------------


@basic.try_except_wrapper
async def callback(
    call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot, **kwargs: object
) -> None:
    if bot.bot_type == "telegram":
        await bot.answer_callback_query(call.id, text="در حال پردازش...")

    data = call.data or ""

    if data.startswith("action:"):
        return await callback_action(call, bot)
    if data.startswith("answer_"):
        return await callback_answer(call, bot)


async def callback_answer(
    call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot
) -> None:
    import uuid

    from apps.bots import models

    message_id = uuid.UUID(call.data.split("_")[1])
    msg: models.Message = await models.Message.get_item(
        uid=message_id, user_id=call.message.user.uid
    )
    call.message.text = msg.content
    await prompt(call.message, bot)


async def callback_action(
    call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot
) -> None:
    """Handle action:summarize/structure/translate/chat:{content_id}."""
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        return
    _, action, content_id = parts

    response = await bot.reply_to(call.message, "در حال پردازش...")
    try:
        result = await services.handle_content_action(
            action=action,
            content_id=content_id,
            message=call.message,
            bot=bot,
        )
        if result:
            await services.send_md_result(
                bot=bot,
                chat_id=call.message.chat.id,
                response_message_id=response.message_id,
                result=result,
                content_id=content_id,
                content_type=action,
                user_id=str(call.message.user.uid) if call.message.user else None,
            )
    except Exception:
        logging.exception("Error in callback_action %s", action)
        await bot.edit_message_text(
            text="خطایی در پردازش رخ داد.",
            chat_id=call.message.chat.id,
            message_id=response.message_id,
        )


# ---------------------------------------------------------------------------
# Inline query (Telegram only)
# ---------------------------------------------------------------------------


@basic.try_except_wrapper
async def inline_query(
    inline_query: async_telebot.types.InlineQuery, bot: base_bot.BaseBot
) -> None:
    import uuid

    from apps.accounts.handlers import get_usso_user
    from apps.ai.clients import AIChatClient

    credentials = {
        "identifier_type": "telegram_id",
        "identifier": f"{inline_query.from_user.id}",
    }
    user = await get_usso_user(credentials)

    query_text = inline_query.query or ""
    if not query_text.strip():
        # Req 17.4: empty query → show guidance
        results = [
            async_telebot.types.InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="متن خود را تایپ کنید",
                input_message_content=async_telebot.types.InputTextMessageContent(
                    message_text="لطفاً متن سوال خود را تایپ کنید."
                ),
            )
        ]
        await bot.answer_inline_query(inline_query.id, results, cache_time=10)
        return

    # Req 17.1, 17.2: get real AI response
    try:
        session = await AIChatClient.get_or_create_session(
            user_id=str(user.uid),
            chat_id=f"inline:{user.uid}",
        )
        session_id = session.get("uid") or session.get("id")
        ai_response = await AIChatClient.send_message(session_id, query_text)
    except Exception:
        # Req 17.3: on error return friendly message instead of crashing
        logging.exception("Inline query AI error")
        ai_response = "خطایی در دریافت پاسخ رخ داد."

    results = [
        async_telebot.types.InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="پاسخ هوش مصنوعی",
            input_message_content=async_telebot.types.InputTextMessageContent(
                message_text=ai_response[:4096]
            ),
            reply_markup=keyboards.inline_keyboard(bot.link),
        )
    ]
    await bot.answer_inline_query(inline_query.id, results, cache_time=300)
