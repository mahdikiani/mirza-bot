"""MongoDB ODM models for bot users, messages, and artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi_mongo_base.models import UserOwnedEntity
from pydantic import Field


class BotUser(UserOwnedEntity):
    """Local bot user profile linked to USSO."""

    telegram_user_id: str = ""
    platform_user_id: str = ""
    usso_user_id: str = ""
    usso_synced: bool = True
    telegram_workspace_id: str | None = None
    # Shared (team/B2B) workspaces this user created or joined via the bot,
    # workspace_id -> display name. Lets the switch-workspace menu show
    # names without an extra USSO round trip; the personal workspace isn't
    # listed here since it's always shown as the "شخصی" default option.
    known_workspaces: dict[str, str] = Field(default_factory=dict)
    # Workspaces this user created via the bot (and so is CEO of) -- gates
    # invite/member-management actions to whoever set up the team, rather
    # than every member who was later added to it.
    owned_workspace_ids: list[str] = Field(default_factory=list)
    preferred_language: str = "fa"
    preferred_model: str = "openai/gpt-5.6-terra"
    phone_verified: bool = False
    phone_number: str | None = None
    platform: str = "telegram"


class WorkspaceInvite(UserOwnedEntity):
    """
    A bearer invite link into a team workspace.

    Created when a CEO/owner taps "invite member"; redeemed by whoever
    starts the bot with this token as the /start deep-link payload. The
    token itself is the capability -- no invited_id is known up front,
    unlike USSO's own WorkspaceInvitation model (which requires the
    invitee to already be a known USSO user).
    """

    token: str = ""
    workspace_id: str = ""
    workspace_name: str = ""
    role: str = "member"
    invited_by_usso_uid: str = ""
    expires_at: datetime | None = None
    used_at: datetime | None = None


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
    workspace_id: str | None = None
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
    workspace_id: str | None = None
    media_url: str | None = None
    content: str = ""
    original_name: str | None = None
    base_name: str | None = None
    mime_type: str | None = None
    meta_data: dict | None = None
