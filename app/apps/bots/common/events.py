"""
Normalized, platform-independent event types.

All platform adapters (Telegram, Bale, etc.) normalize their native
events into these types before dispatching to business logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Metadata = dict[str, object]


@dataclass
class FileRef:
    """Reference to a file attached to a message."""

    file_id: str
    file_name: str
    mime_type: str = ""
    size: int = 0
    metadata: Metadata = field(default_factory=dict)


@dataclass
class MessageRef:
    """Reference to a previous message (for reply chains)."""

    message_id: int | str
    chat_id: int | str | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass
class Sender:
    """Who sent the message."""

    id: int | str
    is_bot: bool = False
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    metadata: Metadata = field(default_factory=dict)


@dataclass(frozen=True)
class PlatformCapabilities:
    """Optional platform features exposed by an adapter/renderer."""

    supports_typing: bool = False
    supports_streaming: bool = False
    supports_inline_query: bool = False
    supports_callback_buttons: bool = False
    max_upload_bytes: int | None = None
    max_text_chars: int | None = None


ContentType = Literal[
    "text",
    "voice",
    "audio",
    "video",
    "photo",
    "document",
    "url",
    "sticker",
    "animation",
]


@dataclass
class MessageEvent:
    """Normalized inbound message from any platform."""

    platform: str = "telegram"
    chat_id: int | str = 0
    chat_type: Literal["private", "group", "supergroup"] = "private"
    message_id: int | str = 0
    text: str | None = None
    caption: str | None = None
    content_type: ContentType = "text"
    sender: Sender | None = None
    file: FileRef | None = None
    reply_to: MessageRef | None = None
    metadata: Metadata = field(default_factory=dict)
    raw: object | None = None


@dataclass
class CallbackEvent:
    """Normalized callback/inline-action from any platform."""

    platform: str = "telegram"
    callback_id: str = ""
    chat_id: int | str = 0
    message_id: int | str = 0
    action: str = ""
    data: str = ""
    message_text: str | None = None
    sender: Sender | None = None
    metadata: Metadata = field(default_factory=dict)
    raw: object | None = None


@dataclass
class InlineQueryEvent:
    """Normalized inline query from any platform."""

    platform: str = "telegram"
    query_id: str = ""
    text: str = ""
    sender: Sender | None = None
    metadata: Metadata = field(default_factory=dict)
    raw: object | None = None
