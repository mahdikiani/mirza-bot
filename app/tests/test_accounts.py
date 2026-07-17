"""
Unit tests for apps.accounts.handlers.get_user_profile.

Validates: Requirements 13.1, 13.2, 13.3
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio

from apps.accounts.handlers import get_user_profile
from apps.accounts.schemas import Profile

pytestmark = pytest.mark.usefixtures("_clear_profile_cache")


@pytest_asyncio.fixture
async def _clear_profile_cache() -> None:
    """Clear the aiocache cache before each test."""
    await get_user_profile.cache.clear()


def _mock_response(
    *, status_code: int = 200, json_data: dict | None = None
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _make_mock_client(mock_resp: MagicMock) -> AsyncMock:
    mock_client = AsyncMock()
    if mock_resp.status_code >= 400:
        mock_client.get_profile = AsyncMock(
            side_effect=mock_resp.raise_for_status.side_effect
        )
    else:
        mock_client.get_profile = AsyncMock(return_value=Profile(**mock_resp.json()))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


PROFILE_PAYLOAD = {
    "uid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "user_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "profile_data": {
        "engine_config": {
            "model": "openai/gpt-4o-mini",
            "personal_prompt": None,
            "summary_style": "concise",
            "language": "fa",
        },
    },
}


@pytest.mark.asyncio
async def test_get_user_profile_success() -> None:
    """Req 13.2: Successful USSO response returns a Profile object."""
    mock_resp = _mock_response(status_code=200, json_data=PROFILE_PAYLOAD)
    mock_client = _make_mock_client(mock_resp)

    with patch("apps.accounts.handlers.get_usso_client", return_value=mock_client):
        result = await get_user_profile("test-user-id")

    assert isinstance(result, Profile)
    assert result.profile_data.engine_config.model == "openai/gpt-4o-mini"
    assert result.profile_data.engine_config.language == "fa"
    mock_client.get_profile.assert_awaited_once_with("test-user-id")


@pytest.mark.asyncio
async def test_get_user_profile_http_error_propagates() -> None:
    """Req 13.3: HTTP errors from USSO are propagated as exceptions."""
    mock_resp = _mock_response(status_code=403)
    mock_client = _make_mock_client(mock_resp)

    with (
        patch("apps.accounts.handlers.get_usso_client", return_value=mock_client),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await get_user_profile("bad-user-id")


@pytest.mark.asyncio
async def test_get_user_profile_server_error_propagates() -> None:
    """Req 13.3: 500 server errors from USSO are also propagated."""
    mock_resp = _mock_response(status_code=500)
    mock_client = _make_mock_client(mock_resp)

    with (
        patch("apps.accounts.handlers.get_usso_client", return_value=mock_client),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await get_user_profile("server-error-user")
