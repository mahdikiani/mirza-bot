"""Tests for personal referrals and admin gift-code flows."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.common import onboarding, referrals
from apps.bots.common.auth_gate import VerifiedUser, VerifiedUserStatus
from apps.bots.common.events import MessageEvent, PlatformCapabilities, Sender
from apps.bots.common.handler import handle_contact_event, handle_message_event
from apps.bots.common.handler_context import BotRuntimeContext
from apps.bots.common.handlers.menu import handle_menu_action
from apps.bots.common.models import BotUser
from utils.i18n import text


class FakeRenderer:
    def __init__(self) -> None:
        self.sent: list[tuple[int | str, str]] = []

    async def send_typing(self, chat_id: int | str) -> None:
        pass

    async def send_text(
        self, chat_id, text_value, reply_to=None, reply_keyboard=None
    ):
        self.sent.append((chat_id, text_value))
        return MagicMock(id=99)

    async def send_contact_request(self, chat_id, text_value) -> None:
        self.sent.append((chat_id, text_value))

    async def send_inline_text(
        self, chat_id, text_value, inline_keyboard, reply_to=None
    ):
        self.sent.append((chat_id, text_value))
        return MagicMock(id=99)


def _ctx(renderer: FakeRenderer, platform: str = "telegram") -> BotRuntimeContext:
    return BotRuntimeContext(
        bot_name="bot",
        platform=platform,
        renderer=renderer,
        capabilities=PlatformCapabilities(),
        bot_username="mirzbenevisabot",
    )


def _message_event(
    text_value: str,
    *,
    chat_id: int | str = 1,
    sender_id: int | str = "ref-tg1",
    platform: str = "telegram",
) -> MessageEvent:
    return MessageEvent(
        platform=platform,
        chat_id=chat_id,
        message_id=1,
        text=text_value,
        sender=Sender(id=sender_id, first_name="Ali"),
    )


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("/start ref_abc123", "abc123"),
        ("/start gift_abc123", None),
        ("/start ref_", None),
        ("/start something_else", None),
        ("/start", None),
    ],
)
def test_parse_referral_payload(payload: str, expected: str | None) -> None:
    assert referrals.parse_start_payload(payload) == expected


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("/start gift_xyz789", "xyz789"),
        ("/start ref_xyz789", None),
        ("/start gift_", None),
        ("/start something_else", None),
        ("/start", None),
    ],
)
def test_parse_gift_payload(payload: str, expected: str | None) -> None:
    assert referrals.parse_gift_payload(payload) == expected


@pytest.mark.asyncio
async def test_pending_referral_roundtrip_with_redis() -> None:
    store: dict[str, str] = {}
    expirations: dict[str, int] = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            store[key] = value
            expirations[key] = ex

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    with patch("apps.bots.common.referrals.get_redis", return_value=FakeRedis()):
        await referrals.stash_pending_referral("telegram", "tg1", "ref-1")
        assert store == {"referral_pending:telegram:tg1": "ref-1"}
        assert expirations["referral_pending:telegram:tg1"] == 900
        assert await referrals.pop_pending_referral("telegram", "tg1") == "ref-1"
        assert await referrals.pop_pending_referral("telegram", "tg1") is None


@pytest.mark.asyncio
async def test_pending_gift_roundtrip_with_redis() -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        async def set(self, key, value, ex=None):
            assert ex == 900
            store[key] = value

        async def get(self, key):
            return store.get(key)

        async def delete(self, key):
            store.pop(key, None)

    with patch("apps.bots.common.referrals.get_redis", return_value=FakeRedis()):
        await referrals.stash_pending_gift("bale", "b1", "gift-1")
        assert store == {"gift_pending:bale:b1": "gift-1"}
        assert await referrals.pop_pending_gift("bale", "b1") == "gift-1"
        assert await referrals.pop_pending_gift("bale", "b1") is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "target", "code"),
    [
        ("/start ref_friend", "stash_pending_referral", "friend"),
        ("/start gift_bonus", "stash_pending_gift", "bonus"),
    ],
)
async def test_start_stashes_pending_code_for_unverified_user(
    payload: str, target: str, code: str
) -> None:
    renderer = FakeRenderer()
    event = _message_event(payload)
    mock_stash = AsyncMock()

    with (
        patch(
            "apps.bots.common.handlers.messages.resolve_verified_user",
            AsyncMock(return_value=(VerifiedUserStatus.needs_contact, None)),
        ),
        patch(f"apps.bots.common.handlers.messages.referrals.{target}", mock_stash),
    ):
        await handle_message_event(event, _ctx(renderer))

    mock_stash.assert_awaited_once_with("telegram", "ref-tg1", code)
    assert renderer.sent


@pytest.mark.asyncio
async def test_start_redeems_gift_for_verified_user() -> None:
    renderer = FakeRenderer()
    bot_user = MagicMock()
    verified = VerifiedUser(usso_uid="usso-gift", bot_user=bot_user)

    with (
        patch(
            "apps.bots.common.handlers.messages.resolve_verified_user",
            AsyncMock(return_value=(VerifiedUserStatus.ok, verified)),
        ),
        patch(
            "apps.bots.common.handlers.messages.ShopClient.redeem_gift_code",
            AsyncMock(return_value={"status": "rewarded", "reward_coins": 20}),
        ) as mock_redeem,
    ):
        await handle_message_event(
            _message_event("/start gift_bonus"), _ctx(renderer)
        )

    mock_redeem.assert_awaited_once_with("bonus", "usso-gift")
    assert any(
        message == text("messages.gift_redeemed", locale="fa")
        for _chat, message in renderer.sent
    )
    assert len(renderer.sent) >= 2


@pytest.mark.asyncio
async def test_new_onboarding_threads_referrer_code() -> None:
    event = _message_event("", sender_id="new-referral-user")
    usso_user = SimpleNamespace(uid="usso-new-referral-user")
    usso = AsyncMock()
    usso.get_user_by_identifier = AsyncMock(return_value=None)
    usso.get_or_create_user_by_identifier = AsyncMock(return_value=usso_user)
    usso.link_identifier = AsyncMock()
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = usso
    client_cm.__aexit__.return_value = False

    with patch(
        "apps.bots.common.onboarding.usso_accounts_client", return_value=client_cm
    ):
        bot_user, is_new = await onboarding.get_or_create_bot_user_from_contact(
            event,
            "+989120000001",
            referrer_code="friend-code",
        )

    assert is_new is True
    assert bot_user.usso_user_id == "usso-new-referral-user"
    usso.get_or_create_user_by_identifier.assert_awaited_once_with(
        "telegram_id",
        "new-referral-user",
        referrer_code="friend-code",
    )


@pytest.mark.asyncio
async def test_existing_onboarding_does_not_thread_referrer_code() -> None:
    event = _message_event("", sender_id="existing-referral-user")
    existing = BotUser(
        user_id="existing-usso",
        telegram_user_id="existing-referral-user",
        platform_user_id="existing-referral-user",
        usso_user_id="existing-usso",
        phone_verified=True,
    )
    await existing.save()
    usso = AsyncMock()
    usso.get_user_by_identifier = AsyncMock(return_value=None)
    usso.get_or_create_user_by_identifier = AsyncMock(
        return_value=SimpleNamespace(uid="existing-usso")
    )
    usso.link_identifier = AsyncMock()
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = usso
    client_cm.__aexit__.return_value = False

    with patch(
        "apps.bots.common.onboarding.usso_accounts_client", return_value=client_cm
    ):
        bot_user, is_new = await onboarding.get_or_create_bot_user_from_contact(
            event,
            "+989120000002",
            referrer_code="must-be-ignored",
        )

    assert is_new is False
    assert bot_user.id == existing.id
    usso.get_or_create_user_by_identifier.assert_awaited_once_with(
        "telegram_id", "existing-referral-user"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "expected_fragment"),
    [
        ("share-me", "start=ref_share-me"),
        (None, text("messages.invite_link_error", locale="en")),
    ],
)
async def test_invite_menu_action(
    code: str | None, expected_fragment: str
) -> None:
    renderer = FakeRenderer()
    event = _message_event("/invite")
    client = AsyncMock()
    client.get_my_referral_code = AsyncMock(return_value=code)
    client_cm = AsyncMock()
    client_cm.__aenter__.return_value = client
    client_cm.__aexit__.return_value = False

    with patch(
        "apps.bots.common.handlers.menu.usso_accounts_client",
        return_value=client_cm,
    ):
        handled = await handle_menu_action(
            "invite", event, _ctx(renderer), "en", "usso-menu"
        )

    assert handled is True
    client.get_my_referral_code.assert_awaited_once_with("usso-menu")
    assert expected_fragment in renderer.sent[0][1]


@pytest.mark.asyncio
async def test_gift_command_is_silent_for_non_admin() -> None:
    renderer = FakeRenderer()
    with (
        patch("apps.bots.common.handlers.messages.Settings.admin_chat_id", "999"),
        patch(
            "apps.bots.common.handlers.messages.ShopClient.create_gift_code",
            AsyncMock(),
        ) as mock_create,
    ):
        await handle_message_event(
            _message_event("/gift 5", chat_id=123), _ctx(renderer)
        )

    mock_create.assert_not_awaited()
    assert renderer.sent == []


@pytest.mark.asyncio
async def test_gift_command_creates_link_for_admin() -> None:
    renderer = FakeRenderer()
    with (
        patch("apps.bots.common.handlers.messages.Settings.admin_chat_id", "123"),
        patch(
            "apps.bots.common.handlers.messages.ShopClient.create_gift_code",
            AsyncMock(return_value={"code": "admin-code"}),
        ) as mock_create,
    ):
        await handle_message_event(
            _message_event("/gift 25", chat_id=123), _ctx(renderer)
        )

    mock_create.assert_awaited_once_with(25)
    assert "start=gift_admin-code" in renderer.sent[0][1]


@pytest.mark.asyncio
async def test_gift_command_without_value_defaults_to_single_use() -> None:
    renderer = FakeRenderer()
    with (
        patch("apps.bots.common.handlers.messages.Settings.admin_chat_id", "123"),
        patch(
            "apps.bots.common.handlers.messages.ShopClient.create_gift_code",
            AsyncMock(return_value={"code": "single-use-code"}),
        ) as mock_create,
    ):
        await handle_message_event(
            _message_event("/gift", chat_id=123), _ctx(renderer)
        )

    mock_create.assert_awaited_once_with(1)
    assert "start=gift_single-use-code" in renderer.sent[0][1]


@pytest.mark.asyncio
async def test_gift_command_rejects_non_numeric_value() -> None:
    renderer = FakeRenderer()
    with (
        patch("apps.bots.common.handlers.messages.Settings.admin_chat_id", "123"),
        patch(
            "apps.bots.common.handlers.messages.ShopClient.create_gift_code",
            AsyncMock(),
        ) as mock_create,
    ):
        await handle_message_event(
            _message_event("/gift abc", chat_id=123), _ctx(renderer)
        )

    mock_create.assert_not_awaited()
    assert text("messages.gift_usage", locale="fa") in renderer.sent[0][1]


@pytest.mark.asyncio
async def test_contact_passes_referral_and_redeems_pending_gift() -> None:
    renderer = FakeRenderer()
    event = _message_event("", sender_id="contact-referral-user")
    bot_user = MagicMock(usso_user_id="usso-contact")

    with (
        patch(
            "apps.bots.common.handlers.contact.referrals.pop_pending_referral",
            AsyncMock(return_value="friend-code"),
        ),
        patch(
            "apps.bots.common.handlers.contact.get_or_create_bot_user_from_contact",
            AsyncMock(return_value=(bot_user, True)),
        ) as mock_onboard,
        patch(
            "apps.bots.common.handlers.contact.team_invites.pop_pending_invite",
            AsyncMock(return_value=None),
        ),
        patch(
            "apps.bots.common.handlers.contact.referrals.pop_pending_gift",
            AsyncMock(return_value="gift-code"),
        ),
        patch(
            "apps.bots.common.handlers.contact.ShopClient.redeem_gift_code",
            AsyncMock(return_value={"status": "rewarded"}),
        ) as mock_redeem,
    ):
        await handle_contact_event(
            event,
            _ctx(renderer),
            phone_number="+989120000003",
            contact_user_id="contact-referral-user",
        )

    mock_onboard.assert_awaited_once_with(
        event,
        "+989120000003",
        referrer_code="friend-code",
    )
    mock_redeem.assert_awaited_once_with("gift-code", "usso-contact")
    assert any(
        message == text("messages.gift_redeemed", locale="fa")
        for _chat, message in renderer.sent
    )
