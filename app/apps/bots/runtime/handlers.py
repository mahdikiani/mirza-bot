"""Bot lifecycle: setup Telethon (Telegram) and telebot (Bale) adapters."""

from __future__ import annotations

import asyncio
import logging
import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import ClassVar, cast

import singleton

from apps.bots.common.events import CallbackEvent, MessageEvent
from apps.bots.common.handler import (
    BotRuntimeContext,
    handle_callback_event,
    handle_inline_query_event,
    handle_message_event,
)
from apps.bots.runtime import registry
from apps.bots.telegram.gateway import (
    TelethonClient,
    TelethonEventRenderer,
    TelethonGateway,
)
from server.config import Settings
from utils.i18n import text

logger = logging.getLogger(__name__)


def app_version() -> str:
    """Return the current app version from package metadata or pyproject.toml."""
    try:
        return version("mirza-bot")
    except PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[3] / "pyproject.toml"
        try:
            data = tomllib.loads(pyproject.read_text())
        except OSError:
            return "unknown"
        return str(data.get("project", {}).get("version", "unknown"))


def get_bot(bot_name: str) -> object:
    """Look up a bot instance by its username."""
    return registry.get_by_name(bot_name)


def get_bot_by_route(bot_route: str) -> object:
    """Look up a bot instance by its webhook route."""
    return registry.get_by_route(bot_route)


class BotHandler(metaclass=singleton.Singleton):
    """Singleton orchestrator that sets up Telegram + Bale adapters."""

    is_setup = False
    _runtime_tasks: ClassVar[list[asyncio.Task]] = []

    async def setup(self) -> None:
        """Initialize Telegram (Telethon) and Bale (telebot) adapters."""
        if self.is_setup:
            return

        from apps.bots.bale.bot import BaleBot
        from apps.bots.telegram.bot import TelegramBot

        telegram = TelegramBot()
        if TelegramBot.is_configured():
            registry.register(telegram)
            logging.info("Setting up Telegram bot: %s", telegram.me)
            await self._start_telegram_gateway(telegram)
        else:
            logging.warning("Skipping Telegram: TELEGRAM_TOKEN missing")

        bale = BaleBot()
        if BaleBot.is_configured():
            registry.register(bale)
            logging.info("Setting up Bale bot: %s", bale.me)
            await self._setup_bale_bot(bale)
            await self._start_bale_polling()
        else:
            logging.warning("Skipping Bale bot: BALE_BOT_TOKEN missing")

        self.is_setup = True

    async def _setup_bale_bot(self, bot: object) -> None:
        """Register Bale renderer and set up polling."""
        from apps.bots.bale.bot import BaleBot
        from apps.bots.bale.renderer import BaleEventRenderer
        from apps.bots.common.renderer_registry import register_renderer

        if not isinstance(bot, BaleBot) or not BaleBot.is_configured():
            logging.warning("Skipping Bale bot: not configured")
            return
        if not bot.token:
            logging.warning("Skipping Bale bot %s: token missing", bot.me)
            return

        await bot.resolve_me()
        registry.register(bot)
        register_renderer(bot.me, BaleEventRenderer(bot))
        await self._notify_admin_started(bot.me, "bale-polling", bot=bot)

    async def _start_telegram_gateway(self, bot: object) -> None:
        """Start Telethon gateway for a Telegram bot."""
        token = getattr(bot, "token", None)
        bot_name = getattr(bot, "me", "telegram")
        if not token:
            logging.warning(
                "Skipping Telethon gateway for %s: TELEGRAM_TOKEN missing",
                bot_name,
            )
            return
        if not Settings.telegram_api_id or not Settings.telegram_api_hash:
            logging.warning(
                "Skipping Telethon gateway for %s: TELEGRAM_API_ID/API_HASH missing",
                bot_name,
            )
            return

        gateway = TelethonGateway(
            bot_name=bot_name,
            api_id=Settings.telegram_api_id,
            api_hash=Settings.telegram_api_hash,
            bot_token=token,
        )

        def _make_runtime_context(client: object) -> BotRuntimeContext:
            return BotRuntimeContext(
                bot_name=bot_name,
                platform="telegram",
                renderer=TelethonEventRenderer(cast(TelethonClient, client), bot_name),
                capabilities=gateway.capabilities,
                bot_user_id=gateway._bot_user_id,
                bot_username=gateway._bot_username,
            )

        async def on_message(event: MessageEvent, client: object) -> None:
            await handle_message_event(event, _make_runtime_context(client))

        async def on_callback(event: CallbackEvent, client: object) -> None:
            await handle_callback_event(event, _make_runtime_context(client))

        async def on_inline_query(event: object, client: object) -> None:
            from apps.bots.common.events import InlineQueryEvent

            if not isinstance(event, InlineQueryEvent):
                return
            await handle_inline_query_event(event, _make_runtime_context(client))

        async def on_started(client: object) -> None:
            from apps.bots.common.renderer_registry import register_renderer

            context = _make_runtime_context(client)
            register_renderer(bot_name, context.renderer)
            await self._notify_admin_started(
                bot_name,
                "telethon",
                renderer=context.renderer,  # type: ignore[arg-type]
            )

        gateway.on_message(on_message)
        gateway.on_callback(on_callback)
        gateway.on_inline_query(on_inline_query)
        gateway.on_started(on_started)
        task = asyncio.create_task(gateway.start(), name=f"telethon-{bot_name}")
        task.add_done_callback(self._log_runtime_task_result)
        self._runtime_tasks.append(task)
        logging.info("Started Telethon gateway task for %s", bot_name)

    @staticmethod
    def _log_runtime_task_result(task: asyncio.Task) -> None:
        """Log unexpected background runtime task failures."""
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            logging.exception("Runtime task failed: %s", task.get_name())

    async def _notify_admin_started(
        self,
        bot_name: str,
        runtime: str,
        bot: object | None = None,
        renderer: TelethonEventRenderer | None = None,
    ) -> None:
        if not Settings.admin_chat_id:
            return

        message_text = text(
            "messages.startup_admin",
            bot_name=bot_name,
            version=app_version(),
            runtime=runtime,
        )
        if bot is not None and getattr(bot, "bot_type", None) == "bale":
            chat_id = Settings.bale_admin_chat_id or Settings.admin_chat_id
        else:
            chat_id = Settings.admin_chat_id
        if isinstance(chat_id, str) and chat_id.isdecimal():
            chat_id = int(chat_id)
        try:
            if renderer:
                await asyncio.wait_for(
                    renderer.send_text(chat_id, message_text), timeout=10
                )
            elif bot is not None and hasattr(bot, "send_message"):
                await asyncio.wait_for(
                    bot.send_message(chat_id, message_text), timeout=10
                )
            logging.info("Sent startup notification to admin for %s", bot_name)
        except Exception:
            logging.exception("Failed to send startup notification to admin")

    async def _start_bale_polling(self) -> None:
        from apps.bots.runtime.poller import start_bale_polling

        logging.info(
            "Starting Bale polling (interval=%.1fs)",
            Settings.polling_interval_seconds,
        )
        task = start_bale_polling(Settings.polling_interval_seconds)
        task.add_done_callback(self._log_runtime_task_result)
        self._runtime_tasks.append(task)
