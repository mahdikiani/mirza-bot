"""Shared (team/B2B) workspace creation and bearer-token invite flow."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta

from apps.accounts.clients import usso_accounts_client
from apps.bots.common import models
from server.db import get_redis

logger = logging.getLogger(__name__)

INVITE_TTL_DAYS = 3
# Window to complete phone verification after tapping an invite link before
# it needs to be re-shared; not the invite's own lifetime (see INVITE_TTL_DAYS).
_PENDING_TTL_SECONDS = 900
_PENDING_KEY_PREFIX = "team_invite_pending:"


def _pending_key(platform: str, messenger_id: str) -> str:
    return f"{_PENDING_KEY_PREFIX}{platform}:{messenger_id}"


async def stash_pending_invite(platform: str, messenger_id: str, token: str) -> None:
    """Remember an invite token across onboarding (phone verification)."""
    redis = get_redis()
    if redis is None:
        logger.warning(
            "Redis unavailable; invite token will be lost if %s needs onboarding",
            messenger_id,
        )
        return
    await redis.set(
        _pending_key(platform, messenger_id), token, ex=_PENDING_TTL_SECONDS
    )


async def pop_pending_invite(platform: str, messenger_id: str) -> str | None:
    """Retrieve and clear a stashed invite token, if any."""
    redis = get_redis()
    if redis is None:
        return None
    key = _pending_key(platform, messenger_id)
    token = await redis.get(key)
    if token:
        await redis.delete(key)
    return token


def parse_start_payload(text_value: str) -> str | None:
    """Extract an invite token from a "/start join_<token>" command."""
    parts = text_value.strip().split(maxsplit=1)
    if len(parts) != 2:
        return None
    payload = parts[1].strip()
    if not payload.startswith("join_"):
        return None
    return payload.removeprefix("join_") or None


async def create_team_workspace(*, name: str, owner_usso_uid: str) -> dict:
    """Create a shared workspace (admin-scoped, no KYC) and add the creator as CEO."""
    async with usso_accounts_client() as client:
        workspace = await client.create_team_workspace(name)
        workspace_id = workspace["uid"]
        await client.add_workspace_member(workspace_id, owner_usso_uid, role="CEO")
    return workspace


async def create_invite(
    *,
    workspace_id: str,
    workspace_name: str,
    role: str,
    invited_by_usso_uid: str,
) -> str:
    """Create a single-use bearer invite token for a workspace."""
    token = secrets.token_urlsafe(16)
    invite = models.WorkspaceInvite(
        user_id=invited_by_usso_uid,
        token=token,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        role=role,
        invited_by_usso_uid=invited_by_usso_uid,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
    )
    await invite.save()
    return token


async def accept_invite(
    *,
    token: str,
    invitee_usso_uid: str,
    bot_user: models.BotUser,
) -> tuple[bool, str, str | None]:
    """
    Redeem an invite token: add the invitee to the workspace, switch them into it.

    Returns (success, workspace_name_on_success_or_error_key, workspace_id).
    """
    invite = await models.WorkspaceInvite.find_one({"token": token})
    if invite is None:
        return False, "invite_not_found", None
    if invite.used_at is not None:
        return False, "invite_already_used", None

    expires_at = invite.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            return False, "invite_expired", None

    try:
        async with usso_accounts_client() as client:
            await client.add_workspace_member(
                invite.workspace_id, invitee_usso_uid, role=invite.role
            )
    except Exception:
        logger.exception(
            "Failed to add %s to workspace %s via invite",
            invitee_usso_uid,
            invite.workspace_id,
        )
        return False, "invite_join_failed", None

    invite.used_at = datetime.now(UTC)
    await invite.save()

    bot_user.known_workspaces = {
        **(bot_user.known_workspaces or {}),
        invite.workspace_id: invite.workspace_name,
    }
    bot_user.telegram_workspace_id = invite.workspace_id
    await bot_user.save()

    return True, invite.workspace_name, invite.workspace_id
