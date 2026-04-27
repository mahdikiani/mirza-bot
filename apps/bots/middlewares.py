import logging

from telebot import async_telebot

from apps.accounts.handlers import get_user_profile, get_usso_user
from apps.bots import base_bot, schemas


class UserMiddleware(async_telebot.BaseMiddleware):
    def __init__(self, bot: base_bot.BaseBot, **kwargs: object) -> None:
        self.update_sensitive = True
        self.update_types = [
            "message",
            "callback_query",
        ]
        self.bot = bot
        self.bot_type = bot.bot_type
        super().__init__(**kwargs)

    async def pre_process_message(
        self, message: async_telebot.types.Message, data: object
    ) -> None:
        # In group chats the sender is from_user; in channels it may be absent
        from_user = message.from_user if message.from_user else message.chat
        bot_me = await self.bot.get_me()
        if from_user.id == bot_me.id:
            # Message originated from the bot itself; use chat as identity
            from_user = message.chat

        credentials = {
            "identifier_type": "telegram_id",
            "identifier": f"{from_user.id}",
        }
        try:
            user = await get_usso_user(credentials)
        except Exception:
            logging.exception("Failed to resolve USSO user for %s", credentials)
            user = None

        message_owned: schemas.MessageOwned = message  # type: ignore[assignment]
        message_owned.user = user

        if user is not None:
            try:
                message_owned.profile = await get_user_profile(str(user.uid))
            except Exception:
                logging.exception("Failed to load profile for user %s", user.uid)
                message_owned.profile = None

    async def pre_process_callback_query(
        self, call: async_telebot.types.CallbackQuery, data: object
    ) -> None:
        await self.pre_process_message(call.message, data)
        # Propagate user/profile to the CallbackQuery object itself
        call_owned: schemas.CallbackQueryOwned = call  # type: ignore[assignment]
        msg_owned: schemas.MessageOwned = call.message  # type: ignore[assignment]
        call_owned.user = msg_owned.user
        call_owned.profile = msg_owned.profile

    async def post_process_message(
        self,
        message: async_telebot.types.Message,
        data: object,
        exception: Exception | None,
    ) -> None:
        if exception:
            logging.exception("Error processing message", exc_info=exception)

    async def post_process_callback_query(
        self,
        call: async_telebot.types.CallbackQuery,
        data: object,
        exception: Exception | None,
    ) -> None:
        if exception:
            logging.exception("Error processing callback", exc_info=exception)
