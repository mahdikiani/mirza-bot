from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from apps.bots.common.auth_gate import VerifiedUser, VerifiedUserStatus
from apps.bots.common.events import (
    CallbackEvent,
    FileRef,
    MessageEvent,
    PlatformCapabilities,
    Sender,
)
from apps.bots.common.handler import (
    BotRuntimeContext,
    handle_callback_event,
    handle_message_event,
)
from apps.bots.common.models import BotUser


@dataclass
class FakeRenderer:
    sent: list[tuple[int | str, str, int | str | None]] = field(default_factory=list)
    callbacks: list[tuple[int | str, str]] = field(default_factory=list)
    contact_requests: list[tuple[int | str, str]] = field(default_factory=list)
    typing: list[int | str] = field(default_factory=list)
    events: list[str] = field(default_factory=list)
    _next_id: int = 1000

    async def send_typing(self, chat_id: int | str) -> None:
        self.typing.append(chat_id)
        self.events.append("typing")

    async def send_text(
        self,
        chat_id: int | str,
        text_value: str,
        reply_to: int | str | None = None,
        reply_keyboard: object | None = None,
    ) -> object | None:
        self.sent.append((chat_id, text_value, reply_to))
        self.events.append("send_text")
        self._next_id += 1
        return SimpleNamespace(id=self._next_id)

    async def send_inline_text(
        self,
        chat_id: int | str,
        text_value: str,
        inline_keyboard: object,
        reply_to: int | str | None = None,
    ) -> object | None:
        self.sent.append((chat_id, text_value, reply_to))
        self.events.append("send_inline_text")
        self._next_id += 1
        return SimpleNamespace(id=self._next_id)

    async def edit_message(
        self,
        chat_id: int | str,
        message_id: int | str,
        text: str,
        inline_keyboard: object | None = None,
    ) -> None:
        self.events.append("edit_message")

    async def answer_callback(
        self,
        callback_id: int | str,
        text_value: str = "",
        raw_event: object | None = None,
    ) -> None:
        self.callbacks.append((callback_id, text_value))
        self.events.append("answer_callback")

    async def send_contact_request(self, chat_id: int | str, text_value: str) -> None:
        self.contact_requests.append((chat_id, text_value))
        self.events.append("contact_request")

    async def download_attached_file(
        self, event: MessageEvent
    ) -> tuple[bytes, str] | None:
        return b"file-bytes", "doc.pdf"


def _context(renderer: FakeRenderer) -> BotRuntimeContext:
    return BotRuntimeContext(
        bot_name="test_bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(max_text_chars=4096),
    )


def _verified_bot_user(**kwargs: object) -> BotUser:
    defaults: dict[str, object] = {
        "user_id": "usso-1",
        "telegram_user_id": "user-1",
        "usso_user_id": "usso-1",
        "phone_verified": True,
        "preferred_language": "fa",
    }
    defaults.update(kwargs)
    return BotUser(**defaults)


def _ok_verified(**kwargs: object) -> tuple[VerifiedUserStatus, VerifiedUser]:
    bot_user = _verified_bot_user(**kwargs)
    return VerifiedUserStatus.ok, VerifiedUser(
        usso_uid=str(bot_user.usso_user_id or "usso-1"),
        bot_user=bot_user,
    )


@pytest.mark.asyncio
async def test_handle_message_start_command() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="/start",
        sender=Sender(id=123),
    )

    with patch(
        "apps.bots.common.handler.resolve_verified_user",
        AsyncMock(return_value=_ok_verified(telegram_user_id="123")),
    ):
        await handle_message_event(event, _context(renderer))

    assert renderer.typing == [100]
    assert renderer.sent
    assert renderer.sent[0][0] == 100
    assert renderer.sent[0][2] == 10
    assert renderer.events[:2] == ["typing", "send_text"]


@pytest.mark.asyncio
async def test_handle_message_start_without_user_requests_contact() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="/start",
        sender=Sender(id=123),
    )

    with patch(
        "apps.bots.common.handler.resolve_verified_user",
        AsyncMock(return_value=(VerifiedUserStatus.needs_contact, None)),
    ):
        await handle_message_event(event, _context(renderer))

    assert renderer.typing == [100]
    assert renderer.sent == []
    assert renderer.contact_requests
    assert renderer.events[:2] == ["typing", "contact_request"]


@pytest.mark.asyncio
async def test_handle_message_empty_event_returns() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(chat_id=100, message_id=10)

    await handle_message_event(event, _context(renderer))

    assert renderer.sent == []
    assert renderer.typing == []


@pytest.mark.asyncio
async def test_handle_message_help_command_with_suffix() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(chat_id=100, message_id=10, text="/help please")

    await handle_message_event(event, _context(renderer))

    assert renderer.typing == [100]
    assert renderer.sent
    assert renderer.sent[0][2] == 10


@pytest.mark.asyncio
async def test_handle_message_no_user() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(chat_id=100, message_id=10, text="hello")

    await handle_message_event(event, _context(renderer))

    assert renderer.typing == [100]
    assert renderer.sent or renderer.contact_requests


