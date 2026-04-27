from telebot import async_telebot
from usso import UserData

from apps.accounts.schemas import Profile


class MessageOwned(async_telebot.types.Message):
    user: UserData | None = None
    profile: Profile | None = None


class CallbackQueryOwned(async_telebot.types.CallbackQuery):
    message: MessageOwned | None = None
    user: UserData | None = None
    profile: Profile | None = None
