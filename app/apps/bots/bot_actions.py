"""High-level bot action handlers.

Message routing:
  text           -> AI Chat (per-user or per-group session)
  voice/audio    -> Transcribe -> MD result with inline keyboard
  video          -> Transcribe -> MD result with inline keyboard
  photo/document -> OCR       -> MD result with inline keyboard
  text/md/...    -> AI Chat with file content as context
  URL            -> fetch content, then AI Chat

Group chats: bot only responds when mentioned (@bot_username) or replied to.
"""

from __future__ import annotations

import logging
import uuid
from io import BytesIO

from fastapi_mongo_base.utils import basic
from telebot import async_telebot
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from apps.bots import base_bot, keyboards, schemas, services
from utils import texttools

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LARGE_FILE_THRESHOLD_BYTES = 20 * 1024 * 1024  # 20 MB

COMMAND_KEY: dict[str, str] = {
    "/start": "start",
    "/help": "help",
    "📚 راهنما": "help",
    "راهنما": "help",
    "/getuserid": "getuserid",
    "مکالمه جدید": "new_conversation",
    "نمایش مکالمه": "show_conversation",
    "مکالمه‌های قبلی": "conversations",
    "ناحیه کاربری": "profile",
    "🛒 خرید بسته": "purchase",
    "خرید اعتبار": "purchase",
    "💰 موجودی سکه": "balance",
    "/profile": "profile",
    "profile": "profile",
    "/sessions": "conversations",
    "/purchase": "purchase",
    "/balance": "balance",
}

_VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "avi", "mkv", "webm"})
_TEXT_EXTENSIONS = frozenset({
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
})

_URL_SOURCE_LABELS: dict[str, str] = {
    "youtube": "یوتیوب 🎬",
    "twitter": "توییتر/X 🐦",
    "instagram": "اینستاگرام 📸",
    "webpage": "صفحه وب 🌐",
}

_QUOTA_ASSET = "token"
_PRODUCTS_PER_PAGE = 5

_PROFILE_TEMPLATE = "\n".join([
    "username: `{username}`",
    "id: `{id}`",
    "first name: {first}",
    "last name: {last}",
    "language: {language}",
])

_HELP_TEXT = (
    "راهنمای استفاده از بات:\n\n"
    "• متن بفرستید → چت با هوش مصنوعی\n"
    "• ویس/صدا → تبدیل به متن\n"
    "• عکس/PDF → OCR و استخراج متن\n"
    "• لینک یوتیوب → دریافت ترنسکریپت\n"
    "• لینک توییتر/اینستاگرام → دریافت متن پست\n"
    "• روی پیام ریپلای بزنید → چت با context\n\n"
    "دکمه‌های زیر هر نتیجه:\n"
    "خلاصه کن | ساختاردهی | ترجمه | چت"
)

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
    return bool(message.caption and f"@{bot_username}" in message.caption)


def _user_format_dict(message: schemas.MessageOwned) -> dict[str, str]:
    fu = message.from_user
    return {
        "username": fu.username if fu else "",
        "id": str(message.chat.id),
        "first": fu.first_name if fu else "",
        "last": fu.last_name if fu else "",
        "language": fu.language_code if fu else "",
    }


async def _download_file(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_id: str,
) -> BytesIO:
    """Download a file, using Telethon for large Telegram files."""
    file_info = await bot.get_file(file_id)
    if (
        bot.bot_type == "telegram"
        and file_info.file_size
        and file_info.file_size > LARGE_FILE_THRESHOLD_BYTES
    ):
        return await bot.get_file_telethon(message.chat.id, message.message_id)
    raw = await bot.download_file(file_info.file_path)
    return BytesIO(raw)


# ---------------------------------------------------------------------------
# Command handler
# ---------------------------------------------------------------------------


async def command(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
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
                _HELP_TEXT,
                reply_markup=keyboards.main_keyboard(),
            )
        case "getuserid" | "profile":
            await bot.reply_to(
                message,
                _PROFILE_TEMPLATE.format(**_user_format_dict(message)),
                parse_mode="markdownV2",
            )
        case "new_conversation":
            if message.user:
                await services.reset_chat_session(message, bot)
            await bot.reply_to(message, "مکالمه جدید آغاز شد.")
        case "balance":
            await show_balance(message, bot)
        case "purchase":
            await show_products(message, bot, page=0)
        case _:
            await bot.reply_to(
                message,
                "دستور شناخته نشد.",
                reply_markup=keyboards.main_keyboard(),
            )


# ---------------------------------------------------------------------------
# Balance (quota)
# ---------------------------------------------------------------------------


