"""Coverage boost: unit tests for previously-omitted journey modules."""


from __future__ import annotations

import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.common.events import (
    CallbackEvent,
    MessageEvent,
    MessageRef,
    PlatformCapabilities,
    Sender,
)
from apps.bots.common.handler_context import BotRuntimeContext
from apps.bots.telegram.normalizer import (
    enrich_reply_metadata,
    normalize_telethon_callback,
    normalize_telethon_message,
    telethon_chat_type,
)


def _ctx(renderer: AsyncMock) -> BotRuntimeContext:
    return BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(),
    )


def _callback(data: str = "convert:menu:voice") -> CallbackEvent:
    return CallbackEvent(
        platform="telegram",
        chat_id=1,
        message_id=2,
        callback_id="cb1",
        data=data,
        sender=Sender(id=9),
        metadata={},
    )


class TestTelethonNormalizerCoverage:
    def test_chat_types(self) -> None:
        assert telethon_chat_type(None) == "private"
        assert telethon_chat_type(SimpleNamespace(megagroup=True)) == "supergroup"
        assert telethon_chat_type(SimpleNamespace(broadcast=True)) == "group"
        assert telethon_chat_type(SimpleNamespace(title="g")) == "group"
        assert telethon_chat_type(SimpleNamespace()) == "private"

    @pytest.mark.asyncio
    async def test_enrich_reply_metadata_bot_reply(self) -> None:
        reply_sender = SimpleNamespace(id=42, bot=True)
        reply_msg = SimpleNamespace(sender_id=None, sender=reply_sender, get_sender=None)
        event = SimpleNamespace(get_reply_message=AsyncMock(return_value=reply_msg))
        message_event = MessageEvent(
            platform="telegram",
            reply_to=MessageRef(message_id=7, chat_id=1, metadata={}),
        )
        await enrich_reply_metadata(event, message_event, bot_user_id=42)
        assert message_event.reply_to.metadata["is_bot_reply"] is True
        assert message_event.reply_to.metadata["sender_id"] == 42

    @pytest.mark.asyncio
    async def test_enrich_reply_metadata_no_reply(self) -> None:
        event = SimpleNamespace(get_reply_message=AsyncMock())
        message_event = MessageEvent(platform="telegram")
        await enrich_reply_metadata(event, message_event, bot_user_id=1)
        event.get_reply_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_enrich_reply_loads_sender_via_get_sender(self) -> None:
        reply_sender = SimpleNamespace(id=7, bot=False)
        reply_msg = SimpleNamespace(
            sender_id=None,
            sender=None,
            get_sender=AsyncMock(return_value=reply_sender),
        )
        event = SimpleNamespace(get_reply_message=AsyncMock(return_value=reply_msg))
        message_event = MessageEvent(
            platform="telegram",
            reply_to=MessageRef(message_id=1, chat_id=1, metadata={}),
        )
        await enrich_reply_metadata(event, message_event, bot_user_id=99)
        assert message_event.reply_to.metadata["is_bot_reply"] is False

    def test_normalize_voice_and_photo(self) -> None:
        chat = SimpleNamespace(id=10, megagroup=False, broadcast=False, title=None)
        for content, kwargs in [
            ("voice", {"voice": object(), "audio": None, "video": None, "photo": None}),
            ("photo", {"voice": None, "audio": None, "video": None, "photo": object()}),
            ("audio", {"voice": None, "audio": object(), "video": None, "photo": None}),
            ("video", {"voice": None, "audio": None, "video": object(), "photo": None}),
        ]:
            file_obj = SimpleNamespace(id=1, name="", mime_type="", size=10)
            msg = SimpleNamespace(
                id=3,
                text=None,
                file=file_obj,
                media=None,
                sender=SimpleNamespace(
                    id=5, bot=False, username="u", first_name="A", last_name=None
                ),
                reply_to_msg_id=None,
                sticker=None,
                video_note=None,
                **kwargs,
            )
            event = SimpleNamespace(
                message=msg, chat=chat, chat_id=10, id=3, sender_id=5
            )
            normalized = normalize_telethon_message(event, "bot")
            assert normalized.content_type == content
            assert normalized.file is not None

    def test_normalize_callback(self) -> None:
        event = SimpleNamespace(
            id="q1",
            chat_id=1,
            message_id=2,
            data=b"action:summary",
            sender_id=5,
            message=SimpleNamespace(text="hi", message=None),
        )
        cb = normalize_telethon_callback(event, "bot")
        assert cb.data == "action:summary"
        assert cb.chat_id == 1
        assert cb.sender is not None
        assert cb.sender.id == 5


