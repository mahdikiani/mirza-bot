"""URL content fetcher.

Detects the type of URL and extracts its content:
  - YouTube          -> transcript via youtube-transcript.io API
  - Twitter/X        -> tweet text via RapidAPI
  - Instagram        -> post caption via RapidAPI
  - Generic webpage  -> clean Markdown via Jina Reader (r.jina.ai)
"""

from __future__ import annotations

import re

import httpx

from server.config import Settings

# ---------------------------------------------------------------------------
# URL type detection
# ---------------------------------------------------------------------------

_YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)
_TWITTER_RE = re.compile(r"(?:twitter\.com|x\.com)/\w+/status/(\d+)")
_INSTAGRAM_RE = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)")


def _youtube_video_id(url: str) -> str | None:
    m = _YOUTUBE_RE.search(url)
    return m.group(1) if m else None


def _twitter_tweet_id(url: str) -> str | None:
    m = _TWITTER_RE.search(url)
    return m.group(1) if m else None


def _instagram_shortcode(url: str) -> str | None:
    m = _INSTAGRAM_RE.search(url)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# YouTube transcript
# ---------------------------------------------------------------------------


async def _fetch_youtube(video_id: str) -> str:
    """Fetch transcript via youtube-transcript.io REST API."""
    api_key = Settings.youtube_transcript_api_key
    if not api_key:
        raise RuntimeError("YOUTUBE_TRANSCRIPT_API_KEY is not set")

    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(
            "https://www.youtube-transcript.io/api/transcripts",
            json={"ids": [video_id]},
            headers={
                "Authorization": f"Basic {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    # Response: list of {videoId, transcripts: [{text, duration, offset}, ...]}
    videos = data if isinstance(data, list) else []
    segments = videos[0].get("transcripts", []) if videos else []
    text = " ".join(s.get("text", "") for s in segments)
    return f"[ترنسکریپت یوتیوب — {video_id}]\n\n{text}"


# ---------------------------------------------------------------------------
# Twitter / X
# ---------------------------------------------------------------------------


async def _fetch_twitter(tweet_id: str) -> str:
    api_key = Settings.rapidapi_key
    if not api_key:
        raise RuntimeError("RAPIDAPI_KEY is not set")

    async with httpx.AsyncClient(timeout=20) as c:
        resp = await c.get(
            "https://twitter241.p.rapidapi.com/tweet",
            params={"pid": tweet_id},
            headers={
                "x-rapidapi-host": "twitter241.p.rapidapi.com",
                "x-rapidapi-key": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    result = data.get("result") or {}
    tweet = (
        result
        .get("data", {})
        .get("tweetResult", {})
        .get("result", {})
        .get("legacy", {})
    )
    text = tweet.get("full_text") or tweet.get("text") or ""
    user = tweet.get("user_id_str", "")
    return f"[توییت — {tweet_id}]\n\n{text}\n\nکاربر: {user}"


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------


async def _fetch_instagram(shortcode: str) -> str:
    api_key = Settings.rapidapi_key
    if not api_key:
        raise RuntimeError("RAPIDAPI_KEY is not set")

    async with httpx.AsyncClient(timeout=20) as c:
        resp = await c.get(
            "https://instagram-scraper-api2.p.rapidapi.com/v1/post_info",
            params={"code_or_id_or_url": shortcode},
            headers={
                "x-rapidapi-host": "instagram-scraper-api2.p.rapidapi.com",
                "x-rapidapi-key": api_key,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    item = data.get("data") or {}
    caption_edges = item.get("edge_media_to_caption", {}).get("edges") or []
    caption = caption_edges[0]["node"]["text"] if caption_edges else ""
    owner = item.get("owner", {}).get("username", "")
    return f"[اینستاگرام — {shortcode}]\n\n{caption}\n\nاکانت: @{owner}"


# ---------------------------------------------------------------------------
# Generic webpage via Jina Reader
# ---------------------------------------------------------------------------


async def _fetch_webpage(url: str) -> str:
    """Use Jina Reader (r.jina.ai) to get clean Markdown from any webpage."""
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"Accept": "text/markdown"}
    if Settings.jina_api_key:
        headers["Authorization"] = f"Bearer {Settings.jina_api_key}"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        resp = await c.get(jina_url, headers=headers)
        resp.raise_for_status()

    return resp.text.strip()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def fetch(url: str) -> tuple[str, str]:
    """Fetch content from a URL.

    Returns (content, source_type) where source_type is one of:
    "youtube" | "twitter" | "instagram" | "webpage"
    """
    video_id = _youtube_video_id(url)
    if video_id:
        return await _fetch_youtube(video_id), "youtube"

    tweet_id = _twitter_tweet_id(url)
    if tweet_id:
        return await _fetch_twitter(tweet_id), "twitter"

    shortcode = _instagram_shortcode(url)
    if shortcode:
        return await _fetch_instagram(shortcode), "instagram"

    return await _fetch_webpage(url), "webpage"
