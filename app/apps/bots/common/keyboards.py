"""Platform-agnostic keyboard definitions."""

from __future__ import annotations

from dataclasses import dataclass, field

from server.config import Settings
from utils.i18n import button, text


@dataclass
class InlineButton:
    """Single inline keyboard button."""

    label: str
    callback_data: str = ""
    url: str = ""


@dataclass
class ReplyButton:
    """Single reply keyboard button."""

    label: str
    request_contact: bool = False


@dataclass
class InlineKeyboard:
    """Platform-neutral inline keyboard layout."""

    rows: list[list[InlineButton]] = field(default_factory=list)


@dataclass
class ReplyKeyboard:
    """Platform-neutral reply keyboard layout."""

    rows: list[list[ReplyButton]] = field(default_factory=list)
    one_time: bool = False


def main_menu_keyboard() -> ReplyKeyboard:
    """Build the main reply keyboard (2x2 layout)."""
    return ReplyKeyboard(
        rows=[
            [
                ReplyButton(button("my_account")),
                ReplyButton(button("buy_credits")),
            ],
            [
                ReplyButton(button("settings")),
                ReplyButton(button("help")),
            ],
        ]
    )


def contact_request_keyboard() -> ReplyKeyboard:
    """Build a one-time contact request keyboard."""
    return ReplyKeyboard(
        rows=[[ReplyButton(button("share_contact"), request_contact=True)]],
        one_time=True,
    )


def settings_language_keyboard(current_lang: str = "fa") -> InlineKeyboard:
    """Build settings inline keyboard from LANGUAGES data."""
    from apps.bots.common.settings import LANGUAGES

    return InlineKeyboard(
        rows=[
            [
                InlineButton(
                    f"{'✅ ' if current_lang == lang['code'] else ''}{lang['label']}",
                    callback_data=f"settings:lang:{lang['code']}",
                )
                for lang in LANGUAGES
            ],
            [InlineButton(button("change_model"), callback_data="settings:model:menu")],
        ]
    )


def settings_model_keyboard(current_model: str) -> InlineKeyboard:
    """Build model selection inline keyboard."""
    from apps.bots.common.settings import AVAILABLE_MODELS

    rows: list[list[InlineButton]] = []
    for model in AVAILABLE_MODELS:
        label = f"{'✅ ' if model == current_model else ''}{model}"
        rows.append([InlineButton(label, callback_data=f"settings:model:{model}")])
    rows.append([InlineButton(button("back"), callback_data="settings:lang:menu")])
    return InlineKeyboard(rows=rows)


def md_result_keyboard(
    content_type: str,
    media_url: str | None = None,
    docx_url: str | None = None,
) -> InlineKeyboard:
    """Build action buttons for OCR/transcribe results."""
    rows = [
        [
            InlineButton(button("summarize"), callback_data="action:summarize"),
            InlineButton(button("format_notes"), callback_data="action:structure"),
        ],
        [
            InlineButton(button("translate"), callback_data="action:translate"),
            InlineButton(button("cleanup"), callback_data="action:cleanup"),
        ],
        [
            InlineButton(button("minutes"), callback_data="action:minutes"),
            InlineButton(button("quiz"), callback_data="action:quiz"),
        ],
        [
            InlineButton(button("convert"), callback_data="convert:menu"),
        ],
    ]
    if content_type in {"voice", "audio", "video"}:
        rows.insert(
            0,
            [
                InlineButton(
                    button("ask_ai"),
                    callback_data="chat:voice",
                ),
            ],
        )
    if docx_url:
        rows.append([
            InlineButton("📄 Word (DOCX)", url=docx_url),
        ])
    return InlineKeyboard(rows=rows)


def convert_keyboard(content_type: str = "", media_url: str | None = None) -> InlineKeyboard:
    """Build conversion sub-menu keyboard."""
    rows = [
        [InlineButton(button("word"), callback_data="convert:docx")],
        [InlineButton(button("markdown"), callback_data="convert:markdown")],
    ]
    if content_type in ("voice", "video", "audio"):
        rows.append([InlineButton(button("audio_read"), callback_data="convert:audio")])
    if Settings.viewer_base_url:
        if media_url:
            rows.append([InlineButton(button("view_online"), url=f"{Settings.viewer_base_url}?url={media_url}")])
        elif content_type in ("voice", "video", "audio"):
            rows.append([InlineButton(button("view_online"), url=f"{Settings.viewer_base_url}?type={content_type}")])
    rows.append([InlineButton(button("back"), callback_data="convert:back")])
    return InlineKeyboard(rows=rows)


def products_keyboard(
    products: list[dict],
    page: int,
    total: int,
) -> InlineKeyboard:
    """Build paginated product purchase keyboard."""
    from apps.bots.common.billing import products_per_page

    rows: list[list[InlineButton]] = []
    for product in products:
        uid = product.get("uid", "")
        name = product.get("name") or text("labels.product_default")
        raw = product.get("unit_price", 0)
        try:
            toman = int(raw) // 10
            price = f"{toman:,}"
        except (ValueError, TypeError):
            price = str(raw)
        rows.append([InlineButton(f"{name} — {price} تومان", callback_data=f"buy:{uid}")])

    nav: list[InlineButton] = []
    if page > 0:
        nav.append(
            InlineButton(button("previous"), callback_data=f"products_page:{page - 1}")
        )
    if (page + 1) * products_per_page() < total:
        nav.append(
            InlineButton(button("next"), callback_data=f"products_page:{page + 1}")
        )
    if nav:
        rows.append(nav)
    return InlineKeyboard(rows=rows)


def buy_credits_keyboard() -> InlineKeyboard:
    """Build a single-button keyboard that opens the purchase flow."""
    return InlineKeyboard(
        rows=[[InlineButton(button("buy_credits"), callback_data="menu:purchase")]]
    )
