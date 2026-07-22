"""Extended coverage tests for redesigned bot modules."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.ai.clients import CompletionClient, WebpageClient, YoutubeClient
from apps.bots.common import context, media_flow, onboarding
from apps.bots.common.events import (
    CallbackEvent,
    FileRef,
    MessageEvent,
    MessageRef,
    PlatformCapabilities,
    Sender,
)
from apps.bots.common.handler import (
    BotRuntimeContext,
    handle_contact_event,
    handle_message_event,
)
from apps.bots.common.models import Artifact, BotUser


def _patch_toolkit(client: AsyncMock):
    return patch(
        "apps.ai.clients.toolkit_client",
        side_effect=lambda *args, **kwargs: _client_ctx(client),
    )


@asynccontextmanager
async def _client_ctx(client: AsyncMock) -> AsyncGenerator[AsyncMock]:
    yield client


def _response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class FakeRenderer:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.contact_requests: list[tuple] = []
        self.typing: list = []
        self.events: list[str] = []

    async def send_typing(self, chat_id: int | str) -> None:
        self.typing.append(chat_id)

    async def send_text(self, chat_id, text_value, reply_to=None, reply_keyboard=None):
        self.sent.append((chat_id, text_value, reply_to))
        return MagicMock(id=99)

    async def send_inline_text(
        self, chat_id, text_value, inline_keyboard, reply_to=None
    ):
        self.sent.append((chat_id, text_value, reply_to))
        return MagicMock(id=99)

    async def edit_message(
        self, chat_id, message_id, text, inline_keyboard=None
    ) -> None:
        self.events.append("edit_message")

    async def answer_inline_query(self, query_id, text_value, raw_event=None) -> None:
        self.events.append("answer_inline_query")

    async def answer_callback(self, callback_id, text_value="", raw_event=None) -> None:
        pass

    async def send_contact_request(self, chat_id, text_value) -> None:
        self.contact_requests.append((chat_id, text_value))

    async def download_attached_file(self, event):
        if event.file and event.file.file_name.endswith(".txt"):
            return b"plain text content", "notes.txt"
        return b"%PDF", "doc.pdf"

    async def download_document(self, chat_id, message_id):
        return b"document body"


def _ctx(renderer: FakeRenderer) -> BotRuntimeContext:
    return BotRuntimeContext(
        bot_name="bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(max_text_chars=4096),
    )


def _verified_user() -> BotUser:
    return BotUser(
        user_id="u1",
        telegram_user_id="tg1",
        usso_user_id="u1",
        phone_verified=True,
        preferred_language="fa",
    )


@pytest.mark.asyncio
async def test_completion_client() -> None:
    client = AsyncMock()
    client.post = AsyncMock(
        return_value=_response({"choices": [{"message": {"content": "hi"}}]})
    )
    with _patch_toolkit(client):
        result = await CompletionClient.complete([{"role": "user", "content": "x"}])
    assert result == "hi"


@pytest.mark.asyncio
async def test_youtube_client_submit_and_get() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "yt-1"}))
    client.get = AsyncMock(
        return_value=_response({"task_status": "completed", "result": "transcript"})
    )
    with _patch_toolkit(client):
        created = await YoutubeClient.submit("abc", "u1")
        result = await YoutubeClient.get_result("yt-1")
    assert created["uid"] == "yt-1"
    assert result == "transcript"


@pytest.mark.asyncio
async def test_webpage_client_submit() -> None:
    client = AsyncMock()
    client.post = AsyncMock(return_value=_response({"uid": "wp-1"}))
    with _patch_toolkit(client):
        result = await WebpageClient.submit(
            "https://example.com",
            "u1",
            "https://bot/hook",
            meta_data={"chat_id": 1},
        )
    assert result["uid"] == "wp-1"
    client.post.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_reply_chain_messages() -> None:
    parent = await context.store_message(
        platform="telegram",
        platform_chat_id="1",
        platform_message_id="1",
        role="user",
        content="first",
        user_id="u1",
    )
    event = MessageEvent(
        platform="telegram",
        chat_id=1,
        message_id=2,
        reply_to=MessageRef(message_id="1"),
    )
    messages = await context.build_reply_chain_messages(event, "second")
    assert messages[0]["content"] == "first"
    assert messages[-1]["content"] == "second"
    assert parent.uid


@pytest.mark.asyncio
async def test_build_reply_chain_with_artifact() -> None:
    artifact = Artifact(user_id="u1", source_type="ocr", content="OCR BODY")
    await artifact.save()
    await context.store_message(
        platform="telegram",
        platform_chat_id="9",
        platform_message_id="11",
        role="assistant",
        content="see attachment",
        user_id="u1",
        artifact_id=str(artifact.id),
    )
    event = MessageEvent(
        platform="telegram",
        chat_id=9,
        message_id=12,
        reply_to=MessageRef(message_id="11"),
    )
    messages = await context.build_reply_chain_messages(event, "follow up")
    assert "OCR BODY" in messages[0]["content"]


@pytest.mark.asyncio
async def test_onboarding_create_bot_user_from_contact() -> None:
    event = MessageEvent(
        platform="telegram",
        sender=Sender(id=555),
        metadata={"language_code": "en"},
    )
    mock_user = MagicMock(uid="usso-555")
    with patch(
        "apps.bots.common.onboarding.usso_accounts_client",
    ) as mock_ctx:
        mock_client = AsyncMock()
        mock_client.get_user_by_identifier = AsyncMock(return_value=None)
        mock_client.get_or_create_user_by_identifier = AsyncMock(return_value=mock_user)
        mock_client.link_identifier = AsyncMock()
        mock_ctx.return_value.__aenter__.return_value = mock_client
        bot_user = await onboarding.get_or_create_bot_user_from_contact(
            event, "+989121234567"
        )
    assert bot_user.phone_verified
    assert bot_user.usso_user_id == "usso-555"
    assert bot_user.usso_synced is True


@pytest.mark.asyncio
async def test_onboarding_falls_back_locally_when_usso_unavailable() -> None:
    """Onboarding must not block the user when USSO is unreachable."""
    event = MessageEvent(
        platform="telegram",
        sender=Sender(id=556),
        metadata={"language_code": "en"},
    )
    with patch(
        "apps.bots.common.onboarding.usso_accounts_client",
        side_effect=Exception("usso unreachable"),
    ):
        bot_user = await onboarding.get_or_create_bot_user_from_contact(
            event, "+989121234567"
        )
    assert bot_user.phone_verified
    assert bot_user.usso_user_id == ""
    assert bot_user.usso_synced is False
    assert bot_user.user_id == "556"


@pytest.mark.asyncio
async def test_media_flow_submit_url_webpage() -> None:
    event = MessageEvent(chat_id=1, message_id=2, sender=Sender(id=3))
    with (
        patch(
            "apps.bots.common.media_flow.WebpageClient.submit",
            AsyncMock(return_value={"uid": "wp-2"}),
        ),
        patch("apps.ai.pending_tasks.add", AsyncMock()) as add_mock,
    ):
        uid = await media_flow.submit_url(
            event=event,
            bot_name="bot",
            url="https://example.com/article",
            response_message_id=2,
            user_id="u1",
        )
    assert uid == "wp-2"
    add_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_media_flow_submit_file_bytes_transcribe() -> None:
    event = MessageEvent(chat_id=1, message_id=2, sender=Sender(id=3))
    with (
        patch(
            "apps.bots.common.media_flow.upload_bytes",
            AsyncMock(return_value="https://media/file.ogg"),
        ),
        patch(
            "apps.bots.common.media_flow.submit_transcribe_url",
            AsyncMock(return_value="tr-1"),
        ),
        patch("apps.ai.pending_tasks.add", AsyncMock()),
    ):
        uid = await media_flow.submit_file_bytes(
            event=event,
            bot_name="bot",
            file_bytes=b"audio",
            file_name="voice.ogg",
            response_message_id=2,
            content_type="voice",
            user_id="u1",
        )
    assert uid == "tr-1"


@pytest.mark.asyncio
async def test_handler_txt_file_inline_extraction() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=1,
        message_id=5,
        sender=Sender(id="tg1"),
        file=FileRef(file_id="f1", file_name="notes.txt"),
    )
    with patch(
        "apps.bots.common.handler.require_verified_user",
        AsyncMock(return_value=("usso-1", _verified_user())),
    ):
        await handle_message_event(event, _ctx(renderer))
    assert len(renderer.sent) >= 1


@pytest.mark.asyncio
async def test_handler_url_message_dispatches() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=1,
        message_id=5,
        sender=Sender(id="tg1"),
        text="https://youtu.be/abc123",
    )
    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.urls.media_flow.submit_url",
            AsyncMock(return_value="yt-1"),
        ) as submit_mock,
    ):
        await handle_message_event(event, _ctx(renderer))
    submit_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_balance_command() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=1, message_id=5, sender=Sender(id="tg1"), text="/balance"
    )
    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.handler.billing.fetch_balance",
            AsyncMock(return_value="balance: 10"),
        ),
    ):
        await handle_message_event(event, _ctx(renderer))
    assert renderer.sent


@pytest.mark.asyncio
async def test_handle_contact_event_success() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(chat_id=1, message_id=5, sender=Sender(id=42))
    with patch(
        "apps.bots.common.handler.get_or_create_bot_user_from_contact",
        AsyncMock(),
    ):
        await handle_contact_event(
            event,
            _ctx(renderer),
            phone_number="+1",
            contact_user_id=42,
        )
    assert renderer.sent


@pytest.mark.asyncio
async def test_handle_contact_event_onboarding_failure_notifies_user() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(chat_id=1, message_id=5, sender=Sender(id=42))
    with patch(
        "apps.bots.common.handler.get_or_create_bot_user_from_contact",
        AsyncMock(side_effect=Exception("usso unreachable")),
    ):
        await handle_contact_event(
            event,
            _ctx(renderer),
            phone_number="+1",
            contact_user_id=42,
        )
    assert len(renderer.sent) == 1
    assert renderer.sent[0][0] == 1


@pytest.mark.asyncio
async def test_task_poller_poll_once_timeout() -> None:
    import time

    from apps.ai import task_poller

    old_task = {
        "task_uid": "old-1",
        "task_type": "youtube",
        "submitted_at": time.time() - 4000,
        "meta_data": {"chat_id": 1, "bot_name": "b", "message_id": 2},
    }
    with (
        patch("apps.ai.pending_tasks.all_pending", AsyncMock(return_value=[old_task])),
        patch("apps.ai.task_poller._notify_timeout", AsyncMock()) as timeout_mock,
    ):
        await task_poller._poll_once()
    timeout_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_result_error_status() -> None:
    from apps.ai.routes import TaskWebhookPayload, _deliver_result

    payload = TaskWebhookPayload(
        uid="e1",
        task_status="error",
        meta_data={"chat_id": 1, "bot_name": "b", "message_id": 2},
        error="boom",
    )
    with patch("apps.ai.routes._notify_task_error", AsyncMock()) as notify:
        await _deliver_result(payload, "document")
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_result_uses_renderer_registry() -> None:
    from apps.ai.routes import TaskWebhookPayload, _deliver_result
    from apps.bots.common.renderer_registry import register_renderer

    renderer = AsyncMock()
    register_renderer("bot-a", renderer)
    payload = TaskWebhookPayload(
        uid="ok-1",
        task_status="completed",
        result="ocr text",
        meta_data={
            "chat_id": 1,
            "bot_name": "bot-a",
            "message_id": 2,
            "user_id": "u1",
            "locale": "fa",
            "reply_to_message_id": 1,
        },
    )
    with patch("apps.ai.pending_tasks.remove", AsyncMock()):
        await _deliver_result(payload, "document")
    renderer.send_inline_text.assert_awaited()


@pytest.mark.asyncio
async def test_notify_task_error_insufficient_credits_renderer() -> None:
    from apps.ai.routes import TaskWebhookPayload, _notify_task_error
    from apps.bots.common.renderer_registry import register_renderer

    renderer = AsyncMock()
    register_renderer("bot-b", renderer)
    payload = TaskWebhookPayload(
        uid="err-1",
        task_status="error",
        meta_data={"chat_id": 1, "bot_name": "bot-b", "message_id": 2, "locale": "fa"},
        error="Insufficient credits",
    )
    with patch("apps.ai.pending_tasks.remove", AsyncMock()):
        await _notify_task_error(payload)
    renderer.edit_message.assert_awaited_once()


@pytest.mark.asyncio

async def test_deliver_md_result_short_text() -> None:
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    await deliver_md_result(
        renderer,
        chat_id=1,
        message_id=2,
        result="short",
        content_type="document",
        user_id="u1",
        locale="fa",
        include_actions=False,
    )
    renderer.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_md_result_converts_markdown_for_inline_send() -> None:
    """Regression: renderers use parse_mode="html"; AI results are Markdown.

    Without conversion, users see literal "**" instead of bold text.
    """
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    await deliver_md_result(
        renderer,
        chat_id=1,
        message_id=2,
        result="**خلاصه:** این *مهم* است.",
        content_type="promptic",
        user_id="u1",
        locale="fa",
        include_actions=False,
    )
    sent_text = renderer.send_text.await_args.args[1]
    assert "**" not in sent_text
    assert "<b>خلاصه:</b>" in sent_text
    assert "<i>مهم</i>" in sent_text


@pytest.mark.asyncio
async def test_deliver_md_result_long_text_uploads_file() -> None:
    from apps.bots.common import media_flow
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    long_text = "x" * (media_flow.MD_FILE_THRESHOLD_CHARS + 1)
    with patch(
        "apps.bots.common.delivery.MediaClient.upload",
        AsyncMock(return_value="https://media.test/r.md"),
    ):
        await deliver_md_result(
            renderer,
            chat_id=1,
            message_id=2,
            result=long_text,
            content_type="voice",
            user_id="u1",
            locale="en",
        )
    renderer.send_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_md_result_caches_raw_markdown_for_convert_buttons() -> None:
    """Regression: convert-to-Word/Markdown buttons read this cache back
    (see apps/ai/result_content_cache.py + callbacks._get_content) since
    Telegram strips '#'/'**' syntax once a message is sent as rich text."""
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    renderer.send_text.return_value = MagicMock(id=999)
    with patch(
        "apps.bots.common.delivery.result_content_cache.save", AsyncMock()
    ) as save_mock:
        await deliver_md_result(
            renderer,
            chat_id=1,
            message_id=2,
            result="# Heading\n**bold**",
            content_type="promptic",
            user_id="u1",
            locale="fa",
            include_actions=False,
        )
    save_mock.assert_awaited_once_with(999, "# Heading\n**bold**")


@pytest.mark.asyncio
async def test_deliver_md_result_long_text_upload_keeps_raw_markdown() -> None:
    """The uploaded .md file must stay real Markdown, not HTML-converted."""
    from apps.bots.common import media_flow
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    long_text = "**bold**\n" + "x" * media_flow.MD_FILE_THRESHOLD_CHARS
    upload_mock = AsyncMock(return_value="https://media.test/r.md")
    with patch("apps.bots.common.delivery.MediaClient.upload", upload_mock):
        await deliver_md_result(
            renderer,
            chat_id=1,
            message_id=2,
            result=long_text,
            content_type="document",
            user_id="u1",
            locale="fa",
        )
    uploaded_bytes = upload_mock.await_args.args[0]
    assert uploaded_bytes == long_text.encode("utf-8")


def test_is_insufficient_credit_error() -> None:
    from apps.bots.common.delivery import is_insufficient_credit_error

    assert is_insufficient_credit_error("Insufficient quota")
    assert is_insufficient_credit_error("موجودی کافی نیست")
    assert not is_insufficient_credit_error("network timeout")


def test_renderer_registry() -> None:
    from apps.bots.common.renderer_registry import get_renderer, register_renderer

    renderer = object()
    register_renderer("test-bot", renderer)
    assert get_renderer("test-bot") is renderer
    assert get_renderer("missing") is None

    from apps.bots.common import keyboards as kb
    from apps.bots.common.menu import resolve_menu_action

    assert kb.main_menu_keyboard().rows
    assert kb.settings_language_keyboard().rows
    assert kb.buy_credits_keyboard().rows
    assert kb.md_result_keyboard("document", media_url="https://x").rows
    assert kb.products_keyboard(
        [{"uid": "p1", "name": "Pack", "unit_price": 10}], 0, 1
    ).rows
    assert resolve_menu_action("/help") == "help"


@pytest.mark.asyncio
async def test_handler_promptic_action_callback() -> None:
    from apps.bots.common.handler import handle_callback_event

    renderer = FakeRenderer()
    event = CallbackEvent(
        chat_id=1,
        message_id=2,
        callback_id="cb4",
        data="action:summarize",
        message_text="document content",
        sender=Sender(id="tg1"),
    )
    with (
        patch(
            "apps.bots.common.callbacks.require_verified_callback",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.callbacks.actions.run_promptic_action",
            AsyncMock(),
        ) as run_action,
    ):
        await handle_callback_event(event, _ctx(renderer))
    run_action.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_settings_callback() -> None:
    from apps.bots.common.handler import handle_callback_event

    renderer = FakeRenderer()
    event = CallbackEvent(
        chat_id=1,
        message_id=2,
        callback_id="cb1",
        data="settings:lang:en",
        sender=Sender(id="tg1"),
    )
    with patch(
        "apps.bots.common.callbacks.settings.set_preferred_language",
        AsyncMock(),
    ):
        await handle_callback_event(event, _ctx(renderer))
    assert renderer.sent


@pytest.mark.asyncio
async def test_handler_products_page_callback() -> None:
    from apps.bots.common.handler import handle_callback_event

    renderer = FakeRenderer()
    event = CallbackEvent(
        chat_id=1,
        message_id=2,
        callback_id="cb2",
        data="products_page:1",
        sender=Sender(id="tg1"),
    )
    with patch(
        "apps.bots.common.callbacks.billing.fetch_products_page",
        AsyncMock(
            return_value=("page 2", [{"uid": "p1", "name": "Pack", "unit_price": 5}], 6)
        ),
    ):
        await handle_callback_event(event, _ctx(renderer))
    assert "edit_message" in renderer.events


@pytest.mark.asyncio
async def test_handler_inline_query() -> None:
    from apps.bots.common.events import InlineQueryEvent
    from apps.bots.common.handler import handle_inline_query_event

    renderer = FakeRenderer()
    renderer.answer_inline_query = AsyncMock()
    event = InlineQueryEvent(
        platform="telegram",
        query_id="q1",
        text="what is ai?",
        sender=Sender(id=1),
    )
    with patch(
        "apps.bots.common.handler.CompletionClient.complete",
        AsyncMock(return_value="answer"),
    ):
        await handle_inline_query_event(event, _ctx(renderer))
    renderer.answer_inline_query.assert_awaited_once()


@pytest.mark.asyncio
async def test_deliver_md_result_sends_as_file_when_long() -> None:
    from apps.bots.common.delivery import deliver_md_result
    from apps.bots.common.delivery import FILE_THRESHOLD

    renderer = AsyncMock()
    long_text = "a" * (FILE_THRESHOLD + 1)
    await deliver_md_result(
        renderer,
        chat_id=1,
        message_id=2,
        result=long_text,
        content_type="document",
        user_id="u1",
        locale="fa",
    )
    assert renderer.send_document.await_count == 1


@pytest.mark.asyncio
async def test_handler_buy_product_callback() -> None:
    from apps.bots.common.handler import handle_callback_event

    renderer = FakeRenderer()
    event = CallbackEvent(
        chat_id=1,
        message_id=2,
        callback_id="cb3",
        data="buy:p1",
        sender=Sender(id="tg1"),
    )
    with (
        patch(
            "apps.bots.common.callbacks.require_verified_callback",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.callbacks.billing.purchase_product",
            AsyncMock(return_value="https://pay.test/1"),
        ),
    ):
        await handle_callback_event(event, _ctx(renderer))
    assert any("https://pay.test/1" in str(item) for item in renderer.sent)


@pytest.mark.asyncio
async def test_handler_docx_file_added_to_chat() -> None:
    import io
    import zipfile

    from apps.bots.common.docx import extract_docx_text
    from apps.bots.common.events import FileRef
    from apps.bots.common.handler import handle_message_event

    def minimal_docx(text: str) -> bytes:
        buffer = io.BytesIO()
        xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
        )
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", xml)
        return buffer.getvalue()

    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        sender=Sender(id="user-1"),
        file=FileRef(file_id="f1", file_name="notes.docx"),
        content_type="document",
    )
    docx_bytes = minimal_docx("docx body")

    async def download(_event: MessageEvent) -> tuple[bytes, str]:
        return docx_bytes, "notes.docx"

    renderer.download_attached_file = download

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.files.context.store_message",
            AsyncMock(),
        ) as store_mock,
    ):
        await handle_message_event(event, _ctx(renderer))

    store_mock.assert_awaited_once()
    assert store_mock.await_args.kwargs["content"] == extract_docx_text(docx_bytes)


@pytest.mark.asyncio
async def test_deliver_md_result_upload_failure_still_sends() -> None:
    from apps.bots.common.delivery import FILE_THRESHOLD
    from apps.bots.common.delivery import deliver_md_result

    renderer = AsyncMock()
    long_text = "x" * (FILE_THRESHOLD + 1)
    with patch(
        "apps.bots.common.delivery.MediaClient.upload",
        AsyncMock(side_effect=RuntimeError("upload failed")),
    ):
        await deliver_md_result(
            renderer,
            chat_id=1,
            message_id=2,
            result=long_text,
            content_type="document",
            user_id="u1",
            locale="fa",
        )
    renderer.send_document.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_multi_link_webpages_only() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="check https://example.com/a and https://example.com/b",
        sender=Sender(id="user-1"),
    )
    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_user())),
        ),
        patch(
            "apps.bots.common.urls.media_flow.fetch_webpages_parallel",
            AsyncMock(return_value=["content a", "content b"]),
        ),
        patch(
            "apps.bots.common.urls.context.chat_completion",
            AsyncMock(return_value="summary"),
        ),
    ):
        await handle_message_event(event, _ctx(renderer))
    assert "edit_message" in renderer.events
