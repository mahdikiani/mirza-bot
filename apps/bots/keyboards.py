from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from server.config import Settings


def main_keyboard() -> ReplyKeyboardMarkup:
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=3)
    markup.add(
        KeyboardButton("راهنما"),
        KeyboardButton("ناحیه کاربری"),
        KeyboardButton("خرید اعتبار"),
        KeyboardButton("مکالمه جدید"),
    )
    return markup


def md_result_keyboard(content_id: str, content_type: str) -> InlineKeyboardMarkup:
    """Inline keyboard shown below every MD result (OCR / transcribe / video)."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(
            "خلاصه کن", callback_data=f"action:summarize:{content_id}"
        ),
        InlineKeyboardButton(
            "ساختاردهی", callback_data=f"action:structure:{content_id}"
        ),
    )
    markup.add(
        InlineKeyboardButton("ترجمه", callback_data=f"action:translate:{content_id}"),
        InlineKeyboardButton("چت", callback_data=f"action:chat:{content_id}"),
    )
    if content_type in ("voice", "video", "audio"):
        markup.add(
            InlineKeyboardButton(
                "مشاهده آنلاین",
                url=f"{Settings.viewer_base_url}/{content_id}",
            ),
        )
    return markup


def answer_keyboard(message_id: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("پاسخ دادن", callback_data=f"answer_{message_id}"),
    )
    return markup


def inline_keyboard(bot_link: str = "https://t.me/mdfier_bot") -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("رفتن به بات", url=bot_link))
    return markup
