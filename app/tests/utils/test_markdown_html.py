"""Tests for utils.markdown_html.markdown_to_telegram_html.

Regression coverage for the "**" showing up literally in delivered results:
renderers send with parse_mode="html" (Telethon explicitly, Bale by client
default), but AI results come back as Markdown — this converter bridges
that gap into Telegram's restricted HTML tag subset.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from utils.markdown_html import markdown_to_telegram_html


class TestInlineFormatting:
    def test_bold_double_star(self) -> None:
        assert markdown_to_telegram_html("**bold**") == "<b>bold</b>"

    def test_bold_double_underscore(self) -> None:
        assert markdown_to_telegram_html("__bold__") == "<b>bold</b>"

    def test_italic_single_star(self) -> None:
        assert markdown_to_telegram_html("*italic*") == "<i>italic</i>"

    def test_italic_single_underscore(self) -> None:
        assert markdown_to_telegram_html("_italic_") == "<i>italic</i>"

    def test_bold_and_italic_together(self) -> None:
        result = markdown_to_telegram_html("**bold** and *italic*")
        assert result == "<b>bold</b> and <i>italic</i>"

    def test_strikethrough(self) -> None:
        assert markdown_to_telegram_html("~~gone~~") == "<s>gone</s>"

    def test_inline_code(self) -> None:
        assert markdown_to_telegram_html("`code`") == "<code>code</code>"

    def test_link(self) -> None:
        result = markdown_to_telegram_html("[click](https://example.com)")
        assert result == '<a href="https://example.com">click</a>'


class TestBlockStructure:
    def test_heading_becomes_bold_line(self) -> None:
        assert markdown_to_telegram_html("# Title") == "<b>Title</b>"

    def test_bullet_becomes_bullet_char(self) -> None:
        result = markdown_to_telegram_html("- item one\n- item two")
        assert result == "• item one\n• item two"

    def test_blockquote_merges_consecutive_lines(self) -> None:
        result = markdown_to_telegram_html("> line one\n> line two")
        assert result == "<blockquote>line one\nline two</blockquote>"

    def test_horizontal_rule(self) -> None:
        assert "──" in markdown_to_telegram_html("---")

    def test_code_block(self) -> None:
        result = markdown_to_telegram_html("```\nprint(1)\n```")
        assert result == "<pre>print(1)\n</pre>"


class TestHtmlSafety:
    def test_escapes_angle_brackets_and_ampersand(self) -> None:
        result = markdown_to_telegram_html("3 < 5 && a > b")
        assert result == "3 &lt; 5 &amp;&amp; a &gt; b"

    def test_code_content_is_escaped_and_not_formatted(self) -> None:
        result = markdown_to_telegram_html("`a < b and **not bold**`")
        assert result == "<code>a &lt; b and **not bold**</code>"

    def test_angle_brackets_inside_code_block_are_escaped(self) -> None:
        result = markdown_to_telegram_html("```\nx = 1 < 2\n```")
        assert "&lt;" in result
        assert "<" not in result.replace("<pre>", "").replace("</pre>", "")

    @pytest.mark.parametrize(
        "raw",
        [
            "**bold**",
            "# Heading\ntext\n- item",
            "> quote\n> more",
            "`code` and *italic* and 3 < 5",
            "[link](https://x.com) with **bold**",
            "no formatting at all",
            "",
        ],
    )
    def test_output_is_always_well_formed_xml(self, raw: str) -> None:
        out = markdown_to_telegram_html(raw)
        if not out:
            return
        ET.fromstring(f"<root>{out}</root>")


class TestRealWorldSummary:
    def test_typical_llm_summary_renders_correctly(self) -> None:
        raw = (
            "**خلاصه:** این یک متن **مهم** است.\n\n"
            "## نکات کلیدی\n"
            "- نکته اول\n"
            "- نکته دوم\n"
        )
        result = markdown_to_telegram_html(raw)

        assert "**" not in result
        assert "<b>خلاصه:</b>" in result
        assert "<b>مهم</b>" in result
        assert "<b>نکات کلیدی</b>" in result
        assert "• نکته اول" in result
