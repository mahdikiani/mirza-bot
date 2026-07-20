"""Shared API-key check for inbound service webhooks."""

from __future__ import annotations

from fastapi import Header, HTTPException

from server.config import Settings


def require_webhook_api_key(
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    """Reject webhook calls without the configured shared secret."""
    expected = Settings.webhook_api_key
    if not expected:
        return
    if not x_api_key or x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
