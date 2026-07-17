"""MongoDB ODM models for bot users, messages, and artifacts."""

from __future__ import annotations

from typing import Literal

from fastapi_mongo_base.models import UserOwnedEntity


class BotUser(UserOwnedEntity):
    """Local bot user profile linked to USSO."""

    telegram_user_id: str = ""
    usso_user_id: str = ""
    usso_synced: bool = True
    preferred_language: str = "fa"
    preferred_model: str = "openai/gpt-5.6-terra"
    phone_verified: bool = False
    phone_number: str | None = None
    platform: str = "telegram"


class Message(UserOwnedEntity):
    """Stored message for reply-chain reconstruction."""

    platform: str = "telegram"
    platform_chat_id: str = ""
    platform_message_id: str = ""
    reply_to_platform_message_id: str | None = None
    role: Literal["user", "assistant", "system"] = "user"
    content: str = ""
    content_type: str = "text"
    artifact_id: str | None = None
    source_chat_id: str | None = None
    meta_data: dict | None = None

    @property
    def text(self) -> str:
        """Alias for content used by reply-chain logic."""
        return self.content

    @text.setter
    def text(self, value: str) -> None:
        self.content = value


class Artifact(UserOwnedEntity):
    """Reference to a stored artifact (media file, AI toolkit result, etc.)."""

    source_type: str = ""
    media_url: str | None = None
    content: str = ""
    meta_data: dict | None = None