async def show_balance(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    """Show remaining quota/coins for the user."""
    from apps.ai.clients import SaasClient

    if not message.user:
        await bot.reply_to(message, "کاربر شناسایی نشد.")
        return

    try:
        data = await SaasClient.get_quota(
            asset=_QUOTA_ASSET,
            user_id=str(message.user.uid),
        )
        quota = data.get("quota", "0")
        unit = data.get("unit") or "توکن"
        await bot.reply_to(
            message,
            f"💰 موجودی شما: *{quota}* {unit}",
            parse_mode="markdown",
        )
    except Exception:
        logging.exception("Failed to fetch quota for user %s", message.user.uid)
        await bot.reply_to(message, "خطا در دریافت موجودی. لطفاً دوباره تلاش کنید.")


# ---------------------------------------------------------------------------
# Products / purchase
# ---------------------------------------------------------------------------


async def show_products(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    page: int = 0,
) -> None:
    """Fetch and display paginated product list."""
    from apps.ai.clients import ShopClient

    try:
        data = await ShopClient.list_products(
            offset=page * _PRODUCTS_PER_PAGE,
            limit=_PRODUCTS_PER_PAGE,
        )
    except Exception:
        logging.exception("Failed to fetch products")
        await bot.reply_to(message, "خطا در دریافت لیست محصولات.")
        return

    products = data.get("items", [])
    total = data.get("total", 0)

    if not products:
        await bot.reply_to(message, "محصولی برای نمایش وجود ندارد.")
        return

    kb = keyboards.products_keyboard(products, page, total)
    await bot.reply_to(message, f"🛒 بسته‌های موجود (صفحه {page + 1}):", reply_markup=kb)


# ---------------------------------------------------------------------------
# Text / AI Chat
# ---------------------------------------------------------------------------


async def prompt(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    response = await bot.reply_to(message, "لطفاً صبر کنید...")
    result = await services.ai_chat_response(message=message, bot=bot)
    if result:
        await bot.edit_message_text(
            text=result[:4096],
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


# ---------------------------------------------------------------------------
# Voice / Audio / Video
# ---------------------------------------------------------------------------


async def _handle_media(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    file_id: str,
    file_name: str,
    content_type: str,
    submit_fn: object,
) -> None:
    """Shared download-and-submit logic for transcribe and OCR."""
    response = await bot.reply_to(message, "در حال پردازش...")
    try:
        file_bytes = await _download_file(message, bot, file_id)
        await submit_fn(
            message=message,
            bot=bot,
            file_bytes=file_bytes.read(),
            file_name=file_name,
            response_message_id=response.message_id,
            content_type=content_type,
        )
    except Exception:
        logging.exception("Error processing %s (%s)", content_type, file_name)
        await bot.edit_message_text(
            text="خطایی در پردازش فایل رخ داد.",
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


async def voice(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    await _handle_media(
        message,
        bot,
        file_id=message.voice.file_id,
        file_name="voice.ogg",
        content_type="voice",
        submit_fn=services.submit_transcribe,
    )


async def audio(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    file_name = getattr(message.audio, "file_name", None) or "audio.mp3"
    await _handle_media(
        message,
        bot,
        file_id=message.audio.file_id,
        file_name=file_name,
        content_type="audio",
        submit_fn=services.submit_transcribe,
    )


async def video(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    file_name = getattr(message.video, "file_name", None) or "video.mp4"
    await _handle_media(
        message,
        bot,
        file_id=message.video.file_id,
        file_name=file_name,
        content_type="video",
        submit_fn=services.submit_transcribe,
    )


# ---------------------------------------------------------------------------
# Photo / Document -> OCR
# ---------------------------------------------------------------------------


async def photo(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    photo_info = message.photo[-1]
    await _handle_media(
        message,
        bot,
        file_id=photo_info.file_id,
        file_name="photo.jpg",
        content_type="photo",
        submit_fn=services.submit_ocr,
    )


async def document(message: schemas.MessageOwned, bot: base_bot.BaseBot) -> None:
    doc = message.document
    file_name = doc.file_name or "document.pdf"
    ext = file_name.rsplit(".", 1)[-1].lower()

    if ext in _VIDEO_EXTENSIONS:
        await _handle_media(
            message,
            bot,
            file_id=doc.file_id,
            file_name=file_name,
            content_type="video",
            submit_fn=services.submit_transcribe,
        )
    elif ext in _TEXT_EXTENSIONS:
        await prompt(message, bot)
    else:
        await _handle_media(
            message,
            bot,
            file_id=doc.file_id,
            file_name=file_name,
            content_type="document",
            submit_fn=services.submit_ocr,
        )


# ---------------------------------------------------------------------------
# URL content fetching
# ---------------------------------------------------------------------------


async def url_content(
    message: schemas.MessageOwned,
    bot: base_bot.BaseBot,
    url: str,
) -> None:
    from apps.bots.url_fetcher import fetch as fetch_url

    response = await bot.reply_to(message, "در حال بارگذاری لینک...")
    try:
        content, source_type = await fetch_url(url)
    except Exception:
        logging.exception("Failed to fetch URL: %s", url)
        await bot.edit_message_text(
            text="متأسفانه نتوانستم محتوای این لینک را بارگذاری کنم.",
            chat_id=message.chat.id,
            message_id=response.message_id,
        )
        return

    label = _URL_SOURCE_LABELS.get(source_type, "لینک")
    await bot.edit_message_text(
        text=f"محتوای {label} دریافت شد. در حال پردازش...",
        chat_id=message.chat.id,
        message_id=response.message_id,
    )

    original_text = message.text or ""
    user_question = original_text.replace(url, "").strip()
    if user_question:
        message.text = f"{user_question}\n\n[محتوای لینک]:\n{content}"
    else:
        message.text = f"[محتوای {label}]:\n{content}\n\nخلاصه‌ای از این محتوا بده."  # noqa: RUF001

    result = await services.ai_chat_response(message=message, bot=bot)
    if result:
        await bot.edit_message_text(
            text=result[:4096],
            chat_id=message.chat.id,
            message_id=response.message_id,
        )


# ---------------------------------------------------------------------------
# Top-level message router
# ---------------------------------------------------------------------------


@basic.try_except_wrapper
async def message(  # noqa: C901
    message: schemas.MessageOwned, bot: base_bot.BaseBot
) -> None:
    bot_me = await bot.get_me()

    if _is_group(message) and not _bot_is_mentioned(message, bot_me.username or bot.me):
        return

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
        return await url_content(message, bot, text)

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
    if data.startswith("buy:"):
        return await callback_buy(call, bot)
    if data.startswith("products_page:"):
        return await callback_products_page(call, bot)


async def callback_answer(
    call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot
) -> None:
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


async def callback_buy(call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot) -> None:
    """Handle buy:{product_uid} — initiate purchase."""
    from apps.ai.clients import ShopClient

    product_uid = call.data.split(":", 1)[1]
    user_id = str(call.user.uid) if call.user else ""
    if not user_id:
        await bot.send_message(call.message.chat.id, "کاربر شناسایی نشد.")
        return

    try:
        redirect_url = await ShopClient.purchase(
            product_uid=product_uid,
            user_id=user_id,
            callback_url=f"https://t.me/{bot.me}",
        )
    except Exception:
        logging.exception("Purchase failed for product %s", product_uid)
        await bot.send_message(
            call.message.chat.id,
            "خطا در ایجاد سفارش. لطفاً دوباره تلاش کنید.",
        )
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 پرداخت", url=redirect_url))
    await bot.send_message(
        call.message.chat.id,
        "برای تکمیل خرید روی دکمه زیر کلیک کنید:",
        reply_markup=kb,
    )


async def callback_products_page(
    call: schemas.CallbackQueryOwned, bot: base_bot.BaseBot
) -> None:
    """Handle products_page:{page} — navigate product pages."""
    from apps.ai.clients import ShopClient

    page = int(call.data.split(":", 1)[1])
    try:
        data = await ShopClient.list_products(
            offset=page * _PRODUCTS_PER_PAGE,
            limit=_PRODUCTS_PER_PAGE,
        )
    except Exception:
        logging.exception("Failed to fetch products page %d", page)
        await bot.send_message(call.message.chat.id, "خطا در دریافت محصولات.")
        return

    products = data.get("items", [])
    total = data.get("total", 0)
    kb = keyboards.products_keyboard(products, page, total)
    await bot.edit_message_text(
        text=f"🛒 بسته‌های موجود (صفحه {page + 1}):",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=kb,
    )


# ---------------------------------------------------------------------------
# Inline query (Telegram only)
# ---------------------------------------------------------------------------


@basic.try_except_wrapper
async def inline_query(
    inline_query: async_telebot.types.InlineQuery, bot: base_bot.BaseBot
) -> None:
    from apps.accounts.handlers import get_usso_user
    from apps.ai.clients import AIChatClient

    credentials = {
        "identifier_type": "telegram_id",
        "identifier": str(inline_query.from_user.id),
    }
    user = await get_usso_user(credentials)

    query_text = inline_query.query or ""
    if not query_text.strip():
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

    try:
        session = await AIChatClient.get_or_create_session(
            user_id=str(user.uid),
            chat_id=f"inline:{user.uid}",
        )
        session_id = session.get("uid") or session.get("id")
        ai_response = await AIChatClient.send_message(session_id, query_text)
    except Exception:
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
