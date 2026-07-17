"""Shared primitives for AI Toolkit clients."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import httpx

from server.config import Settings
from utils.clients._base import service_client


class ToolkitTaskNotCompletedError(ValueError):
    """Raised when a Toolkit task exists but is not completed yet."""


@asynccontextmanager
async def toolkit_client(
    request_timeout: float = 60.0,
) -> AsyncGenerator[httpx.AsyncClient]:
    """Yield an authenticated client for the unified AI Toolkit API."""
    async with service_client(
        Settings.ai_toolkit_base_url,
        request_timeout=request_timeout,
    ) as client:
        yield client


def completed_result_or_raise(data: dict, task_uid: str, task_type: str) -> str:
    """Return a completed Toolkit task result or raise a clear pending error."""
    if data.get("task_status") != "completed":
        status = data.get("task_status")
        msg = f"{task_type} task {task_uid} not completed: {status}"
        raise ToolkitTaskNotCompletedError(msg)
    return data.get("result") or ""
