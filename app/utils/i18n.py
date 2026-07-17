"""Small YAML-backed localization helper."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from server.config import Settings

DEFAULT_LOCALE = "fa"


@lru_cache(maxsize=8)
def _load_locale(locale: str) -> dict[str, Any]:
    path = Settings.base_dir / "texts" / f"{locale}.yaml"
    if not path.exists() and locale != DEFAULT_LOCALE:
        return _load_locale(DEFAULT_LOCALE)
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {}
    return data


def text(key: str, locale: str = DEFAULT_LOCALE, **kwargs: object) -> str:
    """Return localized text by dotted key, formatting kwargs when provided."""
    value: object = _load_locale(locale)
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            if locale != DEFAULT_LOCALE:
                return text(key, DEFAULT_LOCALE, **kwargs)
            return key
        value = value[part]

    rendered = str(value)
    if kwargs:
        return rendered.format(**kwargs)
    return rendered


def button(key: str, locale: str = DEFAULT_LOCALE) -> str:
    """Return localized button label."""
    return text(f"buttons.{key}", locale)
