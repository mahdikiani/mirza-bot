"""Minimal tests for health-review checklist gaps."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.accounts.handlers import usso_identifier_type_for_platform
from apps.bots.common.auth_gate import VerifiedUserStatus
from apps.bots.common.handlers.inline import handle_inline_query_event


def test_usso_identifier_type_for_bale() -> None:
    assert usso_identifier_type_for_platform("bale") == "bale_id"
    assert usso_identifier_type_for_platform("telegram") == "telegram_id"


@pytest.mark.asyncio
async def test_inline_query_unverified_user_gets_auth_message() -> None:
    event = MagicMock()
    event.query_id = "q1"
    event.text = "hello"
    event.sender = MagicMock(id=123)
    event.raw = None
    ctx = MagicMock()
    ctx.capabilities.supports_inline_query = True
    ctx.renderer = AsyncMock()

    with (
        patch(
            "apps.bots.common.handlers.inline.resolve_verified_user",
            new_callable=AsyncMock,
            return_value=(VerifiedUserStatus.needs_contact, None),
        ),
        patch(
            "apps.bots.common.handlers.inline.get_user_locale",
            new_callable=AsyncMock,
            return_value="en",
        ),
        patch(
            "apps.bots.common.handlers.inline.text",
            return_value="Please authenticate first",
        ),
    ):
        await handle_inline_query_event(event, ctx)

    ctx.renderer.answer_inline_query.assert_awaited_once_with(
        "q1",
        "Please authenticate first",
        raw_event=None,
    )
