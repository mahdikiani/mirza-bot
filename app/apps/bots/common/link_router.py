"""URL classification for link handling."""

from __future__ import annotations

import re
from enum import StrEnum

from utils.texttools import contains_valid_urls

YOUTUBE_PATTERN = re.compile(
    r"(?:youtube\.com|youtu\.be)",
    re.IGNORECASE,
)
GDRIVE_PATTERN = re.compile(
    r"(?:drive\.google\.com|docs\.google\.com)",
    re.IGNORECASE,
)
FILE_EXT_PATTERN = re.compile(
    r"\.(pdf|png|jpe?g|gif|webp|mp3|ogg|wav|mp4|mov|avi|mkv|webm|txt|md|docx?|csv)(?:\?|$)",
    re.IGNORECASE,
)


class LinkKind(StrEnum):
    """Classification of a URL found in a user message."""

    youtube = "youtube"
    gdrive = "gdrive"
    file = "file"
    webpage = "webpage"


def classify_url(url: str) -> LinkKind:
    """Classify a single URL."""
    if YOUTUBE_PATTERN.search(url):
        return LinkKind.youtube
    if GDRIVE_PATTERN.search(url):
        return LinkKind.gdrive
    if FILE_EXT_PATTERN.search(url):
        return LinkKind.file
    return LinkKind.webpage


def classify_urls_in_text(text_value: str) -> list[tuple[str, LinkKind]]:
    """Return (url, kind) pairs for all URLs in text."""
    urls = contains_valid_urls(text_value)
    return [(url, classify_url(url)) for url in urls]


def is_media_file_url(url: str) -> bool:
    """Return whether the URL likely points to OCR/transcribe media."""
    kind = classify_url(url)
    return kind in {LinkKind.file, LinkKind.gdrive}


def is_audio_video_url(url: str) -> bool:
    """Heuristic: extension-based audio/video detection."""
    return bool(
        re.search(
            r"\.(mp3|ogg|wav|m4a|mp4|mov|avi|mkv|webm)(?:\?|$)",
            url,
            re.IGNORECASE,
        )
    )
