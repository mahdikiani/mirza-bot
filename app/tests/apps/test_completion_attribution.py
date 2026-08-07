"""Billing attribution for every stateless completion entry point."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common import context
from apps.bots.common.auth_gate import VerifiedUser, VerifiedUserStatus
from apps.bots.common.events import FileRef, InlineQueryEvent, MessageEvent, Sender
from apps.bots.common.handler_context import BotRuntimeContext, PlatformCapabilities
from apps.bots.common.models import BotUser


@pytest.mark.asyncio
async def test_extracted_content_completion_forwards_billing_identity() -> None:
    complete = AsyncMock(return_value="answer")

    with patch("apps.bots.common.context.CompletionClient.complete", complete):
        result = await context.extracted_content_completion(
            "document body",
            "summarize",
            user_id="usso-user-1",
            workspace_id="workspace-1",
        )

    assert result == "answer"
    assert complete.await_args.kwargs["user_id"] == "usso-user-1"
    assert complete.await_args.kwargs["workspace_id"] == "workspace-1"
    assert complete.await_args.kwargs["audit_source"] == "extracted_content"


@pytest.mark.asyncio
async def test_webhook_prompt_uses_trusted_task_identity() -> None:
    from apps.ai.routes import _apply_user_prompt

    completion = AsyncMock(return_value="answer")
    with patch(
        "apps.bots.common.context.extracted_content_completion", completion
    ):
        result = await _apply_user_prompt(
            "extracted text",
            user_prompt="question",
            meta={
                "user_id": "usso-user-2",
                "workspace_id": "workspace-2",
                "platform_user_id": "telegram-user-2",
            },
            locale="fa",
            renderer=AsyncMock(),
            chat_id=123,
        )

    assert result == "answer"
    assert completion.await_args.kwargs["user_id"] == "usso-user-2"
    assert completion.await_args.kwargs["workspace_id"] == "workspace-2"
    assert completion.await_args.kwargs["audit_source"] == "task_webhook_prompt"


@pytest.mark.asyncio
async def test_file_caption_uses_handler_identity() -> None:
    from apps.bots.common.files import handle_file_event

    renderer = AsyncMock()
    renderer.download_attached_file.return_value = (b"document body", "notes.md")
    renderer.send_text.return_value = SimpleNamespace(id=22)
    ctx = BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(),
    )
    event = MessageEvent(
        platform="telegram",
        chat_id=10,
        message_id=20,
        sender=Sender(id="platform-user"),
        file=FileRef(file_id="file-1", file_name="notes.md"),
    )
    completion = AsyncMock(return_value="answer")
    delivery = AsyncMock(return_value=22)

    with (
        patch("apps.bots.common.context.store_message", AsyncMock()),
        patch("apps.bots.common.context.store_artifact_message", AsyncMock()),
        patch("apps.bots.common.context.extracted_content_completion", completion),
        patch("apps.bots.common.files.deliver_md_result", delivery),
    ):
        await handle_file_event(
            event=event,
            ctx=ctx,
            user_id="usso-user-3",
            workspace_id="workspace-3",
            locale="fa",
            response_message_id=21,
            user_prompt="summarize",
        )

    assert completion.await_args.kwargs["user_id"] == "usso-user-3"
    assert completion.await_args.kwargs["workspace_id"] == "workspace-3"
    assert completion.await_args.kwargs["audit_source"] == "file_caption"
    assert delivery.await_args.kwargs["result"] == "answer"


@pytest.mark.asyncio
async def test_long_file_caption_answer_is_delivered_as_result() -> None:
    from apps.bots.common.files import handle_file_event

    renderer = AsyncMock()
    renderer.download_attached_file.return_value = (b"document body", "notes.md")
    ctx = BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(),
    )
    event = MessageEvent(
        platform="telegram",
        chat_id=10,
        message_id=20,
        sender=Sender(id="platform-user"),
        file=FileRef(file_id="file-1", file_name="notes.md"),
    )
    long_answer = "x" * 5000
    delivery = AsyncMock(return_value=22)

    with (
        patch("apps.bots.common.context.store_message", AsyncMock()),
        patch("apps.bots.common.context.store_artifact_message", AsyncMock()),
        patch(
            "apps.bots.common.context.extracted_content_completion",
            AsyncMock(return_value=long_answer),
        ),
        patch("apps.bots.common.files.deliver_md_result", delivery),
    ):
        await handle_file_event(
            event=event,
            ctx=ctx,
            user_id="usso-user-3",
            workspace_id=None,
            locale="fa",
            response_message_id=21,
            user_prompt="give a detailed answer",
        )

    assert delivery.await_args.kwargs["result"] == long_answer
    assert delivery.await_args.kwargs["message_id"] == 20
    renderer.send_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_webpage_prompt_uses_handler_identity() -> None:
    from apps.bots.common.urls import _reply_webpage_completion

    renderer = AsyncMock()
    renderer.send_text.return_value = SimpleNamespace(id=32)
    ctx = BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(max_text_chars=4096),
    )
    event = MessageEvent(
        platform="telegram",
        chat_id=30,
        message_id=31,
        sender=Sender(id="platform-user"),
    )
    completion = AsyncMock(return_value="answer")

    with (
        patch("apps.bots.common.context.store_artifact_message", AsyncMock()),
        patch("apps.bots.common.context.extracted_content_completion", completion),
    ):
        await _reply_webpage_completion(
            event=event,
            ctx=ctx,
            combined="webpage body",
            user_text="summarize",
            user_id="usso-user-4",
            workspace_id="workspace-4",
            locale="fa",
            edit_message_id=None,
        )

    assert completion.await_args.kwargs["user_id"] == "usso-user-4"
    assert completion.await_args.kwargs["workspace_id"] == "workspace-4"
    assert completion.await_args.kwargs["audit_source"] == "webpage_prompt"


@pytest.mark.asyncio
async def test_inline_completion_uses_verified_user_and_active_workspace() -> None:
    from apps.bots.common.handlers.inline import handle_inline_query_event

    renderer = AsyncMock()
    ctx = BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(supports_inline_query=True),
    )
    event = InlineQueryEvent(
        platform="telegram",
        query_id="query-1",
        text="question",
        sender=Sender(id="untrusted-platform-id"),
        metadata={"user_id": "injected-user", "workspace_id": "injected-workspace"},
    )
    verified = VerifiedUser(
        usso_uid="verified-usso-user",
        bot_user=BotUser(
            user_id="verified-usso-user",
            telegram_user_id="untrusted-platform-id",
            platform_user_id="untrusted-platform-id",
            telegram_workspace_id="verified-workspace",
        ),
    )
    complete = AsyncMock(return_value="answer")

    with (
        patch(
            "apps.bots.common.handlers.inline.resolve_verified_user",
            AsyncMock(return_value=(VerifiedUserStatus.ok, verified)),
        ),
        patch(
            "apps.bots.common.handlers.inline.get_user_locale",
            AsyncMock(return_value="fa"),
        ),
        patch("apps.bots.common.handlers.inline.CompletionClient.complete", complete),
    ):
        await handle_inline_query_event(event, ctx)

    assert complete.await_args.kwargs["user_id"] == "verified-usso-user"
    assert complete.await_args.kwargs["workspace_id"] == "verified-workspace"
    assert complete.await_args.kwargs["audit_source"] == "telegram_inline"
    renderer.answer_inline_query.assert_awaited_once_with(
        "query-1", "answer", raw_event=event.raw
    )
