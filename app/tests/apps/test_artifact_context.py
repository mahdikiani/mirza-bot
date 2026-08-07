"""Workspace-scoped artifact persistence and reply-chain reconstruction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.bots.common import context
from apps.bots.common.delivery import _markdown_file_name
from apps.bots.common.events import CallbackEvent, MessageEvent, MessageRef, Sender
from apps.bots.common.handler_context import BotRuntimeContext, PlatformCapabilities
from apps.bots.common.models import Artifact


@pytest.mark.parametrize(
    ("input_name", "expected"),
    [
        ("notes.md", "notes.md"),
        ("NOTES.MD", "NOTES.MD"),
        ("notes.txt", "notes.md"),
        ("notes", "notes.md"),
        ("lesson.pdf", "lesson.md"),
        ("عنوان فارسی / بخش اول", "عنوان فارسی - بخش اول.md"),
    ],
)
def test_markdown_filename_has_exactly_one_extension(
    input_name: str, expected: str
) -> None:
    assert _markdown_file_name(input_name) == expected


@pytest.mark.asyncio
async def test_delivered_artifact_is_loaded_into_reply_context() -> None:
    message, artifact = await context.store_artifact_message(
        platform="telegram",
        platform_chat_id="artifact-chat-1",
        platform_message_id="artifact-message-1",
        reply_to_platform_message_id="source-message-1",
        user_id="artifact-user-1",
        workspace_id="artifact-workspace-1",
        source_type="document",
        artifact_content="# Document\n\nFull artifact content",
        original_name="درس-اول.pdf",
        base_name="درس-اول",
    )

    event = MessageEvent(
        platform="telegram",
        chat_id="artifact-chat-1",
        message_id="question-message-1",
        reply_to=MessageRef(message_id="artifact-message-1"),
    )
    messages = await context.build_reply_chain_messages(
        event,
        "Question about the document",
        user_id="artifact-user-1",
        workspace_id="artifact-workspace-1",
    )

    assert artifact.workspace_id == "artifact-workspace-1"
    assert message.artifact_id == str(artifact.id)
    assert messages == [
        {"role": "assistant", "content": "# Document\n\nFull artifact content"},
        {"role": "user", "content": "Question about the document"},
    ]


@pytest.mark.asyncio
async def test_reply_context_cannot_read_another_workspace_artifact() -> None:
    await context.store_artifact_message(
        platform="telegram",
        platform_chat_id="shared-group-chat",
        platform_message_id="private-artifact-message",
        reply_to_platform_message_id=None,
        user_id="workspace-owner",
        workspace_id="private-workspace",
        source_type="document",
        artifact_content="محتوای خصوصی",
    )
    event = MessageEvent(
        platform="telegram",
        chat_id="shared-group-chat",
        message_id="foreign-question",
        reply_to=MessageRef(message_id="private-artifact-message"),
    )

    renderer = AsyncMock()
    messages = await context.build_reply_chain_messages(
        event,
        "این فایل چیست؟",
        renderer=renderer,
        user_id="other-user",
        workspace_id="other-workspace",
    )

    assert messages == [{"role": "user", "content": "این فایل چیست؟"}]
    renderer.download_document.assert_not_awaited()


@pytest.mark.asyncio
async def test_personal_artifact_uses_personal_workspace() -> None:
    message, artifact = await context.store_artifact_message(
        platform="bale",
        platform_chat_id="personal-chat",
        platform_message_id="personal-result",
        reply_to_platform_message_id=None,
        user_id="personal-user",
        workspace_id=None,
        source_type="url",
        artifact_content="صفحه وب",
    )

    assert artifact.workspace_id == "personal-user"
    assert message.workspace_id == "personal-user"


@pytest.mark.asyncio
async def test_webhook_delivery_persists_workspace_artifact() -> None:
    from apps.ai.routes import _store_completed_delivery

    await _store_completed_delivery(
        meta={
            "platform": "telegram",
            "workspace_id": "delivery-workspace",
            "reply_to_message_id": "delivery-source",
            "file_name_hint": "lesson.pdf",
        },
        chat_id="delivery-chat",
        delivered_message_id="delivery-result",
        result="Extracted document body",
        user_id="delivery-user",
        content_type="document",
    )

    stored = await context.get_message_by_platform_id(
        "telegram",
        "delivery-chat",
        "delivery-result",
        user_id="delivery-user",
        workspace_id="delivery-workspace",
    )
    assert stored is not None
    assert stored.reply_to_platform_message_id == "delivery-source"
    artifact = await Artifact.get(stored.artifact_id)
    assert artifact is not None
    assert artifact.content == "Extracted document body"
    assert artifact.original_name == "lesson.pdf"
    assert artifact.base_name == "lesson"


@pytest.mark.asyncio
async def test_action_inherits_artifact_base_name() -> None:
    from types import SimpleNamespace
    from unittest.mock import patch

    from apps.bots.common.auth_gate import VerifiedUser
    from apps.bots.common.callbacks.chat import handle_action_callback
    from apps.bots.common.models import BotUser

    renderer = AsyncMock()
    renderer.send_text.return_value = SimpleNamespace(id=55)
    ctx = BotRuntimeContext(
        bot_name="test-bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(),
    )
    event = CallbackEvent(
        platform="telegram",
        callback_id="callback-1",
        chat_id=1,
        message_id=2,
        data="action:summarize",
        sender=Sender(id=3),
    )
    verified = VerifiedUser(
        usso_uid="user-1",
        bot_user=BotUser(
            user_id="user-1",
            telegram_workspace_id="workspace-1",
        ),
    )
    action = AsyncMock(return_value={"uid": "task-1"})

    with (
        patch(
            "apps.bots.common.callbacks.chat.require_verified_callback",
            AsyncMock(return_value=(verified.usso_uid, verified.bot_user)),
        ),
        patch(
            "apps.bots.common.callbacks.chat.get_content",
            AsyncMock(return_value="transcript"),
        ),
        patch(
            "apps.bots.common.context.get_artifact_by_platform_message",
            AsyncMock(return_value=SimpleNamespace(base_name="Meaningful title")),
        ),
        patch(
            "apps.bots.common.actions.run_promptic_action",
            action,
        ),
    ):
        handled = await handle_action_callback(
            "action:summarize", event, ctx, "fa", "user-1"
        )

    assert handled
    meta = action.await_args.kwargs["meta_data"]
    assert meta["file_name_hint"] == "Meaningful title"


@pytest.mark.asyncio
async def test_youtube_title_becomes_delivery_file_name() -> None:
    from unittest.mock import patch

    from apps.ai.routes import _deliver_result
    from apps.ai.schemas import TaskWebhookPayload

    renderer = AsyncMock()
    deliver = AsyncMock(return_value=77)
    payload = TaskWebhookPayload(
        uid="youtube-task-1",
        task_status="completed",
        result="transcript",
        provider_meta={"title": "Meaningful video title", "video_id": "abc123"},
    )
    pending = {
        "meta_data": {
            "platform": "telegram",
            "chat_id": 1,
            "message_id": 2,
            "reply_to_message_id": 3,
            "bot_name": "test-bot",
            "user_id": "user-1",
            "workspace_id": "user-1",
            "locale": "fa",
        }
    }

    with (
        patch("apps.ai.pending_tasks.get", AsyncMock(return_value=pending)),
        patch("apps.ai.pending_tasks.remove", AsyncMock()),
        patch("apps.ai.routes.get_renderer", return_value=renderer),
        patch("apps.ai.routes.deliver_md_result", deliver),
        patch("apps.ai.routes._store_completed_delivery", AsyncMock()),
    ):
        await _deliver_result(payload, "youtube")

    assert deliver.await_args.kwargs["file_name_hint"] == "Meaningful video title"
