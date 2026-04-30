"""Shared HTTP client factory for all internal service clients.

Every internal service is authenticated with the admin API key via
the ``x-api-key`` header.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from server.config import Settings


def _admin_headers(api_key: str | None = None) -> dict[str, str]:
    """Return auth headers using the provided key or the default AI API key."""
    key = api_key if api_key is not None else (Settings.ai_api_key or "")
    return {"x-api-key": key}


@asynccontextmanager
async def service_client(
    base_url: str,
    api_key: str | None = None,
    request_timeout: float = 60.0,
) -> AsyncGenerator[httpx.AsyncClient]:
    """Async context manager that yields an authenticated httpx.AsyncClient.

    Args:
        base_url:        Base URL of the internal service.
        api_key:         Override the default AI API key (e.g. for media service).
        request_timeout: Request timeout in seconds.
    """
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=_admin_headers(api_key),
        timeout=request_timeout,
    ) as client:
        yield client
