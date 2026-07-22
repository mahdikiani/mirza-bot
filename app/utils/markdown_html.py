"""Convert LLM-style Markdown to the restricted HTML subset Telegram/Bale
``parse_mode="HTML"`` actually supports.

Both delivery renderers (Telethon for Telegram, telebot for Bale) send
messages with HTML parse mode. AI results (OCR, transcription summaries,
Promptic actions) come back as plain Markdown (``**bold**``, ``# heading``,
`` `code` ``, ...), which HTML parse mode does not understand — it shows the
literal ``**`` characters instead of rendering bold text.

Telegram's Bot API HTML mode only understands a small, fixed tag set:
``b``, ``i``, ``u``, ``s``, ``a``, ``code``, ``pre``, ``blockquote``. There is
no heading or list-item entity, so headings/bullets are rendered as bold
lines / bullet characters rather than dropped silently.

Processing order matters: block-level structure (heading/bullet/quote) is
stripped from each *raw* line first, then the remaining text is HTML-escaped,
then inline formatting (bold/italic/strike/links) is applied — in that order
so ``>``/``<`` in the original content never gets confused with markup we
insert, and formatting markers we emit are never re-escaped.
"""

from __future__ import annotations

import re

_CODE_BLOCK_RE = re.compile(r"```(?:[^\n`]*\n)?(.*?)```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_BOLD_RE = re.compile(r"\*\*(?!\s)(.+?)(?<!\s)\*\*|__(?!\s)(.+?)(?<!\s)__")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)|(?<!_)_(?!\s)(.+?)(?<!\s)_(?!_)")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")

_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_BULLET_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_HR_RE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")

_PLACEHOLDER_RE = re.compile(r"\x00(\d+)\x00")


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _format_inline(content: str) -> str:
    """Escape HTML then apply inline bold/italic/strike/link markup."""
    escaped = _escape_html(content)
    escaped = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped)
    escaped = _BOLD_RE.sub(lambda m: f"<b>{m.group(1) or m.group(2)}</b>", escaped)
    escaped = _ITALIC_RE.sub(lambda m: f"<i>{m.group(1) or m.group(2)}</i>", escaped)
    escaped = _STRIKE_RE.sub(lambda m: f"<s>{m.group(1)}</s>", escaped)
    return escaped


def markdown_to_telegram_html(text: str) -> str:
    """Convert Markdown to Telegram-safe HTML for inline chat delivery.

    Kept deliberately conservative: unrecognized syntax is left as literal
    (already-escaped) text rather than guessed at, and any tag we didn't
    intend to emit can't appear because HTML-unsafe characters in the
    original content are escaped before any of our own tags are inserted.
    """
    if not text:
        return text

    # Pull out code blocks/spans first (as opaque placeholders, already
    # rendered to final HTML) so nothing else ever processes their content.
    placeholders: list[str] = []

    def _stash(html_fragment: str) -> str:
        placeholders.append(html_fragment)
        return f"\x00{len(placeholders) - 1}\x00"

    working = _CODE_BLOCK_RE.sub(
        lambda m: _stash(f"<pre>{_escape_html(m.group(1))}</pre>"), text
    )
    working = _INLINE_CODE_RE.sub(
        lambda m: _stash(f"<code>{_escape_html(m.group(1))}</code>"), working
    )

    rendered_lines: list[str] = []
    quote_buffer: list[str] = []

    def _flush_quote() -> None:
        if quote_buffer:
            rendered_lines.append(
                "<blockquote>" + "\n".join(quote_buffer) + "</blockquote>"
            )
            quote_buffer.clear()

    for line in working.split("\n"):
        quote_match = _QUOTE_RE.match(line)
        if quote_match:
            quote_buffer.append(_format_inline(quote_match.group(1)))
            continue
        _flush_quote()

        if _HR_RE.match(line):
            rendered_lines.append("──────────")
            continue

        heading_match = _HEADING_RE.match(line)
        if heading_match:
            rendered_lines.append(f"<b>{_format_inline(heading_match.group(1))}</b>")
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            rendered_lines.append(
                f"{bullet_match.group(1)}• {_format_inline(bullet_match.group(2))}"
            )
            continue

        rendered_lines.append(_format_inline(line))

    _flush_quote()
    result = "\n".join(rendered_lines)

    return _PLACEHOLDER_RE.sub(lambda m: placeholders[int(m.group(1))], result)
