"""Unit tests for apps.bots.url_fetcher.

Covers URL type detection and content fetching for YouTube, Twitter,
Instagram, and generic webpages.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.bots.url_fetcher import (
    _instagram_shortcode,
    _twitter_tweet_id,
    _youtube_video_id,
    fetch,
)

# ---------------------------------------------------------------------------
# URL type detection (pure functions — no mocking needed)
# ---------------------------------------------------------------------------


def test_youtube_video_id_watch() -> None:
    assert (
        _youtube_video_id("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        == "jNQXAC9IVRw"
    )


def test_youtube_video_id_short() -> None:
    assert _youtube_video_id("https://youtu.be/jNQXAC9IVRw") == "jNQXAC9IVRw"


def test_youtube_video_id_shorts() -> None:
    assert (
        _youtube_video_id("https://www.youtube.com/shorts/jNQXAC9IVRw") == "jNQXAC9IVRw"
    )


def test_youtube_video_id_none() -> None:
    assert _youtube_video_id("https://example.com/page") is None


def test_twitter_tweet_id() -> None:
    assert _twitter_tweet_id("https://twitter.com/user/status/123456789") == "123456789"


def test_twitter_tweet_id_x_com() -> None:
    assert _twitter_tweet_id("https://x.com/user/status/987654321") == "987654321"


def test_twitter_tweet_id_none() -> None:
    assert _twitter_tweet_id("https://youtube.com/watch?v=abc") is None


def test_instagram_shortcode() -> None:
    assert _instagram_shortcode("https://www.instagram.com/p/ABC123def/") == "ABC123def"


def test_instagram_shortcode_reel() -> None:
    assert _instagram_shortcode("https://www.instagram.com/reel/XYZ789/") == "XYZ789"


def test_instagram_shortcode_none() -> None:
    assert _instagram_shortcode("https://example.com") is None


# ---------------------------------------------------------------------------
# fetch() dispatch — mocking the internal fetchers
# ---------------------------------------------------------------------------


def _make_httpx_response(
    *, status_code: int = 200, json_data: dict | None = None, text: str = ""
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    resp.raise_for_status = MagicMock()
    return resp


def _make_async_client(response: MagicMock) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client.get = AsyncMock(return_value=response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_fetch_youtube_returns_transcript() -> None:
    """YouTube URL → calls transcript API and returns formatted text."""
    transcript_resp = _make_httpx_response(
        json_data=[
            {
                "videoId": "jNQXAC9IVRw",
                "transcripts": [
                    {"text": "Hello", "duration": 1.0, "offset": 0.0},
                    {"text": "world", "duration": 1.0, "offset": 1.0},
                ],
            }
        ]
    )
    mock_client = _make_async_client(transcript_resp)

    with (
        patch("apps.bots.url_fetcher.Settings") as mock_settings,
        patch("apps.bots.url_fetcher.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.youtube_transcript_api_key = "test-key"
        content, source_type = await fetch("https://youtu.be/jNQXAC9IVRw")

    assert source_type == "youtube"
    assert "Hello world" in content
    assert "jNQXAC9IVRw" in content


@pytest.mark.asyncio
async def test_fetch_youtube_no_api_key_raises() -> None:
    """Missing YOUTUBE_TRANSCRIPT_API_KEY raises RuntimeError."""
    with patch("apps.bots.url_fetcher.Settings") as mock_settings:
        mock_settings.youtube_transcript_api_key = None
        with pytest.raises(RuntimeError, match="YOUTUBE_TRANSCRIPT_API_KEY"):
            await fetch("https://youtu.be/jNQXAC9IVRw")


@pytest.mark.asyncio
async def test_fetch_twitter_returns_tweet_text() -> None:
    """Twitter URL → calls RapidAPI and returns tweet text."""
    tweet_resp = _make_httpx_response(
        json_data={
            "result": {
                "data": {
                    "tweetResult": {
                        "result": {
                            "legacy": {
                                "full_text": "This is a tweet",
                                "user_id_str": "12345",
                            }
                        }
                    }
                }
            }
        }
    )
    mock_client = _make_async_client(tweet_resp)

    with (
        patch("apps.bots.url_fetcher.Settings") as mock_settings,
        patch("apps.bots.url_fetcher.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.rapidapi_key = "rapid-key"
        content, source_type = await fetch("https://twitter.com/user/status/123456789")

    assert source_type == "twitter"
    assert "This is a tweet" in content


@pytest.mark.asyncio
async def test_fetch_twitter_no_api_key_raises() -> None:
    """Missing RAPIDAPI_KEY raises RuntimeError."""
    with patch("apps.bots.url_fetcher.Settings") as mock_settings:
        mock_settings.rapidapi_key = None
        with pytest.raises(RuntimeError, match="RAPIDAPI_KEY"):
            await fetch("https://twitter.com/user/status/123456789")


@pytest.mark.asyncio
async def test_fetch_instagram_returns_caption() -> None:
    """Instagram URL → calls RapidAPI and returns post caption."""
    insta_resp = _make_httpx_response(
        json_data={
            "data": {
                "edge_media_to_caption": {
                    "edges": [{"node": {"text": "Beautiful sunset"}}]
                },
                "owner": {"username": "testuser"},
            }
        }
    )
    mock_client = _make_async_client(insta_resp)

    with (
        patch("apps.bots.url_fetcher.Settings") as mock_settings,
        patch("apps.bots.url_fetcher.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.rapidapi_key = "rapid-key"
        content, source_type = await fetch("https://www.instagram.com/p/ABC123def/")

    assert source_type == "instagram"
    assert "Beautiful sunset" in content
    assert "testuser" in content


@pytest.mark.asyncio
async def test_fetch_webpage_returns_markdown() -> None:
    """Generic URL → calls Jina Reader and returns markdown content."""
    webpage_resp = _make_httpx_response(text="# Page Title\n\nSome content here.")
    mock_client = _make_async_client(webpage_resp)

    with (
        patch("apps.bots.url_fetcher.Settings") as mock_settings,
        patch("apps.bots.url_fetcher.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.jina_api_key = None
        content, source_type = await fetch("https://example.com/article")

    assert source_type == "webpage"
    assert "Page Title" in content


@pytest.mark.asyncio
async def test_fetch_youtube_empty_transcript() -> None:
    """YouTube with no transcript segments returns empty text body."""
    transcript_resp = _make_httpx_response(
        json_data=[{"videoId": "abc1234defg", "transcripts": []}]
    )
    mock_client = _make_async_client(transcript_resp)

    with (
        patch("apps.bots.url_fetcher.Settings") as mock_settings,
        patch("apps.bots.url_fetcher.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.youtube_transcript_api_key = "test-key"
        content, source_type = await fetch("https://youtu.be/abc1234defg")

    assert source_type == "youtube"
    assert "abc1234defg" in content
