"""Tests for apps/bots/common modules."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common import (
    actions,
    billing,
    context,
    link_router,
    media_flow,
    onboarding,
    settings,
)
from apps.bots.common.events import MessageEvent, MessageRef, Sender
from apps.bots.common.link_router import LinkKind
from apps.bots.common.models import BotUser


class TestLinkRouter:
    def test_classify_youtube(self) -> None:
        assert link_router.classify_url("https://youtu.be/abc123") == LinkKind.youtube

    def test_classify_gdrive(self) -> None:
        assert (
            link_router.classify_url("https://drive.google.com/file/d/abc/view")
            == LinkKind.gdrive
        )

    def test_classify_file(self) -> None:
        assert link_router.classify_url("https://x.com/doc.pdf") == LinkKind.file

    def test_classify_webpage(self) -> None:
        assert (
            link_router.classify_url("https://example.com/article") == LinkKind.webpage
        )

    def test_is_media_file_url(self) -> None:
        assert link_router.is_media_file_url("https://x.com/a.pdf")
        assert link_router.is_audio_video_url("https://x.com/a.mp3")


class TestContext:
    def test_should_respond_private(self) -> None:
        event = MessageEvent(chat_type="private", text="hi")
        assert context.should_respond_in_group(event, "bot", 1)

    def test_should_respond_group_mention(self) -> None:
        event = MessageEvent(
            chat_type="supergroup",
            text="@mybot hello",
        )
        assert context.should_respond_in_group(event, "mybot", 99)

    def test_should_not_respond_group_without_mention(self) -> None:
        event = MessageEvent(chat_type="supergroup", text="hello")
        assert not context.should_respond_in_group(event, "mybot", 99)

    def test_should_respond_group_reply_to_bot(self) -> None:
        event = MessageEvent(
            chat_type="supergroup",
            text="hello",
            reply_to=MessageRef(message_id=5, metadata={"sender_id": 42}),
        )
        assert context.should_respond_in_group(event, "mybot", 42)

    @pytest.mark.asyncio
    async def test_chat_completion_returns_error_on_failure(self) -> None:
        event = MessageEvent(text="hi")
        with patch(
            "apps.bots.common.context.CompletionClient.complete",
            AsyncMock(side_effect=Exception("down")),
        ):
            result = await context.chat_completion(event, "hi", locale="en")
        assert result

    @pytest.mark.asyncio
    async def test_store_and_fetch_message(self) -> None:
        stored = await context.store_message(
            platform="telegram",
            platform_chat_id="1",
            platform_message_id="10",
            role="user",
            content="hello",
            user_id="u1",
        )
        fetched = await context.get_message_by_platform_id("telegram", "1", "10")
        assert fetched is not None
        assert fetched.content == "hello"
        assert stored.uid == fetched.uid


class TestOnboarding:
    def test_detect_locale_fa_default(self) -> None:
        assert onboarding.detect_locale(None) == "fa"

    def test_detect_locale_en(self) -> None:
        assert onboarding.detect_locale("en-US") == "en"

    def test_typed_phone_rejection(self) -> None:
        assert onboarding.is_typed_phone_rejection("+989121234567")
        assert not onboarding.is_typed_phone_rejection("/start")

    def test_contact_mismatch(self) -> None:
        event = MessageEvent(sender=Sender(id=1))
        assert onboarding.contact_user_id_matches(event, 1)
        assert not onboarding.contact_user_id_matches(event, 2)

    def test_onboarding_messages(self) -> None:
        assert onboarding.onboarding_success_message("en")
        assert onboarding.contact_mismatch_message("fa")
        assert onboarding.typed_phone_rejection_message("en")


class TestActions:
    def test_map_callback_action(self) -> None:
        assert actions.map_callback_action("summarize") == "summarize"
        assert actions.map_callback_action("unknown") is None

    @pytest.mark.asyncio
    async def test_run_promptic_action(self) -> None:
        with (
            patch(
                "apps.bots.common.actions.PrompticClient.execute",
                AsyncMock(return_value={"uid": "p1"}),
            ) as execute_mock,
            patch("apps.ai.pending_tasks.add", AsyncMock()) as add_mock,
        ):
            result = await actions.run_promptic_action(
                prompt_name="summarize",
                content="text",
                user_id="u1",
                target_language="fa",
                meta_data={"chat_id": 1},
            )
        assert result["uid"] == "p1"
        execute_mock.assert_awaited_once()
        add_mock.assert_awaited_once()


class TestSettings:
    @pytest.mark.asyncio
    async def test_get_user_locale_default(self) -> None:
        assert await settings.get_user_locale("missing-user") == "fa"

    @pytest.mark.asyncio
    async def test_get_user_locale_from_bot_user(self) -> None:
        user = BotUser(
            user_id="u2",
            telegram_user_id="tg2",
            preferred_language="en",
            phone_verified=True,
        )
        await user.save()
        assert await settings.get_user_locale("tg2") == "en"

    @pytest.mark.asyncio
    async def test_set_preferred_language(self) -> None:
        user = BotUser(
            user_id="u1",
            telegram_user_id="tg1",
            usso_user_id="u1",
            preferred_language="fa",
            phone_verified=True,
        )
        await user.save()
        with patch(
            "apps.bots.common.settings.usso_accounts_client",
        ) as mock_ctx:
            mock_client = AsyncMock()
            mock_ctx.return_value.__aenter__.return_value = mock_client
            updated = await settings.set_preferred_language("tg1", "en")
        assert updated is not None
        assert updated.preferred_language == "en"


class TestBilling:
    @pytest.mark.asyncio
    async def test_fetch_balance(self) -> None:
        with patch(
            "apps.bots.common.billing.SaasClient.get_quota",
            AsyncMock(return_value={"quota": "10", "unit": "coins"}),
        ):
            msg = await billing.fetch_balance("u1", locale="en")
        assert "10" in msg

    @pytest.mark.asyncio
    async def test_fetch_balance_error(self) -> None:
        with patch(
            "apps.bots.common.billing.SaasClient.get_quota",
            AsyncMock(side_effect=Exception("down")),
        ):
            msg = await billing.fetch_balance("u1", locale="en")
        assert msg

    @pytest.mark.asyncio
    async def test_fetch_products_page_empty(self) -> None:
        with patch(
            "apps.bots.common.billing.ShopClient.list_products",
            AsyncMock(return_value={"items": [], "total": 0}),
        ):
            msg, products, total = await billing.fetch_products_page(locale="en")
        assert products == []
        assert total == 0
        assert msg

    @pytest.mark.asyncio
    async def test_fetch_products_page_with_items(self) -> None:
        with patch(
            "apps.bots.common.billing.ShopClient.list_products",
            AsyncMock(
                return_value={
                    "items": [{"uid": "p1", "name": "Pack", "unit_price": 10}],
                    "total": 1,
                }
            ),
        ):
            msg, products, total = await billing.fetch_products_page(
                locale="en", page=0
            )
        assert len(products) == 1
        assert total == 1
        assert "1" in msg

    @pytest.mark.asyncio
    async def test_purchase_product(self) -> None:
        with patch(
            "apps.bots.common.billing.ShopClient.purchase",
            AsyncMock(return_value="https://pay.test/checkout"),
        ):
            url = await billing.purchase_product("p1", "u1", "https://t.me/bot")
        assert url.startswith("https://pay")


class TestSafeFilename:
    """_safe_filename must strip characters that break strict URL validators
    (e.g. Soniox's audio_url pattern) once the media service embeds the raw
    filename in a public URL path segment."""

    def test_strips_spaces_and_keeps_extension(self) -> None:
        name = media_flow._safe_filename(
            "audio", "War report66 mohammadi 304405 part2.mp3"
        )
        assert " " not in name
        assert name.endswith(".mp3")
        assert name == "War_report66_mohammadi_304405_part2.mp3"

    def test_strips_parens_quotes_and_other_unsafe_chars(self) -> None:
        name = media_flow._safe_filename("document", 'weird (name) "quoted".pdf')
        assert name == "weird_name_quoted.pdf"

    def test_generates_fallback_name_when_stem_is_entirely_unsafe(self) -> None:
        name = media_flow._safe_filename("photo", "____.jpg")
        assert name.startswith("photo_")
        assert name.endswith(".jpg")

    def test_no_extension_still_sanitized(self) -> None:
        name = media_flow._safe_filename("document", "no extension here")
        assert name == "no_extension_here"

    def test_empty_name_falls_back_to_generated_name(self) -> None:
        name = media_flow._safe_filename("voice", "")
        assert name.startswith("voice_")
        assert name.endswith(".ogg")

    def test_safe_ascii_name_is_left_untouched(self) -> None:
        name = media_flow._safe_filename("document", "report_final-v2.docx")
        assert name == "report_final-v2.docx"


class TestMediaFlow:
    def test_toolkit_task_meta(self) -> None:
        event = MessageEvent(
            chat_id=1,
            message_id=2,
            sender=Sender(id=3),
        )
        meta = media_flow.toolkit_task_meta(
            event=event,
            bot_name="bot",
            response_message_id=2,
            content_type="document",
            user_id="u1",
        )
        assert meta["chat_id"] == 1
        assert meta["bot_name"] == "bot"

    @pytest.mark.asyncio
    async def test_submit_ocr_url(self) -> None:
        with patch(
            "apps.bots.common.media_flow.OCRClient.submit",
            AsyncMock(return_value={"uid": "ocr-1"}),
        ):
            uid = await media_flow.submit_ocr_url(
                "https://x.com/a.pdf", "u1", {"chat_id": 1}
            )
        assert uid == "ocr-1"

    @pytest.mark.asyncio
    async def test_submit_transcribe_url(self) -> None:
        with patch(
            "apps.bots.common.media_flow.TranscribeClient.submit",
            AsyncMock(return_value={"uid": "tr-1"}),
        ):
            uid = await media_flow.submit_transcribe_url(
                "https://x.com/a.ogg", "u1", {"chat_id": 1}
            )
        assert uid == "tr-1"

    @pytest.mark.asyncio
    async def test_webhook_url_for(self) -> None:
        url = media_flow.webhook_url_for("ocr_webhook")
        assert "ocr" in url

    @pytest.mark.asyncio
    async def test_submit_youtube_registers_pending(self) -> None:
        with (
            patch(
                "apps.bots.common.media_flow.YoutubeClient.submit",
                AsyncMock(return_value={"uid": "yt-1"}),
            ),
            patch(
                "apps.ai.pending_tasks.add",
                AsyncMock(),
            ) as add_mock,
        ):
            uid = await media_flow.submit_youtube("vid", "u1", {"chat_id": 1})
        assert uid == "yt-1"
        add_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_artifact(self) -> None:
        artifact = await media_flow.save_artifact(
            user_id="u1",
            source_type="ocr",
            content="extracted",
        )
        assert artifact.content == "extracted"


class TestTaskPoller:
    @pytest.mark.asyncio
    async def test_handle_completed_ocr_task(self) -> None:
        from apps.ai.task_poller import _handle_completed_task

        task = {
            "task_uid": "ocr-1",
            "task_type": "ocr",
            "meta_data": {"chat_id": 1, "bot_name": "b", "message_id": 2},
        }
        with (
            patch(
                "apps.ai.clients.OCRClient.get_result",
                AsyncMock(return_value="text"),
            ),
            patch("apps.ai.routes._deliver_result", AsyncMock()) as deliver,
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _handle_completed_task(task)
        deliver.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notify_timeout(self) -> None:
        from apps.ai.task_poller import _notify_timeout

        task = {
            "task_uid": "ocr-2",
            "meta_data": {"chat_id": 1, "bot_name": "b", "message_id": 2},
        }
        renderer = AsyncMock()
        with (
            patch(
                "apps.bots.common.renderer_registry.get_renderer",
                return_value=renderer,
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _notify_timeout(task)
        renderer.edit_message.assert_awaited_once()


class TestBale:
    @pytest.mark.asyncio
    async def test_bale_webhook_message(self, client) -> None:
        import asyncio

        payload = {
            "message": {
                "message_id": 1,
                "text": "/help",
                "chat": {"id": 100, "type": "private"},
                "from": {"id": 1, "first_name": "Test"},
            }
        }
        scheduled: list[asyncio.Task] = []

        def schedule(coro: object) -> asyncio.Task:
            task = asyncio.get_running_loop().create_task(coro)
            scheduled.append(task)
            return task

        with (
            patch("apps.bots.bale.routes.asyncio.create_task", side_effect=schedule),
            patch(
                "apps.bots.bale.routes.handle_bale_update",
                AsyncMock(),
            ) as handle_mock,
        ):
            resp = await client.post("/bale/webhook/test_bot", json=payload)
            if scheduled:
                await scheduled[0]
        assert resp.status_code == 200
        handle_mock.assert_awaited_once()

    def test_normalize_bale_message(self) -> None:
        from apps.bots.bale.normalizer import normalize_bale_message

        event = normalize_bale_message(
            {
                "message_id": 1,
                "text": "hi",
                "chat": {"id": 10},
                "from": {"id": 2},
            },
            "bot",
        )
        assert event.platform == "bale"
        assert event.text == "hi"


class TestWebhookErrors:
    @pytest.mark.asyncio
    async def test_notify_task_error(self) -> None:
        from apps.ai.routes import TaskWebhookPayload, _notify_task_error

        payload = TaskWebhookPayload(
            uid="t1",
            task_status="error",
            meta_data={"chat_id": 1, "bot_name": "b", "message_id": 2},
            task_report="failed",
        )
        renderer = AsyncMock()
        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _notify_task_error(payload)
        renderer.edit_message.assert_awaited_once()