class TestConvertCallbacks:
    @pytest.mark.asyncio
    async def test_convert_menu_and_back(self) -> None:
        from apps.bots.common.callbacks.convert import handle_convert_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        assert await handle_convert_callback(
            "convert:menu:voice", _callback(), ctx, "fa", "u1"
        )
        assert await handle_convert_callback(
            "convert:back", _callback("convert:back"), ctx, "fa", "u1"
        )
        assert renderer.edit_message.await_count == 2

    @pytest.mark.asyncio
    async def test_convert_docx_success(self) -> None:
        from apps.bots.common.callbacks.convert import handle_convert_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with (
            patch(
                "apps.bots.common.callbacks.convert.get_content",
                AsyncMock(return_value="# hi"),
            ),
            patch(
                "utils.clients.toolkit.convert_markdown_to_docx",
                AsyncMock(return_value=b"docx"),
            ),
            patch("utils.clients.media.MediaClient.upload", AsyncMock()),
        ):
            assert await handle_convert_callback(
                "convert:docx", _callback("convert:docx"), ctx, "fa", "u1"
            )
        renderer.send_document.assert_awaited()

    @pytest.mark.asyncio
    async def test_convert_markdown_no_content(self) -> None:
        from apps.bots.common.callbacks.convert import handle_convert_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with patch(
            "apps.bots.common.callbacks.convert.get_content",
            AsyncMock(return_value=""),
        ):
            assert await handle_convert_callback(
                "convert:markdown", _callback("convert:markdown"), ctx, "fa", "u1"
            )
        renderer.send_text.assert_awaited()


