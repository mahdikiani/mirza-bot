"""Extract plain text from .docx files without extra dependencies."""


from __future__ import annotations

import io
import re
import zipfile

# OOXML paragraphs/text runs: <w:p ...>...</w:p>, <w:t ...>content</w:t>
# (prefix may vary; local name is ``p``/``t``). Paragraphs never nest, so
# non-greedy matching against the first closing tag is safe.
_W_P_RE = re.compile(
    rb"<(?:[\w-]+:)?p(?:\s[^>]*)?>(.*?)</(?:[\w-]+:)?p>",
    re.DOTALL,
)
_W_T_RE = re.compile(
    rb"<(?:[\w-]+:)?t(?:\s[^>]*)?>(.*?)</(?:[\w-]+:)?t>",
    re.DOTALL,
)


def _decode_run(chunk: bytes) -> str:
    text = chunk.decode("utf-8", errors="replace")
    # Decode a few common XML entities that appear in Word runs.
    return (
        text.replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


def extract_docx_text(data: bytes) -> str:
    """Return paragraph text from a .docx file, one paragraph per line."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml_bytes = archive.read("word/document.xml")
    paragraphs: list[str] = []
    for p_match in _W_P_RE.finditer(xml_bytes):
        runs = [_decode_run(t.group(1)) for t in _W_T_RE.finditer(p_match.group(1))]
        paragraphs.append("".join(runs))
    return "\n".join(paragraphs).strip()
