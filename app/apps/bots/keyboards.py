from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from server.config import Settings

_PRODUCTS_PER_PAGE = 5


def main_keyboard() -> ReplyKeyboardMarkup:
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton(
            "\U0001f4b0 \u0645\u0648\u062c\u0648\u062f\u06cc \u0633\u06a9\u0647"
        ),
        KeyboardButton("\U0001f6d2 \u062e\u0631\u06cc\u062f \u0628\u0633\u062a\u0647"),
    )
    markup.add(
        KeyboardButton("\U0001f4da \u0631\u0627\u0647\u0646\u0645\u0627"),
        KeyboardButton("\u0645\u06a9\u0627\u0644\u0645\u0647 \u062c\u062f\u06cc\u062f"),
    )
    markup.add(
        KeyboardButton(
            "\u0646\u0627\u062d\u06cc\u0647 \u06a9\u0627\u0631\u0628\u0631\u06cc"
        ),
    )
    return markup


def products_keyboard(
    products: list[dict],
    page: int,
    total: int,
) -> InlineKeyboardMarkup:
    """Inline keyboard for product listing with pagination.

    Shows up to 5 products per page, with prev/next navigation row.
    """
    markup = InlineKeyboardMarkup(row_width=1)
    for p in products:
        uid = p.get("uid", "")
        name = p.get("name", "محصول")
        price = p.get("unit_price", "?")
        markup.add(
            InlineKeyboardButton(
                f"{name} — {price} ریال",
                callback_data=f"buy:{uid}",
            )
        )

    # Pagination row
    nav_buttons = []
    if page > 0:
        nav_buttons.append(
            InlineKeyboardButton(
                "\u2b05\ufe0f قبلی",
                callback_data=f"products_page:{page - 1}",
            )
        )
    offset = (page + 1) * _PRODUCTS_PER_PAGE
    if offset < total:
        nav_buttons.append(
            InlineKeyboardButton(
                "بعدی \u27a1\ufe0f",
                callback_data=f"products_page:{page + 1}",
            )
        )
    if nav_buttons:
        markup.row(*nav_buttons)

    return markup


def md_result_keyboard(
    content_id: str,
    content_type: str,
    media_url: str | None = None,
) -> InlineKeyboardMarkup:
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
    # Viewer button: for large results uploaded to media, use the media URL;
    # for voice/video always show viewer link
    if media_url:
        viewer_url = f"{Settings.viewer_base_url}?url={media_url}"
        markup.add(
            InlineKeyboardButton("مشاهده آنلاین 🔗", url=viewer_url),
        )
    elif content_type in ("voice", "video", "audio"):
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