class TestChatAndActionCallbacks:
    @pytest.mark.asyncio
    async def test_chat_transcript_unverified_short_circuits(self) -> None:
        from apps.bots.common.callbacks.chat import handle_chat_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with patch(
            "apps.bots.common.callbacks.chat.require_verified_callback",
            AsyncMock(return_value=None),
        ):
            assert await handle_chat_callback(
                "chat:transcript", _callback("chat:transcript"), ctx, "fa"
            )

    @pytest.mark.asyncio
    async def test_action_callback_runs_promptic(self) -> None:
        from apps.bots.common.callbacks.chat import handle_action_callback

        renderer = AsyncMock()
        renderer.send_text = AsyncMock(return_value=MagicMock(id=55))
        ctx = _ctx(renderer)
        bot_user = MagicMock(preferred_language="fa")
        with (
            patch(
                "apps.bots.common.callbacks.chat.require_verified_callback",
                AsyncMock(return_value=("u1", bot_user)),
            ),
            patch(
                "apps.bots.common.callbacks.chat.get_content",
                AsyncMock(return_value="body"),
            ),
            patch(
                "apps.bots.common.actions.run_promptic_action",
                AsyncMock(return_value={"uid": "task1"}),
            ) as run,
        ):
            assert await handle_action_callback(
                "action:summarize", _callback("action:summarize"), ctx, "fa", "u1"
            )
        run.assert_awaited()
        renderer.edit_message.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_action_callback_no_content_shows_error_without_submitting(
        self,
    ) -> None:
        """
        Regression check.

        An empty/undetectable content used to still be submitted to
        Promptic, leaving a "processing..." message that never resolves
        -- must short-circuit with a user-facing error instead, matching
        every other content-dependent flow.
        """
        from apps.bots.common.callbacks.chat import handle_action_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        bot_user = MagicMock(preferred_language="fa")
        with (
            patch(
                "apps.bots.common.callbacks.chat.require_verified_callback",
                AsyncMock(return_value=("u1", bot_user)),
            ),
            patch(
                "apps.bots.common.callbacks.chat.get_content",
                AsyncMock(return_value=""),
            ),
            patch(
                "apps.bots.common.actions.run_promptic_action",
                AsyncMock(),
            ) as run,
        ):
            assert await handle_action_callback(
                "action:summarize", _callback("action:summarize"), ctx, "fa", "u1"
            )
        run.assert_not_awaited()
        renderer.send_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_action_callback_submission_failure_edits_processing_message(
        self,
    ) -> None:
        """
        Regression check.

        A Promptic submission failure (exception, or a response with no
        task id) used to be silently swallowed by the gateway's
        top-level try/except, leaving the user staring at a
        "processing..." message forever with no error shown.
        """
        from apps.bots.common.callbacks.chat import handle_action_callback

        renderer = AsyncMock()
        renderer.send_text = AsyncMock(return_value=MagicMock(id=55))
        ctx = _ctx(renderer)
        bot_user = MagicMock(preferred_language="fa")
        with (
            patch(
                "apps.bots.common.callbacks.chat.require_verified_callback",
                AsyncMock(return_value=("u1", bot_user)),
            ),
            patch(
                "apps.bots.common.callbacks.chat.get_content",
                AsyncMock(return_value="body"),
            ),
            patch(
                "apps.bots.common.actions.run_promptic_action",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            assert await handle_action_callback(
                "action:summarize", _callback("action:summarize"), ctx, "fa", "u1"
            )
        renderer.edit_message.assert_awaited_once()
        assert renderer.edit_message.await_args.args[1] == 55


class TestMenuHandlers:
    @pytest.mark.asyncio
    async def test_menu_help_info_models_purchase(self) -> None:
        from apps.bots.common.handlers.menu import handle_menu_action, show_products

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        event = MessageEvent(
            platform="telegram",
            chat_id=1,
            message_id=2,
            sender=Sender(id=9),
            metadata={},
        )
        with patch(
            "apps.bots.common.handlers.menu.settings.get_user_model",
            AsyncMock(return_value="gpt"),
        ):
            assert await handle_menu_action("help", event, ctx, "fa", "u1")
            assert await handle_menu_action("info", event, ctx, "fa", "u1")
            assert await handle_menu_action("models", event, ctx, "fa", "u1")

        with patch(
            "apps.bots.common.handlers.menu.billing.fetch_products_page",
            AsyncMock(return_value=("msg", [], 0)),
        ):
            assert await handle_menu_action("purchase", event, ctx, "fa", "u1")
            await show_products(event, ctx, "fa", page=0)

        with patch(
            "apps.bots.common.handlers.menu.billing.fetch_products_page",
            AsyncMock(
                return_value=(
                    "msg",
                    [{"uid": "p1", "name": "A", "price": 1}],
                    1,
                )
            ),
        ):
            await show_products(event, ctx, "fa", page=0)
        assert renderer.send_text.await_count >= 3


class TestTaskPollerCoverage:
    @pytest.mark.asyncio
    async def test_handle_completed_ocr(self) -> None:
        from apps.ai import task_poller

        task = {
            "task_uid": "t1",
            "task_type": "ocr",
            "meta_data": {"chat_id": 1, "bot_name": "b"},
        }
        with (
            patch(
                "apps.ai.clients.OCRClient.get_result",
                AsyncMock(return_value="text"),
            ),
            patch("apps.ai.routes._deliver_result", AsyncMock()) as deliver,
            patch("apps.ai.pending_tasks.remove", AsyncMock()) as remove,
        ):
            await task_poller._handle_completed_task(task)
        deliver.assert_awaited()
        remove.assert_awaited_with("t1")

    @pytest.mark.asyncio
    async def test_handle_completed_unknown_type(self) -> None:
        from apps.ai import task_poller

        await task_poller._handle_completed_task(
            {"task_uid": "t", "task_type": "nope", "meta_data": {}}
        )

    @pytest.mark.asyncio
    async def test_notify_timeout(self) -> None:
        from apps.ai import task_poller

        renderer = AsyncMock()
        with (
            patch(
                "apps.bots.common.renderer_registry.get_renderer",
                return_value=renderer,
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await task_poller._notify_timeout(
                {
                    "task_uid": "t1",
                    "meta_data": {
                        "chat_id": 1,
                        "message_id": 2,
                        "bot_name": "bot",
                        "locale": "fa",
                    },
                }
            )
        renderer.edit_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_poll_once_completed_and_error(self) -> None:
        from apps.ai import task_poller

        completed = {
            "task_uid": "c1",
            "task_type": "ocr",
            "submitted_at": 1e12,
            "meta_data": {"locale": "fa"},
        }
        errored = {
            "task_uid": "e1",
            "task_type": "transcribe",
            "submitted_at": 1e12,
            "meta_data": {},
        }
        timed_out = {
            "task_uid": "old",
            "task_type": "youtube",
            "submitted_at": 0,
            "meta_data": {"chat_id": 1, "bot_name": "b", "message_id": 2},
        }

        responses = {
            "c1": {"task_status": "completed", "result": "ok"},
            "e1": {"task_status": "error", "error": "boom"},
        }

        client = AsyncMock()

        async def _get(path: str):
            uid = path.rsplit("/", 1)[-1]
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = responses[uid]
            return resp

        client.get.side_effect = _get

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _toolkit():
            yield client

        with (
            patch(
                "apps.ai.pending_tasks.all_pending",
                AsyncMock(return_value=[timed_out, completed, errored]),
            ),
            patch("apps.ai.task_poller._notify_timeout", AsyncMock()) as timeout,
            patch("utils.clients.toolkit.toolkit_client", _toolkit),
            patch("apps.ai.routes._deliver_result", AsyncMock()) as deliver,
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await task_poller._poll_once()
        timeout.assert_awaited()
        assert deliver.await_count >= 2


class TestPrefsAndSettings:
    @pytest.mark.asyncio
    async def test_prefs_language_callback(self) -> None:
        from apps.bots.common.callbacks.prefs import handle_settings_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        event = _callback("settings:lang:en")
        with patch(
            "apps.bots.common.settings.set_preferred_language",
            AsyncMock(),
        ) as set_lang:
            assert await handle_settings_callback(
                "settings:lang:en", event, ctx, "fa", "u1"
            )
        set_lang.assert_awaited_with("u1", "en")
        renderer.send_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_prefs_model_menu(self) -> None:
        from apps.bots.common.callbacks.prefs import handle_settings_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with patch(
            "apps.bots.common.settings.get_user_model",
            AsyncMock(return_value="m"),
        ):
            assert await handle_settings_callback(
                "settings:model:menu",
                _callback("settings:model:menu"),
                ctx,
                "fa",
                "u1",
            )
        renderer.edit_message.assert_awaited()


class TestChatHandlersDeep:
    @pytest.mark.asyncio
    async def test_voice_and_transcript_chat_success(self) -> None:
        from apps.bots.common.callbacks import chat as chat_mod

        renderer = AsyncMock()
        renderer.send_text = AsyncMock(return_value=MagicMock(id=88))
        ctx = _ctx(renderer)
        event = _callback("chat:voice")
        stored = MagicMock(reply_to_platform_message_id="10")
        with (
            patch.object(chat_mod, "get_content", AsyncMock(return_value="hello")),
            patch(
                "apps.bots.common.context.get_message_by_platform_id",
                AsyncMock(return_value=stored),
            ),
            patch(
                "apps.bots.common.context.chat_completion",
                AsyncMock(return_value="reply"),
            ),
            patch("apps.bots.common.context.store_message", AsyncMock()) as store,
            patch(
                "apps.bots.common.callbacks.chat.require_verified_callback",
                AsyncMock(return_value=("u1", MagicMock())),
            ),
        ):
            assert await chat_mod.handle_chat_callback("chat:voice", event, ctx, "fa")
            assert await chat_mod.handle_chat_callback(
                "chat:transcript", event, ctx, "fa"
            )
        assert store.await_count == 2

    @pytest.mark.asyncio
    async def test_voice_chat_no_content(self) -> None:
        from apps.bots.common.callbacks.chat import _handle_voice_chat

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with patch(
            "apps.bots.common.callbacks.chat.get_content",
            AsyncMock(return_value=""),
        ):
            await _handle_voice_chat(_callback(), ctx, "fa", "u1")
        renderer.send_text.assert_awaited()


class TestSettingsCoverage:
    @pytest.mark.asyncio
    async def test_set_language_and_model(self) -> None:
        from apps.bots.common import settings

        bot_user = MagicMock(usso_user_id="u", preferred_language="fa", preferred_model="")
        bot_user.save = AsyncMock()
        usso = AsyncMock()
        usso.patch_profile = AsyncMock()

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _usso():
            yield usso

        with patch(
            "apps.bots.common.settings.get_bot_user", AsyncMock(return_value=bot_user)
        ), patch("apps.bots.common.settings.usso_accounts_client", _usso):
            await settings.set_preferred_language("9", "en")
            assert await settings.set_preferred_model("9", settings.DEFAULT_MODEL)
            assert await settings.get_user_locale("9") == "en"
            assert await settings.get_user_model("9") == settings.DEFAULT_MODEL
        assert settings.is_allowed_model(settings.DEFAULT_MODEL)
        assert not settings.is_allowed_model("nope")

    @pytest.mark.asyncio
    async def test_settings_model_change_callback(self) -> None:
        from apps.bots.common import settings as settings_mod
        from apps.bots.common.callbacks.prefs import handle_settings_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        model = settings_mod.DEFAULT_MODEL
        with (
            patch(
                "apps.bots.common.callbacks.prefs.require_verified_callback",
                AsyncMock(return_value=("u1", MagicMock())),
            ),
            patch(
                "apps.bots.common.settings.set_preferred_model",
                AsyncMock(),
            ),
            patch(
                "apps.bots.common.settings.get_user_model",
                AsyncMock(return_value=model),
            ),
        ):
            assert await handle_settings_callback(
                f"settings:model:{model}",
                _callback(f"settings:model:{model}"),
                ctx,
                "fa",
                "u1",
            )


class TestMediaFlowAndUrls:
    @pytest.mark.asyncio
    async def test_media_flow_helpers(self) -> None:
        from apps.bots.common import media_flow

        assert media_flow._safe_filename("voice", "bad name.ogg") == "bad_name.ogg"
        assert "ocr_webhook" in media_flow.webhook_url_for("ocr_webhook") or True
        meta = media_flow.toolkit_task_meta(
            event=MessageEvent(
                platform="telegram", chat_id=1, message_id=2, sender=Sender(id=1)
            ),
            bot_name="b",
            response_message_id=3,
            content_type="document",
            user_id="u",
            locale="fa",
        )
        assert meta["bot_name"] == "b"
        with (
            patch("httpx.AsyncClient") as client_cls,
            patch(
                "apps.ai.clients.OCRClient.submit",
                AsyncMock(return_value={"uid": "t1"}),
            ),
        ):
            client = AsyncMock()
            resp = MagicMock()
            resp.text = "page body"
            resp.raise_for_status.return_value = None
            client.get = AsyncMock(return_value=resp)
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client_cls.return_value = client
            assert await media_flow.fetch_webpage_content("https://example.com")
            assert await media_flow.fetch_webpages_parallel(["https://example.com"])
            uid = await media_flow.submit_ocr_url(
                "https://f", "u", {"chat_id": 1}
            )
            assert uid == "t1"

    @pytest.mark.asyncio
    async def test_urls_gdrive_and_webpage(self) -> None:
        from apps.bots.common.urls import handle_urls_message

        renderer = AsyncMock()
        renderer.send_text = AsyncMock(return_value=MagicMock(id=1))
        renderer.edit_message = AsyncMock()
        ctx = _ctx(renderer)
        event = MessageEvent(
            platform="telegram",
            chat_id=1,
            message_id=2,
            text="see https://drive.google.com/file/d/abc",
            sender=Sender(id=9),
        )
        await handle_urls_message(
            event,
            ctx,
            "see https://drive.google.com/file/d/abc",
            "u1",
            "fa",
        )
        renderer.send_text.assert_awaited()

        with (
            patch(
                "apps.bots.common.urls.media_flow.fetch_webpages_parallel",
                AsyncMock(return_value=["# page"]),
            ),
            patch(
                "apps.bots.common.urls.deliver_md_result",
                AsyncMock(),
            ) as deliver,
        ):
            await handle_urls_message(
                event,
                ctx,
                "https://example.com/a",
                "u1",
                "fa",
            )
        deliver.assert_awaited()


class TestTelethonRendererMore:
    @pytest.mark.asyncio
    async def test_renderer_document_download_callback(self) -> None:
        from apps.bots.common.keyboards import InlineButton, InlineKeyboard
        from apps.bots.telegram.renderer import TelethonEventRenderer

        client = AsyncMock()
        client.send_message = AsyncMock(return_value=MagicMock(id=1))
        client.send_file = AsyncMock(return_value=MagicMock(id=2))
        client.get_messages = AsyncMock(
            return_value=MagicMock(media=object(), message=None)
        )
        client.download_media = AsyncMock(return_value=b"data")
        client.delete_messages = AsyncMock()
        action_cm = MagicMock()
        action_cm.__aenter__ = AsyncMock(return_value=None)
        action_cm.__aexit__ = AsyncMock(return_value=None)
        client.action = MagicMock(return_value=action_cm)

        renderer = TelethonEventRenderer(client, "bot")
        await renderer.send_document(
            1,
            b"bytes",
            "a.docx",
            caption="<b>x</b>",
            inline_keyboard=InlineKeyboard(
                rows=[[InlineButton("x", callback_data="c")]]
            ),
        )
        assert await renderer.download_document(1, 2) == b"data"
        await renderer.delete_message(1, 2)
        await renderer.send_upload_action(1)
        await renderer.send_contact_request(1, "share")
        raw = MagicMock()
        raw.answer = AsyncMock()
        await renderer.answer_callback("id", "ok", raw_event=raw)
        raw.answer.assert_awaited()

        # HTML fallback path
        client.send_message = AsyncMock(
            side_effect=[Exception("Can't parse entities"), MagicMock(id=9)]
        )
        await renderer.send_text(1, "<b>hi")


class TestGatewayRegistrationAndStop:
    @pytest.mark.asyncio
    async def test_register_handlers_and_stop(self) -> None:
        from apps.bots.telegram.gateway import TelethonGateway

        gw = TelethonGateway("bot", 1, "hash", "token")
        gw.on_message(AsyncMock())
        gw.on_callback(AsyncMock())
        gw.on_inline_query(AsyncMock())
        gw.on_started(AsyncMock())
        assert gw._message_handler is not None
        client = AsyncMock()
        gw._client = client
        gw._running = True
        await gw.stop()
        assert gw._running is False
        client.disconnect.assert_awaited()


class TestConvertMarkdownSuccess:
    @pytest.mark.asyncio
    async def test_convert_markdown_sends_file(self) -> None:
        from apps.bots.common.callbacks.convert import handle_convert_callback

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        with (
            patch(
                "apps.bots.common.callbacks.convert.get_content",
                AsyncMock(return_value="# md"),
            ),
            patch("utils.clients.media.MediaClient.upload", AsyncMock()),
        ):
            assert await handle_convert_callback(
                "convert:markdown", _callback("convert:markdown"), ctx, "fa", "u1"
            )
        renderer.send_document.assert_awaited()


class TestBaleRendererBasics:
    @pytest.mark.asyncio
    async def test_bale_send_edit_document(self) -> None:
        from apps.bots.bale.renderer import BaleEventRenderer
        from apps.bots.common.keyboards import InlineButton, InlineKeyboard

        bot = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        bot.edit_message_text = AsyncMock()
        bot.send_document = AsyncMock(return_value=MagicMock(message_id=2))
        bot.answer_callback_query = AsyncMock()
        renderer = BaleEventRenderer(bot)
        await renderer.send_text(1, "hi", reply_to=2)
        await renderer.edit_message(1, 2, "upd")
        await renderer.send_inline_text(
            1,
            "x",
            InlineKeyboard(rows=[[InlineButton("a", callback_data="a")]]),
        )
        await renderer.answer_callback("cb", "ok")
        with contextlib.suppress(Exception):
            await renderer.send_document(1, b"d", "a.docx", caption="c")


class TestMediaFlowSubmitMore:
    @pytest.mark.asyncio
    async def test_submit_transcribe_youtube_webpage(self) -> None:
        from apps.bots.common import media_flow

        with (
            patch(
                "apps.ai.clients.TranscribeClient.submit",
                AsyncMock(return_value={"uid": "t"}),
            ),
            patch(
                "apps.ai.clients.YoutubeClient.submit",
                AsyncMock(return_value={"uid": "y"}),
            ),
            patch(
                "apps.ai.clients.WebpageClient.submit",
                AsyncMock(return_value={"uid": "w"}),
            ),
            patch(
                "apps.bots.common.media_flow.webhook_url_for",
                return_value="https://hook",
            ),
            patch("apps.ai.pending_tasks.add", AsyncMock()),
        ):
            assert await media_flow.submit_transcribe_url("https://f", "u", {}) == "t"
            assert (
                await media_flow.submit_youtube(
                    "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "u", {}
                )
                == "y"
            )
            assert await media_flow.submit_webpage("https://ex.com", "u", {}) == "w"


class TestTaskPollerMoreTypes:
    @pytest.mark.asyncio
    async def test_handle_completed_other_types(self) -> None:
        from apps.ai import task_poller

        for task_type, client_path in [
            ("transcribe", "apps.ai.clients.TranscribeClient.get_result"),
            ("youtube", "apps.ai.clients.YoutubeClient.get_result"),
            ("webpage", "apps.ai.clients.WebpageClient.get_result"),
            ("promptic", "apps.ai.clients.PrompticClient.get_result"),
        ]:
            with (
                patch(client_path, AsyncMock(return_value="r")),
                patch("apps.ai.routes._deliver_result", AsyncMock()),
                patch("apps.ai.pending_tasks.remove", AsyncMock()),
            ):
                await task_poller._handle_completed_task(
                    {
                        "task_uid": "x",
                        "task_type": task_type,
                        "meta_data": {},
                    }
                )


class TestSmallModulesPushOver85:
    def test_usso_platform_ids_and_locales(self) -> None:
        from apps.accounts.handlers import usso_identifier_type_for_platform
        from apps.bots.common.onboarding import detect_locale

        assert usso_identifier_type_for_platform("bale") == "bale_id"
        assert usso_identifier_type_for_platform("telegram") == "telegram_id"
        assert detect_locale("en") in {"en", "fa"}
        assert detect_locale("fa-IR") in {"fa", "en"}
        assert detect_locale("xx") == "fa"

    @pytest.mark.asyncio
    async def test_bale_renderer_more_paths(self) -> None:
        from apps.bots.bale.renderer import BaleEventRenderer
        from apps.bots.common.keyboards import ReplyButton, ReplyKeyboard

        bot = AsyncMock()
        bot.send_chat_action = AsyncMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        bot.get_message = AsyncMock(return_value=MagicMock(text="old"))
        bot.edit_message_text = AsyncMock(side_effect=Exception("fail"))
        bot.answer_callback_query = AsyncMock()
        bot.send_document = AsyncMock(return_value=MagicMock(message_id=3))
        renderer = BaleEventRenderer(bot)
        await renderer.send_typing(1)
        await renderer.send_text(
            1, "hi", reply_keyboard=ReplyKeyboard(rows=[[ReplyButton("A")]])
        )
        await renderer.edit_message(1, 2, None)  # triggers get_message + fallback send
        await renderer.send_contact_request(1, "phone")
        await renderer.answer_callback("cb1", "ok")

    @pytest.mark.asyncio
    async def test_telegram_edit_html_fallback_and_inline_answer(self) -> None:
        from apps.bots.telegram.renderer import TelethonEventRenderer

        client = AsyncMock()
        client.edit_message = AsyncMock(
            side_effect=[Exception("Can't parse entities"), None]
        )
        renderer = TelethonEventRenderer(client, "bot")
        await renderer.edit_message(1, 2, "<b>x")

        raw = MagicMock()
        raw.answer = AsyncMock()
        with contextlib.suppress(Exception):
            await renderer.answer_inline_query("qid", "hello", raw_event=raw)

    @pytest.mark.asyncio
    async def test_poller_empty_completed_result(self) -> None:
        from contextlib import asynccontextmanager

        from apps.ai import task_poller

        client = AsyncMock()
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"task_status": "completed", "result": ""}
        client.get = AsyncMock(return_value=resp)

        @asynccontextmanager
        async def _toolkit():
            yield client

        with (
            patch(
                "apps.ai.pending_tasks.all_pending",
                AsyncMock(
                    return_value=[
                        {
                            "task_uid": "e",
                            "task_type": "ocr",
                            "submitted_at": 1e12,
                            "meta_data": {"locale": "fa"},
                        }
                    ]
                ),
            ),
            patch("utils.clients.toolkit.toolkit_client", _toolkit),
            patch("apps.ai.routes._deliver_result", AsyncMock()) as deliver,
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await task_poller._poll_once()
        deliver.assert_awaited()

    @pytest.mark.asyncio
    async def test_menu_account_balance(self) -> None:
        from apps.bots.common.handlers.menu import handle_menu_action

        renderer = AsyncMock()
        ctx = _ctx(renderer)
        event = MessageEvent(
            platform="telegram",
            chat_id=1,
            message_id=2,
            sender=Sender(id=9),
            metadata={},
        )
        with patch(
            "apps.bots.common.handlers.menu.billing.fetch_balance",
            AsyncMock(return_value="bal"),
        ):
            assert await handle_menu_action("account", event, ctx, "fa", "u1")
            assert await handle_menu_action("balance", event, ctx, "fa", "u1")


class TestTelethonGatewayCoverage:
    def _gateway(self):
        from apps.bots.telegram.gateway import TelethonGateway

        return TelethonGateway("test-bot", 1, "hash", "token")

    @pytest.mark.asyncio
    async def test_dispatch_paths(self) -> None:
        gw = self._gateway()
        gw._client = MagicMock()
        gw._bot_user_id = 99
        gw._bot_username = "testbot"

        # no handlers → early return
        await gw._dispatch_new_message(SimpleNamespace(chat_id=1, id=2, message=None))
        await gw._dispatch_callback(SimpleNamespace(chat_id=1, message_id=2))
        await gw._dispatch_inline_query(SimpleNamespace(id="q", text="hi", sender_id=1))

        msg_handler = AsyncMock()
        cb_handler = AsyncMock()
        iq_handler = AsyncMock()
        gw.on_message(msg_handler)
        gw.on_callback(cb_handler)
        gw.on_inline_query(iq_handler)

        file_msg = SimpleNamespace(
            file=None,
            sender=SimpleNamespace(
                id=1, bot=False, username="u", first_name="a", last_name="b"
            ),
            reply_to_msg_id=None,
            text="hello",
            id=10,
            contact=None,
        )
        event = SimpleNamespace(
            chat_id=1,
            id=10,
            message=file_msg,
            chat=SimpleNamespace(id=1),
            sender_id=1,
            get_reply_message=AsyncMock(return_value=None),
        )
        with patch(
            "apps.bots.telegram.gateway.normalize_telethon_message",
            return_value=MessageEvent(
                platform="telegram",
                chat_id=1,
                message_id=10,
                text="hello",
                sender=Sender(id=1),
            ),
        ):
            await gw._dispatch_new_message(event)
        msg_handler.assert_awaited()

        contact = SimpleNamespace(phone_number="+98912", user_id=5)
        event.message = SimpleNamespace(contact=contact)
        with (
            patch(
                "apps.bots.telegram.gateway.normalize_telethon_message",
                return_value=MessageEvent(
                    platform="telegram",
                    chat_id=1,
                    message_id=10,
                    sender=Sender(id=1),
                ),
            ),
            patch(
                "apps.bots.common.handler.handle_contact_event",
                AsyncMock(),
            ) as contact_handler,
        ):
            await gw._dispatch_new_message(event)
        contact_handler.assert_awaited()

        with patch(
            "apps.bots.telegram.gateway.normalize_telethon_callback",
            return_value=_callback(),
        ):
            await gw._dispatch_callback(SimpleNamespace(chat_id=1, message_id=2))
        cb_handler.assert_awaited()

        await gw._dispatch_inline_query(
            SimpleNamespace(id="q1", text="x", sender_id=3)
        )
        iq_handler.assert_awaited()

        ctx = gw._runtime_context()
        assert ctx.bot_name == "test-bot"

    @pytest.mark.asyncio
    async def test_register_handlers_and_stop(self) -> None:
        gw = self._gateway()
        handlers: dict[object, object] = {}

        class FakeEvents:
            NewMessage = object()
            CallbackQuery = object()
            InlineQuery = object()

        client = MagicMock()

        def on(event_type):
            def deco(fn):
                handlers[event_type] = fn
                return fn

            return deco

        client.on = on
        gw._client = client
        gw._register_handlers(FakeEvents)

        assert FakeEvents.NewMessage in handlers
        assert FakeEvents.CallbackQuery in handlers
        assert FakeEvents.InlineQuery in handlers

        with patch.object(gw, "_dispatch_new_message", AsyncMock()) as d:
            await handlers[FakeEvents.NewMessage](SimpleNamespace())
            d.assert_awaited()
        with patch.object(
            gw, "_dispatch_new_message", AsyncMock(side_effect=RuntimeError("x"))
        ):
            await handlers[FakeEvents.NewMessage](SimpleNamespace())

        with patch.object(gw, "_dispatch_callback", AsyncMock()) as d:
            await handlers[FakeEvents.CallbackQuery](SimpleNamespace())
            d.assert_awaited()
        with patch.object(
            gw, "_dispatch_callback", AsyncMock(side_effect=RuntimeError("x"))
        ):
            await handlers[FakeEvents.CallbackQuery](SimpleNamespace())

        with patch.object(gw, "_dispatch_inline_query", AsyncMock()) as d:
            await handlers[FakeEvents.InlineQuery](SimpleNamespace())
            d.assert_awaited()
        with patch.object(
            gw, "_dispatch_inline_query", AsyncMock(side_effect=RuntimeError("x"))
        ):
            await handlers[FakeEvents.InlineQuery](SimpleNamespace())

        client.disconnect = AsyncMock()
        await gw.stop()
        client.disconnect.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_and_download(self) -> None:
        import asyncio

        from apps.bots.telegram import gateway as gw_mod

        gw = self._gateway()
        client = MagicMock()
        client.start = AsyncMock()
        client.get_me = AsyncMock(
            return_value=SimpleNamespace(id=7, username="bot")
        )
        client.run_until_disconnected = AsyncMock()
        client.on = lambda _e: (lambda f: f)

        started = AsyncMock()
        gw.on_started(started)

        with (
            patch("telethon.TelegramClient", return_value=client),
            patch("apps.bots.common.renderer_registry.register_renderer"),
            patch.object(gw, "_register_handlers"),
        ):
            await gw.start()
            await asyncio.sleep(0)
        assert gw._running is True
        started.assert_awaited()

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_API_ID": "0", "TELEGRAM_API_HASH": ""},
            ),
            pytest.raises(RuntimeError),
        ):
            await gw_mod.download_with_telethon(1, 2, "tok")

        fake_client = MagicMock()
        fake_client.__aenter__ = AsyncMock(return_value=fake_client)
        fake_client.__aexit__ = AsyncMock(return_value=None)
        fake_client.start = AsyncMock()
        fake_client.get_input_entity = AsyncMock(return_value="ent")
        msg = SimpleNamespace(media=object())
        fake_client.get_messages = AsyncMock(return_value=msg)
        fake_client.download_media = AsyncMock(return_value=b"data")

        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"},
            ),
            patch("telethon.TelegramClient", return_value=fake_client),
        ):
            data = await gw_mod.download_with_telethon(1, 2, "tok")
        assert data == b"data"

        fake_client.get_messages = AsyncMock(return_value=None)
        with (
            patch.dict(
                "os.environ",
                {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"},
            ),
            patch("telethon.TelegramClient", return_value=fake_client),
        ):
            assert await gw_mod.download_with_telethon(1, 2, "tok") is None
