"""Shared API-key check for inbound service webhooks."""

from __future__ import annotations

import hmac
import logging

from fastapi import Header, HTTPException

from server.config import Settings

logger = logging.getLogger(__name__)


def _keys_match(provided: str, expected: str) -> bool:
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def require_webhook_api_key(
    x_api_key: str | None = Header(default=None, alias="x-api-key"),
) -> None:
    """
    Reject webhook calls without the configured shared secret.

    Fail-closed: missing/empty ``WEBHOOK_API_KEY`` refuses all callers.
    Comparison uses ``hmac.compare_digest`` to avoid timing leaks.
    """
    expected = Settings.webhook_api_key
    if not expected:
        logger.error("Webhook rejected: WEBHOOK_API_KEY is not configured")
        raise HTTPException(
            status_code=503,
            detail="Webhook authentication is not configured",
        )
    if not x_api_key or not _keys_match(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
