"""Convert platform-agnostic keyboards to telegram-bale-bot markup."""

from __future__ import annotations

from telebot.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

from apps.bots.common.keyboards import (
    InlineButton,
    InlineKeyboard,
    ReplyKeyboard,
)


def to_reply_markup(keyboard: ReplyKeyboard | None) -> ReplyKeyboardMarkup | None:
    """Convert a reply keyboard to telebot markup."""
    if keyboard is None:
        return None
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    if keyboard.one_time:
        markup.one_time_keyboard = True
    for row in keyboard.rows:
        buttons = [
            KeyboardButton(item.label, request_contact=True)
            if item.request_contact
            else KeyboardButton(item.label)
            for item in row
        ]
        markup.add(*buttons)
    return markup


def to_inline_markup(keyboard: InlineKeyboard | None) -> InlineKeyboardMarkup | None:
    """Convert an inline keyboard to telebot markup."""
    if keyboard is None:
        return None
    markup = InlineKeyboardMarkup(row_width=2)
    for row in keyboard.rows:
        buttons: list[InlineKeyboardButton] = []
        for item in row:
            if item.url:
                buttons.append(InlineKeyboardButton(item.label, url=item.url))
            else:
                buttons.append(
                    InlineKeyboardButton(item.label, callback_data=item.callback_data)
                )
        markup.add(*buttons)
    return markup


def inline_row(buttons: list[InlineButton]) -> list[InlineKeyboardButton]:
    """Convert a row of inline buttons to telebot buttons."""
    return [
        InlineKeyboardButton(b.label, url=b.url)
        if b.url
        else InlineKeyboardButton(b.label, callback_data=b.callback_data)
        for b in buttons
    ]
