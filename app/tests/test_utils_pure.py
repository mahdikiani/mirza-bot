"""Unit tests for pure utility functions (b64tools, texttools, i18n)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from utils import b64tools, texttools
from utils.i18n import button, text

# ---------------------------------------------------------------------------
# b64tools
# ---------------------------------------------------------------------------


class TestB64Tools:
    def test_b64_encode_uuid(self) -> None:
        encoded = b64tools.b64_encode_uuid("550e8400-e29b-41d4-a716-446655440000")
        assert isinstance(encoded, str)
        assert "=" in encoded  # standard base64 has padding

    def test_b64_encode_uuid_strip_removes_padding(self) -> None:
        encoded = b64tools.b64_encode_uuid_strip("550e8400-e29b-41d4-a716-446655440000")
        assert "=" not in encoded

    def test_b64_decode_uuid_roundtrip(self) -> None:
        original = "550e8400-e29b-41d4-a716-446655440000"
        encoded = b64tools.b64_encode_uuid_strip(original)
        decoded = b64tools.b64_decode_uuid(encoded)
        assert str(decoded) == original

    def test_b64_decode_uuid_without_padding(self) -> None:
        uuid_obj = b64tools.b64_decode_uuid("VQ6EAOKbQdSnFkRmVUQAAA")
        assert str(uuid_obj) == "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# texttools
# ---------------------------------------------------------------------------


class TestTexttoolsValidators:
    def test_is_valid_uuid_true(self) -> None:
        assert texttools.is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_is_valid_uuid_false(self) -> None:
        assert texttools.is_valid_uuid("not-a-uuid") is False

    def test_is_valid_url_http(self) -> None:
        assert texttools.is_valid_url("https://example.com/path") is True

    def test_is_valid_url_no_scheme(self) -> None:
        assert texttools.is_valid_url("not-a-url") is False

    def test_is_valid_url_ftp(self) -> None:
        assert texttools.is_valid_url("ftp://files.example.com") is True

    def test_contains_valid_urls_single(self) -> None:
        result = texttools.contains_valid_urls("https://example.com/page")
        assert result == ["https://example.com/page"]

    def test_contains_valid_urls_with_trailing_path(self) -> None:
        result = texttools.contains_valid_urls("https://example.com/path/to/page")
        assert result == ["https://example.com/path/to/page"]

    def test_contains_valid_urls_full_string_only(self) -> None:
        result = texttools.contains_valid_urls("https://a.com/path")
        assert result == ["https://a.com/path"]

    def test_contains_valid_urls_none(self) -> None:
        assert texttools.contains_valid_urls("no urls here") == []

    def test_contains_valid_urls_embedded(self) -> None:
        result = texttools.contains_valid_urls(
            "check https://example.com/page for details"
        )
        assert result == ["https://example.com/page"]

    def test_contains_valid_urls_with_query_string(self) -> None:
        result = texttools.contains_valid_urls(
            "Watch https://www.youtube.com/watch?v=dQw4w9WgXcQ now"
        )
        assert result == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]

    def test_is_username_valid(self) -> None:
        assert texttools.is_username("user_name") is True

    def test_is_username_too_short(self) -> None:
        assert texttools.is_username("ab") is False

    def test_is_email_valid(self) -> None:
        assert texttools.is_email("user@example.com") is True

    def test_is_email_invalid(self) -> None:
        assert texttools.is_email("not-an-email") is False

    def test_is_phone_valid(self) -> None:
        assert texttools.is_phone("+989123456789") is True

    def test_is_phone_invalid(self) -> None:
        assert texttools.is_phone("abc") is False


class TestTexttoolsFormatting:
    def test_json_extractor(self) -> None:
        result = texttools.json_extractor('before {"key": "value"} after')
        assert result == {"key": "value"}

    def test_format_string_keys(self) -> None:
        result = texttools.format_string_keys("Hello {name}, you are {age}")
        assert result == {"name", "age"}

    def test_format_string_fixer(self) -> None:
        result = texttools.format_string_fixer(names=["a", "b"], vals=[1, 2])
        assert result == [
            {"names": "a", "vals": 1},
            {"names": "b", "vals": 2},
        ]

    def test_escape_markdown(self) -> None:
        result = texttools.escape_markdown("_hello_ *world* [link]")
        assert "\\_" in result
        assert "\\*" in result
        assert "\\[" in result

    def test_convert_to_english_digits_persian(self) -> None:
        result = texttools.convert_to_english_digits("۱۲۳")
        assert result == "123"

    def test_convert_to_english_digits_arabic(self) -> None:
        result = texttools.convert_to_english_digits("٤٥٦")
        assert result == "456"

    def test_convert_to_english_digits_mixed(self) -> None:
        result = texttools.convert_to_english_digits("abc\u06f1\u06f2\u06f3def")
        assert result == "abc123def"


class TestTexttoolsSplitText:
    def test_split_text_short(self) -> None:
        result = texttools.split_text("Hello world", max_chunk_size=4096)
        assert result == ["Hello world"]

    def test_split_text_multiple_paragraphs(self) -> None:
        text = "A" * 100 + "\n\n" + "B" * 100
        result = texttools.split_text(text, max_chunk_size=80)
        assert len(result) >= 2

    def test_split_text_single_paragraph_returns_one_chunk(self) -> None:
        text = "word " * 2000
        result = texttools.split_text(text, max_chunk_size=1000)
        assert len(result) == 1
        assert len(result[0]) <= 1000

    def test_split_text_sentence_split(self) -> None:
        text = "Short sentence. " * 50
        result = texttools.split_text(text, max_chunk_size=200)
        assert len(result) >= 2

    def test_split_text_preserves_code_blocks(self) -> None:
        text = "before\n```\ncode block\n```\nafter"
        result = texttools.split_text(text, max_chunk_size=50)
        assert len(result) >= 1


class TestTexttoolsSanitize:
    def test_sanitize_filename_simple(self) -> None:
        result = texttools.sanitize_filename("my file.txt")
        assert " " not in result  # spaces replaced

    def test_sanitize_filename_from_url(self) -> None:
        result = texttools.sanitize_filename("https://example.com/path/to/document.pdf")
        assert "document" in result

    def test_sanitize_filename_max_length(self) -> None:
        result = texttools.sanitize_filename(
            "a" * 200 + ".txt", max_length=50, space_remover=False
        )
        assert len(result) <= 50

    def test_remove_whitespace(self) -> None:
        result = texttools.remove_whitespace("hello   world\n\n  test")
        assert "  " not in result

    def test_generate_random_chars(self) -> None:
        result = texttools.generate_random_chars(10)
        assert len(result) == 10
        assert result.isalnum()

    def test_replace_unicode_digits(self) -> None:
        import re

        result = re.sub(r"\d", texttools.replace_unicode_digits, "\u06f5")
        assert result == "5"


# ---------------------------------------------------------------------------
# i18n — use monkeypatch on Settings.base_dir to control file loading
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.usefixtures("_clear_i18n_cache")


@pytest.fixture
def _clear_i18n_cache() -> None:
    from utils.i18n import _load_locale

    _load_locale.cache_clear()


class TestI18n:
    @staticmethod
    def _write_locale(base_dir: Path, locale: str, data: dict) -> None:
        texts_dir = base_dir / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)
        (texts_dir / f"{locale}.yaml").write_text(
            yaml.dump(data, allow_unicode=True), encoding="utf-8"
        )

    def test_text_returns_localized_value(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(
            tmp_path,
            "fa",
            {
                "messages": {"hello": "سلام {name}", "start": "خوش آمدید"},
            },
        )
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("messages.start") == "خوش آمدید"

    def test_text_with_formatting(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"messages": {"hello": "سلام {name}"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("messages.hello", name="علی") == "سلام علی"

    def test_text_returns_key_when_not_found(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"messages": {"start": "خوش آمدید"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("messages.nonexistent") == "messages.nonexistent"

    def test_text_falls_back_from_en_to_fa(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"messages": {"hello": "سلام"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("messages.start", locale="en") == "messages.start"

    def test_text_fallback_uses_fa_when_en_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"messages": {"fallback": "پیام پیش‌فرض"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("messages.fallback", locale="en") == "پیام پیش‌فرض"

    def test_button_returns_localized(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"buttons": {"help": "راهنما"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert button("help") == "راهنما"

    def test_button_returns_key_when_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._write_locale(tmp_path, "fa", {"buttons": {"help": "راهنما"}})
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert button("nonexistent") == "buttons.nonexistent"

    def test_non_dict_yaml_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        texts_dir = tmp_path / "texts"
        texts_dir.mkdir(parents=True)
        (texts_dir / "fa.yaml").write_text("just a string\n", encoding="utf-8")
        monkeypatch.setattr("server.config.Settings.base_dir", tmp_path, raising=False)
        assert text("any.key") == "any.key"
