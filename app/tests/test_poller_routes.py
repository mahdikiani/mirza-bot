"""Tests for poller module and AI webhook routes."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from apps.ai import task_poller
from apps.ai.routes import (
    TaskWebhookPayload,
    _process_ocr_webhook,
    _process_transcribe_webhook,
)
from apps.bots.runtime import poller


@dataclass
class MockUpdate:
    update_id: int


class TestCbToDict:
    def test_cb_to_dict_propagates_caption_for_document_messages(self) -> None:
        """
        A result delivered as a file has its content in `caption`, not `text`.

        Dropping caption here (as the poller once did) left
        normalize_bale_callback's `text or caption` fallback with nothing,
        so action buttons on file-delivered results always came back empty
        once the redis content cache wasn't the source that served them.
        """
        chat = SimpleNamespace(id=42)
        from_user = SimpleNamespace(id=7)
        message = SimpleNamespace(
            message_id=99, chat=chat, text=None, caption="📄 نتیجه پردازش"
        )
        cb = SimpleNamespace(id="cb1", data="action:summarize", from_user=from_user, message=message)

        result = poller._cb_to_dict(cb)

        assert result["message"]["caption"] == "📄 نتیجه پردازش"
        assert result["message"]["text"] == ""
        assert result["message_id"] == 99
        assert result["chat_id"] == 42

    def test_cb_to_dict_propagates_text_for_plain_messages(self) -> None:
        chat = SimpleNamespace(id=1)
        message = SimpleNamespace(message_id=5, chat=chat, text="hello", caption=None)
        cb = SimpleNamespace(
            id="cb2", data="settings:lang:fa", from_user=None, message=message
        )

        result = poller._cb_to_dict(cb)

        assert result["message"]["text"] == "hello"
        assert result["message"]["caption"] == ""

    def test_cb_to_dict_carries_document_file_id(self) -> None:
        """
        The document's file_id must survive the manual object->dict conversion.

        Lets a long result's content be re-downloaded directly by file_id
        (see CallbackEvent.file) when the redis cache is unavailable/expired,
        since Bale's Bot API has no generic "get message by id" to fall back on.
        """
        chat = SimpleNamespace(id=42)
        document = SimpleNamespace(
            file_id="file-xyz", file_name="result.md", mime_type="text/markdown",
            file_size=2048,
        )
        message = SimpleNamespace(
            message_id=99,
            chat=chat,
            text=None,
            caption="📄 نتیجه پردازش",
            document=document,
            voice=None,
            audio=None,
            video=None,
            sticker=None,
            animation=None,
        )
        cb = SimpleNamespace(id="cb3", data="action:summarize", from_user=None, message=message)

        result = poller._cb_to_dict(cb)

        assert result["message"]["document"]["file_id"] == "file-xyz"
        assert result["message"]["document"]["file_name"] == "result.md"


class TestPollerOnce:
    @pytest.mark.asyncio
    async def test_poll_once_no_updates(self) -> None:
        bot = AsyncMock()
        bot.last_update_id = None
        bot.get_updates = AsyncMock(return_value=[])
        bot.me = "test_bot"
        bot.bot_type = "bale"
        bot.process_new_updates = AsyncMock()

        with patch("apps.bots.runtime.poller._process_updates", MagicMock()) as process:
            await poller._poll_once(bot)

        bot.get_updates.assert_awaited_once()
        process.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_once_with_updates(self) -> None:
        bot = AsyncMock()
        bot.last_update_id = None
        bot.me = "test_bot"
        bot.bot_type = "bale"
        update = MockUpdate(update_id=1)
        bot.get_updates = AsyncMock(return_value=[update])
        bot.process_new_updates = AsyncMock()

        with patch("apps.bots.runtime.poller._process_updates", MagicMock()) as process:
            await poller._poll_once(bot)

        process.assert_called_once_with(bot, [update])
        assert bot.last_update_id == 1

    @pytest.mark.asyncio
    async def test_poll_once_skips_old_updates(self) -> None:
        bot = AsyncMock()
        bot.last_update_id = 5
        bot.me = "test_bot"
        bot.bot_type = "bale"
        old_update = MockUpdate(update_id=3)
        new_update = MockUpdate(update_id=6)
        bot.get_updates = AsyncMock(return_value=[old_update, new_update])
        bot.process_new_updates = AsyncMock()

        with patch("apps.bots.runtime.poller._process_updates", MagicMock()):
            await poller._poll_once(bot)

        assert bot.last_update_id == 6

    @pytest.mark.asyncio
    async def test_poll_once_handles_error(self) -> None:
        bot = AsyncMock()
        bot.last_update_id = None
        bot.me = "test_bot"
        bot.get_updates = AsyncMock(side_effect=Exception("API error"))

        await poller._poll_once(bot)
        bot.get_updates.assert_awaited_once()


class TestPollerWorkers:
    def test_start_task_poller_creates_background_task(self) -> None:
        mock_task = MagicMock()
        with patch(
            "apps.ai.task_poller.asyncio.create_task", return_value=mock_task
        ) as mock_create:
            task_poller.start_task_poller()

        mock_create.assert_called_once()
        mock_create.call_args.args[0].close()
        mock_task.add_done_callback.assert_called_once()

    def test_start_bale_polling_creates_task(self) -> None:
        with patch("apps.bots.runtime.poller.asyncio.create_task") as mock_create:
            poller.start_bale_polling(5.0)
            mock_create.assert_called_once()
            mock_create.call_args.args[0].close()


class TestAiWebhooks:
    @pytest.mark.asyncio
    async def test_ocr_webhook_returns_accepted(
        self, client: httpx.AsyncClient
    ) -> None:
        payload = {"uid": "ocr-task-1", "task_status": "completed", "result": "text"}
        with patch("apps.ai.routes._deliver_result", AsyncMock()):
            resp = await client.post(
                "/ai/ocr/webhook/",
                json=payload,
                headers={"x-api-key": "test-webhook-key"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "accepted"}

    @pytest.mark.asyncio
    async def test_transcribe_webhook_returns_accepted(
        self, client: httpx.AsyncClient
    ) -> None:
        payload = {"uid": "tr-task-1", "task_status": "completed", "result": "text"}
        with patch("apps.ai.routes._deliver_result", AsyncMock()):
            resp = await client.post(
                "/ai/transcribe/webhook/",
                json=payload,
                headers={"x-api-key": "test-webhook-key"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "accepted"}

    @pytest.mark.asyncio
    async def test_ocr_webhook_ignores_non_completed(self) -> None:
        payload = TaskWebhookPayload(uid="ocr-1", task_status="pending")

        with patch("apps.ai.pending_tasks.get") as mock_get:
            await _process_ocr_webhook(payload)
            mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_transcribe_webhook_ignores_non_completed(self) -> None:
        payload = TaskWebhookPayload(uid="tr-1", task_status="failed")

        with patch("apps.ai.pending_tasks.get") as mock_get:
            await _process_transcribe_webhook(payload)
            mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ocr_webhook_missing_meta_returns(self) -> None:
        payload = TaskWebhookPayload(
            uid="ocr-2", task_status="completed", result="text"
        )

        with (
            patch("apps.ai.pending_tasks.get", AsyncMock(return_value={})),
            patch("apps.ai.pending_tasks.remove", AsyncMock()) as remove_mock,
        ):
            await _process_ocr_webhook(payload)
        remove_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ocr_webhook_completes_full_flow(self) -> None:
        meta = {
            "chat_id": 100,
            "bot_name": "test_bot",
            "message_id": 55,
            "content_type": "document",
            "user_id": "u1",
        }
        payload = TaskWebhookPayload(
            uid="ocr-3", task_status="completed", meta_data={}, result="ocr text"
        )
        renderer = AsyncMock()

        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": meta}),
            ),
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ocr_webhook_fetches_result_when_missing(self) -> None:
        meta = {"chat_id": 100, "bot_name": "test_bot", "message_id": 55}
        payload = TaskWebhookPayload(uid="ocr-4", task_status="completed")
        renderer = AsyncMock()

        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch(
                "apps.ai.clients.OCRClient.get_result",
                AsyncMock(return_value="fetched text"),
            ),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": meta}),
            ),
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ocr_webhook_handles_result_fetch_failure(self) -> None:
        meta = {"chat_id": 100, "bot_name": "test_bot", "message_id": 55}
        payload = TaskWebhookPayload(uid="ocr-5", task_status="completed")
        renderer = AsyncMock()

        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch(
                "apps.ai.clients.OCRClient.get_result",
                AsyncMock(side_effect=Exception("API error")),
            ),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": meta}),
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_not_awaited()
        renderer.edit_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_transcribe_webhook_handles_result_fetch_failure(self) -> None:
        meta = {"chat_id": 200, "bot_name": "test_bot", "message_id": 66}
        payload = TaskWebhookPayload(uid="tr-5", task_status="completed")
        renderer = AsyncMock()

        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch(
                "apps.ai.clients.TranscribeClient.get_result",
                AsyncMock(side_effect=Exception("API error")),
            ),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": meta}),
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _process_transcribe_webhook(payload)

        deliver_mock.assert_not_awaited()
        renderer.edit_message.assert_awaited()

    @pytest.mark.asyncio
    async def test_ocr_webhook_skips_when_no_renderer(self) -> None:
        meta = {
            "chat_id": 100,
            "bot_name": "test_bot",
            "message_id": 55,
            "user_id": "u1",
        }
        payload = TaskWebhookPayload(
            uid="ocr-6", task_status="completed", result="text"
        )

        with (
            patch("apps.ai.routes.get_renderer", return_value=None),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": meta}),
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()) as remove_mock,
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_not_awaited()
        remove_mock.assert_awaited()

    @pytest.mark.asyncio
    async def test_ocr_webhook_uses_pending_meta_only(self) -> None:
        payload_meta = {"chat_id": 1, "bot_name": "wrong", "message_id": 1}
        pending_meta = {
            "chat_id": 100,
            "bot_name": "test_bot",
            "message_id": 55,
            "user_id": "u1",
        }
        payload = TaskWebhookPayload(
            uid="ocr-7",
            task_status="completed",
            meta_data=payload_meta,
            result="ocr text",
        )
        renderer = AsyncMock()

        with (
            patch("apps.ai.routes.get_renderer", return_value=renderer),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch(
                "apps.ai.pending_tasks.get",
                AsyncMock(return_value={"meta_data": pending_meta}),
            ),
            patch("apps.ai.pending_tasks.remove", AsyncMock()),
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_awaited_once()
        assert deliver_mock.await_args.kwargs["chat_id"] == 100

    @pytest.mark.asyncio
    async def test_ocr_webhook_rejects_payload_meta_without_pending(self) -> None:
        payload_meta = {
            "chat_id": 100,
            "bot_name": "test_bot",
            "message_id": 55,
            "user_id": "u1",
        }
        payload = TaskWebhookPayload(
            uid="ocr-8",
            task_status="completed",
            meta_data=payload_meta,
            result="ocr text",
        )

        with (
            patch("apps.ai.routes.get_renderer", return_value=AsyncMock()),
            patch("apps.ai.routes.deliver_md_result", AsyncMock()) as deliver_mock,
            patch("apps.ai.pending_tasks.get", AsyncMock(return_value=None)),
            patch("apps.ai.pending_tasks.remove", AsyncMock()) as remove_mock,
        ):
            await _process_ocr_webhook(payload)

        deliver_mock.assert_not_awaited()
        remove_mock.assert_awaited_once()
