"""Tests for shared (team/B2B) workspace creation, invites, and switching."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.common import team_invites
from apps.bots.common.auth_gate import VerifiedUser, VerifiedUserStatus
from apps.bots.common.callbacks.team import handle_team_callback
from apps.bots.common.events import (
    CallbackEvent,
    MessageEvent,
    PlatformCapabilities,
    Sender,
)
from apps.bots.common.handler import handle_contact_event, handle_message_event
from apps.bots.common.handler_context import BotRuntimeContext
from apps.bots.common.models import BotUser, WorkspaceInvite


class FakeRenderer:
    def __init__(self) -> None:
        self.sent: list[tuple] = []
        self.edited: list[tuple] = []

    async def send_typing(self, chat_id: int | str) -> None:
        pass

    async def send_text(self, chat_id, text_value, reply_to=None, reply_keyboard=None):
        self.sent.append((chat_id, text_value))
        return MagicMock(id=99)

    async def send_contact_request(self, chat_id, text_value) -> None:
        self.sent.append((chat_id, text_value))

    async def send_inline_text(
        self, chat_id, text_value, inline_keyboard, reply_to=None
    ):
        self.sent.append((chat_id, text_value))
        return MagicMock(id=99)

    async def edit_message(self, chat_id, message_id, text_value, inline_keyboard=None):
        self.edited.append((chat_id, text_value))

    async def answer_callback(self, callback_id, text_value="", raw_event=None) -> None:
        pass


def _ctx(renderer: FakeRenderer) -> BotRuntimeContext:
    return BotRuntimeContext(
        bot_name="bot",
        platform="telegram",
        renderer=renderer,
        capabilities=PlatformCapabilities(),
        bot_username="mirzbenevisabot",
    )


def _callback(data: str) -> CallbackEvent:
    return CallbackEvent(
        platform="telegram",
        callback_id="cb1",
        chat_id=1,
        message_id=5,
        data=data,
        sender=Sender(id="tg1", first_name="Ali"),
    )


async def _bot_user(**kwargs: object) -> BotUser:
    defaults: dict[str, object] = {
        "user_id": "usso-1",
        "telegram_user_id": "tg1",
        "usso_user_id": "usso-1",
        "usso_synced": True,
        "phone_verified": True,
    }
    defaults.update(kwargs)
    user = BotUser(**defaults)
    await user.save()
    return user


# --- team_invites -----------------------------------------------------


def test_parse_start_payload_extracts_join_token() -> None:
    assert team_invites.parse_start_payload("/start join_abc123") == "abc123"


def test_parse_start_payload_rejects_non_join_payload() -> None:
    assert team_invites.parse_start_payload("/start something_else") is None


def test_parse_start_payload_rejects_bare_start() -> None:
    assert team_invites.parse_start_payload("/start") is None


@pytest.mark.asyncio
async def test_pending_invite_roundtrip_with_redis() -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            store[key] = value

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    with patch("apps.bots.common.team_invites.get_redis", return_value=FakeRedis()):
        await team_invites.stash_pending_invite("telegram", "tg1", "tok-1")
        token = await team_invites.pop_pending_invite("telegram", "tg1")
        assert token == "tok-1"
        # Popped once; a second pop finds nothing.
        assert await team_invites.pop_pending_invite("telegram", "tg1") is None


@pytest.mark.asyncio
async def test_pending_invite_noop_without_redis() -> None:
    with patch("apps.bots.common.team_invites.get_redis", return_value=None):
        await team_invites.stash_pending_invite("telegram", "tg1", "tok-1")
        assert await team_invites.pop_pending_invite("telegram", "tg1") is None


@pytest.mark.asyncio
async def test_create_team_workspace_adds_creator_as_ceo() -> None:
    client = AsyncMock()
    client.create_team_workspace = AsyncMock(return_value={"uid": "ws-1"})
    client.add_workspace_member = AsyncMock()
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with patch(
        "apps.bots.common.team_invites.usso_accounts_client",
        return_value=client_cm,
    ):
        workspace = await team_invites.create_team_workspace(
            name="Team X", owner_usso_uid="usso-1"
        )

    assert workspace == {"uid": "ws-1"}
    client.create_team_workspace.assert_awaited_once_with("Team X")
    client.add_workspace_member.assert_awaited_once_with(
        "ws-1", "usso-1", role="CEO"
    )


@pytest.mark.asyncio
async def test_accept_invite_not_found() -> None:
    bot_user = await _bot_user()
    success, key, workspace_id = await team_invites.accept_invite(
        token="missing", invitee_usso_uid="usso-2", bot_user=bot_user
    )
    assert not success
    assert key == "invite_not_found"
    assert workspace_id is None


@pytest.mark.asyncio
async def test_accept_invite_already_used() -> None:
    from datetime import UTC, datetime

    invite = WorkspaceInvite(
        user_id="usso-1",
        token="used-token",
        workspace_id="ws-1",
        workspace_name="Team X",
        role="member",
        invited_by_usso_uid="usso-1",
        used_at=datetime.now(UTC),
    )
    await invite.save()
    bot_user = await _bot_user(usso_user_id="usso-2")
    success, key, _ = await team_invites.accept_invite(
        token="used-token", invitee_usso_uid="usso-2", bot_user=bot_user
    )
    assert not success
    assert key == "invite_already_used"


@pytest.mark.asyncio
async def test_accept_invite_expired() -> None:
    from datetime import UTC, datetime, timedelta

    invite = WorkspaceInvite(
        user_id="usso-1",
        token="old-token",
        workspace_id="ws-1",
        workspace_name="Team X",
        role="member",
        invited_by_usso_uid="usso-1",
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    await invite.save()
    bot_user = await _bot_user(usso_user_id="usso-3")
    success, key, _ = await team_invites.accept_invite(
        token="old-token", invitee_usso_uid="usso-3", bot_user=bot_user
    )
    assert not success
    assert key == "invite_expired"


@pytest.mark.asyncio
async def test_accept_invite_success_switches_and_marks_used() -> None:
    from datetime import UTC, datetime, timedelta

    invite = WorkspaceInvite(
        user_id="usso-1",
        token="fresh-token",
        workspace_id="ws-1",
        workspace_name="Team X",
        role="member",
        invited_by_usso_uid="usso-1",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await invite.save()
    bot_user = await _bot_user(usso_user_id="usso-4")

    client = AsyncMock()
    client.add_workspace_member = AsyncMock()
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with patch(
        "apps.bots.common.team_invites.usso_accounts_client",
        return_value=client_cm,
    ):
        success, name, workspace_id = await team_invites.accept_invite(
            token="fresh-token", invitee_usso_uid="usso-4", bot_user=bot_user
        )

    assert success
    assert name == "Team X"
    assert workspace_id == "ws-1"
    assert bot_user.telegram_workspace_id == "ws-1"
    assert bot_user.known_workspaces["ws-1"] == "Team X"
    client.add_workspace_member.assert_awaited_once_with("ws-1", "usso-4", role="member")

    refreshed = await WorkspaceInvite.find_one({"token": "fresh-token"})
    assert refreshed.used_at is not None


@pytest.mark.asyncio
async def test_accept_invite_join_failure_reported() -> None:
    from datetime import UTC, datetime, timedelta

    invite = WorkspaceInvite(
        user_id="usso-1",
        token="fail-token",
        workspace_id="ws-1",
        workspace_name="Team X",
        role="member",
        invited_by_usso_uid="usso-1",
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    await invite.save()
    bot_user = await _bot_user(usso_user_id="usso-5")

    client_cm = AsyncMock()
    client_cm.__aenter__.side_effect = RuntimeError("usso down")

    with patch(
        "apps.bots.common.team_invites.usso_accounts_client",
        return_value=client_cm,
    ):
        success, key, _ = await team_invites.accept_invite(
            token="fail-token", invitee_usso_uid="usso-5", bot_user=bot_user
        )
    assert not success
    assert key == "invite_join_failed"


# --- callbacks/team -----------------------------------------------------


@pytest.mark.asyncio
async def test_team_menu_shows_personal_by_default() -> None:
    bot_user = await _bot_user(usso_user_id="usso-6")
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-6", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:menu", _callback("team:menu"), _ctx(renderer), "fa"
        )
    assert handled
    assert renderer.edited


@pytest.mark.asyncio
async def test_team_create_sets_owner_and_active_workspace() -> None:
    bot_user = await _bot_user(usso_user_id="usso-7")
    renderer = FakeRenderer()
    client = AsyncMock()
    client.create_team_workspace = AsyncMock(return_value={"uid": "ws-new"})
    client.add_workspace_member = AsyncMock()
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with (
        patch(
            "apps.bots.common.callbacks.team.require_verified_callback",
            AsyncMock(return_value=("usso-7", bot_user)),
        ),
        patch(
            "apps.bots.common.team_invites.usso_accounts_client",
            return_value=client_cm,
        ),
    ):
        handled = await handle_team_callback(
            "team:create", _callback("team:create"), _ctx(renderer), "fa"
        )
    assert handled
    assert bot_user.telegram_workspace_id == "ws-new"
    assert "ws-new" in bot_user.owned_workspace_ids
    assert bot_user.known_workspaces["ws-new"]


@pytest.mark.asyncio
async def test_team_invite_denied_when_not_owner() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-8", telegram_workspace_id="ws-not-mine"
    )
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-8", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:invite", _callback("team:invite"), _ctx(renderer), "fa"
        )
    assert handled
    assert renderer.sent
    assert bot_user.telegram_workspace_id == "ws-not-mine"


@pytest.mark.asyncio
async def test_team_invite_generates_link_for_owner() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-9",
        telegram_workspace_id="ws-mine",
        owned_workspace_ids=["ws-mine"],
        known_workspaces={"ws-mine": "Team Mine"},
    )
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-9", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:invite", _callback("team:invite"), _ctx(renderer), "fa"
        )
    assert handled
    assert any("join_" in msg for _chat, msg in renderer.sent)


@pytest.mark.asyncio
async def test_team_members_none_for_personal_workspace() -> None:
    bot_user = await _bot_user(usso_user_id="usso-10")
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-10", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:members", _callback("team:members"), _ctx(renderer), "fa"
        )
    assert handled
    assert renderer.sent


@pytest.mark.asyncio
async def test_team_members_lists_for_team_workspace() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-11", telegram_workspace_id="ws-mine"
    )
    renderer = FakeRenderer()
    client = AsyncMock()
    client.list_workspace_members = AsyncMock(
        return_value=[{"uid": "u1", "name": "Ali", "roles": ["CEO"]}]
    )
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with (
        patch(
            "apps.bots.common.callbacks.team.require_verified_callback",
            AsyncMock(return_value=("usso-11", bot_user)),
        ),
        patch(
            "apps.bots.common.callbacks.team.usso_accounts_client",
            return_value=client_cm,
        ),
    ):
        handled = await handle_team_callback(
            "team:members", _callback("team:members"), _ctx(renderer), "fa"
        )
    assert handled
    assert any("Ali" in msg for _chat, msg in renderer.sent)


@pytest.mark.asyncio
async def test_team_switch_menu_shows_keyboard() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-12", known_workspaces={"ws-1": "Team A"}
    )
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-12", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:switch:menu", _callback("team:switch:menu"), _ctx(renderer), "fa"
        )
    assert handled
    assert renderer.edited


@pytest.mark.asyncio
async def test_team_switch_to_personal() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-13", telegram_workspace_id="ws-mine"
    )
    renderer = FakeRenderer()
    with patch(
        "apps.bots.common.callbacks.team.require_verified_callback",
        AsyncMock(return_value=("usso-13", bot_user)),
    ):
        handled = await handle_team_callback(
            "team:switch:personal",
            _callback("team:switch:personal"),
            _ctx(renderer),
            "fa",
        )
    assert handled
    assert bot_user.telegram_workspace_id == "usso-13"


@pytest.mark.asyncio
async def test_team_switch_to_team_rejects_non_member() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-14", known_workspaces={"ws-1": "Team A"}
    )
    renderer = FakeRenderer()
    fresh_user = SimpleNamespace(workspace_ids=["usso-14"])
    client = AsyncMock()
    client.get_user_by_identifier = AsyncMock(return_value=fresh_user)
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with (
        patch(
            "apps.bots.common.callbacks.team.require_verified_callback",
            AsyncMock(return_value=("usso-14", bot_user)),
        ),
        patch(
            "apps.bots.common.callbacks.team.usso_accounts_client",
            return_value=client_cm,
        ),
    ):
        handled = await handle_team_callback(
            "team:switch:ws-1", _callback("team:switch:ws-1"), _ctx(renderer), "fa"
        )
    assert handled
    assert bot_user.telegram_workspace_id != "ws-1"


@pytest.mark.asyncio
async def test_team_switch_to_team_succeeds_for_member() -> None:
    bot_user = await _bot_user(
        usso_user_id="usso-15", known_workspaces={"ws-1": "Team A"}
    )
    renderer = FakeRenderer()
    fresh_user = SimpleNamespace(workspace_ids=["usso-15", "ws-1"])
    client = AsyncMock()
    client.get_user_by_identifier = AsyncMock(return_value=fresh_user)
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with (
        patch(
            "apps.bots.common.callbacks.team.require_verified_callback",
            AsyncMock(return_value=("usso-15", bot_user)),
        ),
        patch(
            "apps.bots.common.callbacks.team.usso_accounts_client",
            return_value=client_cm,
        ),
    ):
        handled = await handle_team_callback(
            "team:switch:ws-1", _callback("team:switch:ws-1"), _ctx(renderer), "fa"
        )
    assert handled
    assert bot_user.telegram_workspace_id == "ws-1"


@pytest.mark.asyncio
async def test_team_callback_ignores_unrelated_data() -> None:
    renderer = FakeRenderer()
    handled = await handle_team_callback(
        "settings:lang:fa", _callback("settings:lang:fa"), _ctx(renderer), "fa"
    )
    assert not handled


# --- /start join_<token> deep link -------------------------------------


def _message_event(text_value: str) -> MessageEvent:
    return MessageEvent(
        platform="telegram",
        chat_id=1,
        message_id=1,
        text=text_value,
        sender=Sender(id="tg1", first_name="Ali"),
    )


@pytest.mark.asyncio
async def test_start_with_invite_token_accepts_for_verified_user() -> None:
    bot_user = await _bot_user(usso_user_id="usso-20")
    renderer = FakeRenderer()
    verified = VerifiedUser(usso_uid="usso-20", bot_user=bot_user)

    with (
        patch(
            "apps.bots.common.handlers.messages.resolve_verified_user",
            AsyncMock(return_value=(VerifiedUserStatus.ok, verified)),
        ),
        patch(
            "apps.bots.common.handlers.messages.team_invites.accept_invite",
            AsyncMock(return_value=(True, "Team X", "ws-1")),
        ) as mock_accept,
    ):
        await handle_message_event(_message_event("/start join_tok1"), _ctx(renderer))

    mock_accept.assert_awaited_once_with(
        token="tok1", invitee_usso_uid="usso-20", bot_user=bot_user
    )
    assert any("Team X" in msg for _chat, msg in renderer.sent)


@pytest.mark.asyncio
async def test_start_with_invite_token_stashes_for_unverified_user() -> None:
    renderer = FakeRenderer()

    with (
        patch(
            "apps.bots.common.handlers.messages.resolve_verified_user",
            AsyncMock(return_value=(VerifiedUserStatus.needs_contact, None)),
        ),
        patch(
            "apps.bots.common.handlers.messages.team_invites.stash_pending_invite",
            AsyncMock(),
        ) as mock_stash,
    ):
        await handle_message_event(_message_event("/start join_tok2"), _ctx(renderer))

    mock_stash.assert_awaited_once_with("telegram", "tg1", "tok2")
    assert renderer.sent  # contact request prompt was sent


@pytest.mark.asyncio
async def test_contact_event_redeems_pending_invite() -> None:
    renderer = FakeRenderer()
    bot_user = await _bot_user(usso_user_id="usso-21")
    event = MessageEvent(
        platform="telegram",
        chat_id=1,
        message_id=2,
        sender=Sender(id="tg1"),
        metadata={"contact": {"phone_number": "+989120000000", "user_id": "tg1"}},
    )

    with (
        patch(
            "apps.bots.common.handlers.contact.get_or_create_bot_user_from_contact",
            AsyncMock(return_value=bot_user),
        ),
        patch(
            "apps.bots.common.handlers.contact.team_invites.pop_pending_invite",
            AsyncMock(return_value="tok3"),
        ),
        patch(
            "apps.bots.common.handlers.contact.team_invites.accept_invite",
            AsyncMock(return_value=(True, "Team X", "ws-1")),
        ) as mock_accept,
    ):
        await handle_contact_event(
            event, _ctx(renderer), "+989120000000", contact_user_id="tg1"
        )

    mock_accept.assert_awaited_once_with(
        token="tok3", invitee_usso_uid="usso-21", bot_user=bot_user
    )
    assert any("Team X" in msg for _chat, msg in renderer.sent)
