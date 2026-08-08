"""Application version exposed to messenger users."""

from __future__ import annotations

APP_VERSION = "0.1.46"


def app_version() -> str:
    """Return the installed Mirza Bot package version."""
    return APP_VERSION
