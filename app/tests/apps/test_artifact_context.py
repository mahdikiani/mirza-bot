"""Workspace-scoped artifact persistence and reply-chain reconstruction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from apps.bots.common import context
from apps.bots.common.delivery import _markdown_file_name
from apps.bots.common.events import MessageEvent, MessageRef
from apps.bots.common.models import Artifact


@pytest.mark.parametrize(
    ("input_name", "expected"),
    [
        ("notes.md", "notes.md"),
        ("NOTES.MD", "NOTES.MD"),
        ("notes.txt", "notes.md"),
        ("notes", "notes.md"),
        ("lesson.pdf", "lesson.md"),
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