@pytest.mark.asyncio
async def test_handle_message_sends_ai_response() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="hello",
        sender=Sender(id="user-1"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.handler.context.chat_completion",
            AsyncMock(return_value="ai response"),
        ) as chat_completion,
        patch(
            "apps.bots.common.handler.context.store_message",
            AsyncMock(),
        ),
    ):
        await handle_message_event(event, _context(renderer))

    chat_completion.assert_awaited_once()
    assert renderer.sent[-1][0] == 100
    assert renderer.sent[-1][1] == "ai response"
    assert renderer.sent[-1][2] == 10


@pytest.mark.asyncio
async def test_handle_message_uses_group_session_id_and_thread() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=200,
        chat_type="supergroup",
        message_id=10,
        text="@test_bot hello group",
        metadata={"telegram_user_id": "user-1"},
    )
    ctx = BotRuntimeContext(
        bot_name="test_bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(max_text_chars=4096),
        bot_username="test_bot",
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.handler.context.chat_completion",
            AsyncMock(return_value="ai response"),
        ) as chat_completion,
        patch(
            "apps.bots.common.handler.context.store_message",
            AsyncMock(),
        ),
    ):
        await handle_message_event(event, ctx)

    chat_completion.assert_awaited_once_with(
        event, "hello group", locale="fa", renderer=renderer
    )
    assert renderer.sent[-1][1] == "ai response"


@pytest.mark.asyncio
async def test_handle_message_file_without_text_acknowledges_processing() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        sender=Sender(id="user-1"),
        file=FileRef(file_id="file-1", file_name="doc.pdf"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.files.media_flow.submit_file_bytes",
            AsyncMock(return_value="task-1"),
        ) as submit_mock,
    ):
        await handle_message_event(event, _context(renderer))

    submit_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_message_file_with_caption_uses_ocr() -> None:
    """A document caption must not route the attachment to chat completion."""
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        sender=Sender(id="user-1"),
        caption="این PDF را بررسی کن",
        content_type="document",
        file=FileRef(file_id="file-1", file_name="doc.pdf"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.files.media_flow.submit_file_bytes",
            AsyncMock(return_value="task-1"),
        ) as submit_mock,
        patch(
            "apps.bots.common.handler.context.chat_completion",
            AsyncMock(),
        ) as chat_completion,
    ):
        await handle_message_event(event, _context(renderer))

    submit_mock.assert_awaited_once()
    chat_completion.assert_not_awaited()


@pytest.mark.asyncio
async def test_async_url_uses_processing_message_for_webhook_delivery() -> None:
    renderer = FakeRenderer()
    renderer.send_text = AsyncMock(return_value=SimpleNamespace(id=77))
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        sender=Sender(id="user-1"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.urls.media_flow.submit_url",
            AsyncMock(return_value="task-1"),
        ) as submit_mock,
    ):
        await handle_message_event(event, _context(renderer))

    assert renderer.typing == [100]
    assert renderer.send_text.await_args.args[1] == "در حال پردازش..."
    assert submit_mock.await_args.kwargs["response_message_id"] == 77


@pytest.mark.asyncio
async def test_handle_message_missing_session_id_returns_error() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="hello",
        sender=Sender(id="user-1"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.handler.context.chat_completion",
            AsyncMock(return_value=""),
        ),
        patch(
            "apps.bots.common.handler.context.store_message",
            AsyncMock(),
        ),
    ):
        await handle_message_event(event, _context(renderer))

    assert renderer.sent


@pytest.mark.asyncio
async def test_handle_message_ai_exception_returns_error() -> None:
    renderer = FakeRenderer()
    event = MessageEvent(
        chat_id=100,
        message_id=10,
        text="hello",
        sender=Sender(id="user-1"),
    )

    with (
        patch(
            "apps.bots.common.handler.require_verified_user",
            AsyncMock(return_value=("usso-1", _verified_bot_user())),
        ),
        patch(
            "apps.bots.common.handler.context.chat_completion",
            AsyncMock(return_value="خطای هوش مصنوعی"),
        ),
        patch(
            "apps.bots.common.handler.context.store_message",
            AsyncMock(),
        ),
    ):
        await handle_message_event(event, _context(renderer))

    assert renderer.sent
    assert renderer.sent[-1][1] == "خطای هوش مصنوعی"


@pytest.mark.asyncio
async def test_handle_callback_answers_raw_event() -> None:
    renderer = FakeRenderer()
    event = CallbackEvent(callback_id="cb-1", chat_id=0)

    await handle_callback_event(event, _context(renderer))

    assert renderer.typing == [0]
    assert renderer.callbacks == [("cb-1", "در حال پردازش...")]


@pytest.mark.asyncio
async def test_handle_callback_falls_back_to_renderer() -> None:
    renderer = FakeRenderer()
    event = CallbackEvent(callback_id="cb-1")

    await handle_callback_event(event, _context(renderer))

    assert renderer.typing == [0]
    assert renderer.callbacks
