"""
Shared HTTP client factory for all internal service clients.

Every internal service is authenticated with the admin API key via
the ``x-api-key`` header. All requests include a trace ID for
distributed tracing and have configurable retry policy.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from server.config import Settings

logger = logging.getLogger(__name__)

MAX_RETRIES = 2
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def generate_trace_id() -> str:
    """Return a short unique trace ID for request tracing."""
    return uuid.uuid4().hex[:12]


def _admin_headers(
    api_key: str | None = None, trace_id: str | None = None
) -> dict[str, str]:
    """Return auth headers using the provided key or the default AI API key."""
    key = api_key if api_key is not None else (Settings.ai_api_key or "")
    headers = {"x-api-key": key}
    if trace_id:
        headers["x-trace-id"] = trace_id
    return headers


def _retry_status_error(status_code: int) -> httpx.TransportError:
    msg = f"Request failed after {MAX_RETRIES + 1} attempts, last status={status_code}"
    return httpx.TransportError(msg)


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    trace_id: str,
    **kwargs: object,
) -> httpx.Response:
    """
    Make an HTTP request with up to MAX_RETRIES retries on failures.

    Retries on network errors, timeouts, and retryable status codes (429, 5xx).
    """
    last_error: Exception | None = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in RETRYABLE_STATUSES:
                if attempt < MAX_RETRIES:
                    wait = 0.5 * (2**attempt)
                    logger.warning(
                        "trace=%s attempt=%d/%d status=%d retrying in %.1fs",
                        trace_id,
                        attempt + 1,
                        MAX_RETRIES + 1,
                        resp.status_code,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise _retry_status_error(resp.status_code)
        except (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.TransportError,
        ) as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                wait = 0.5 * (2**attempt)
                logger.warning(
                    "trace=%s attempt=%d/%d error=%s retrying in %.1fs",
                    trace_id,
                    attempt + 1,
                    MAX_RETRIES + 1,
                    exc,
                    wait,
                )
                await asyncio.sleep(wait)
                continue
            raise
        else:
            return resp
    msg = f"Request failed after {MAX_RETRIES + 1} attempts"
    if last_error:
        raise httpx.TransportError(msg) from last_error
    raise httpx.TransportError(msg)


@asynccontextmanager
async def service_client(
    base_url: str,
    api_key: str | None = None,
    request_timeout: float = 60.0,
) -> AsyncGenerator[httpx.AsyncClient]:
    """
    Async context manager that yields an authenticated httpx.AsyncClient.

    Args:
        base_url:        Base URL of the internal service.
        api_key:         Override the default AI API key (e.g. for media service).
        request_timeout: Request timeout in seconds.

    """
    trace_id = generate_trace_id()
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=_admin_headers(api_key, trace_id),
        timeout=request_timeout,
    ) as client:
        client._trace_id = trace_id
        yield client
