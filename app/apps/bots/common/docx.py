"""Extract plain text from .docx files without extra dependencies."""


from __future__ import annotations

import io
import re
import zipfile

# OOXML text runs: <w:t ...>content</w:t> (prefix may vary; local name is ``t``).
_W_T_RE = re.compile(
    rb"<(?:[\w-]+:)?t(?:\s[^>]*)?>(.*?)</(?:[\w-]+:)?t>",
    re.DOTALL,
)


def extract_docx_text(data: bytes) -> str:
    """Return paragraph text from a .docx file."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_bytes = archive.read("word/document.xml")
    parts: list[str] = []
    for match in _W_T_RE.finditer(xml_bytes):
        chunk = match.group(1).decode("utf-8", errors="replace")
        # Decode a few common XML entities that appear in Word runs.
        chunk = (
            chunk.replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&amp;", "&")
            .replace("&quot;", '"')
            .replace("&apos;", "'")
        )
        parts.append(chunk)
    return "".join(parts).strip()
