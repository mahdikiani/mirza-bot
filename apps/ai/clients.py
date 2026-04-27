"""Async HTTP clients for internal microservices.

All clients authenticate with the admin API key and forward the user_id
so each service can charge the correct user's coins.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from server.config import Settings


def _admin_headers() -> dict[str, str]:
    return {"x-api-key": Settings.ai_api_key or ""}


@asynccontextmanager
async def _client(base_url: str) -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=_admin_headers(),
        timeout=60.0,
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------


class OCRClient:
    """Submit OCR tasks to services/ai and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        async with _client(Settings.ai_base_url) as c:
            resp = await c.post(
                "/ocrs",
                json={
                    "file_url": file_url,
                    "user_id": user_id,
                    "webhook_url": webhook_url,
                    "meta_data": meta_data or {},
                },
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def get_result(task_uid: str) -> str:
        async with _client(Settings.ai_base_url) as c:
            resp = await c.get(f"/ocrs/{task_uid}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("task_status") != "completed":
                msg = f"OCR task {task_uid} not completed: {data.get('task_status')}"
                raise ValueError(msg)
            return data.get("result") or ""


# ---------------------------------------------------------------------------
# Transcribe
# ---------------------------------------------------------------------------


class TranscribeClient:
    """Submit transcription tasks to services/ai and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
    ) -> dict:
        async with _client(Settings.ai_base_url) as c:
            resp = await c.post(
                "/transcribes",
                json={
                    "file_url": file_url,
                    "user_id": user_id,
                    "webhook_url": webhook_url,
                },
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def get_result(task_uid: str) -> str:
        async with _client(Settings.ai_base_url) as c:
            resp = await c.get(f"/transcribes/{task_uid}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("task_status") != "completed":
                msg = f"Transcribe task {task_uid} not completed: {data.get('task_status')}"
                raise ValueError(msg)
            return data.get("result") or ""


# ---------------------------------------------------------------------------
# AI Chat
# ---------------------------------------------------------------------------


class AIChatClient:
    """Manage chat sessions and messages via services/ai-chat."""

    @staticmethod
    async def get_or_create_session(
        user_id: str,
        chat_id: str,
        engine_config: dict | None = None,
    ) -> dict:
        async with _client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                "/sessions",
                json={
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "engine_config": engine_config or {},
                },
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def send_message(
        session_id: str,
        content: str,
    ) -> str:
        async with _client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                f"/sessions/{session_id}/messages",
                json={"content": content, "role": "user"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("content", "")

    @staticmethod
    async def set_context(session_id: str, context: str, context_type: str) -> None:
        async with _client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                f"/sessions/{session_id}/context",
                json={"content": context, "context_type": context_type},
            )
            resp.raise_for_status()

    @staticmethod
    async def new_session(user_id: str, chat_id: str) -> dict:
        async with _client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                "/sessions",
                json={"user_id": user_id, "chat_id": chat_id, "force_new": True},
            )
            resp.raise_for_status()
            return resp.json()


# ---------------------------------------------------------------------------
# Promptic
# ---------------------------------------------------------------------------


class PrompticClient:
    """Execute named prompt templates via services/promptic."""

    @staticmethod
    async def execute(
        template: str,
        variables: dict[str, Any],
        user_id: str | None = None,
    ) -> str:
        payload: dict[str, Any] = {"template": template, "variables": variables}
        if user_id:
            payload["user_id"] = user_id
        async with _client(Settings.promptic_base_url) as c:
            resp = await c.post("/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")

    @staticmethod
    async def render(template: str, variables: dict[str, Any]) -> str:
        async with _client(Settings.promptic_base_url) as c:
            resp = await c.post(
                "/render", json={"template": template, "variables": variables}
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", "")


# ---------------------------------------------------------------------------
# Media upload (moved from utils/media.py pattern for consistency)
# ---------------------------------------------------------------------------


class MediaClient:
    """Upload files to services/media and return a public URL."""

    @staticmethod
    async def upload(file_bytes: bytes, filename: str) -> str:
        async with httpx.AsyncClient(
            base_url=Settings.media_base_url,
            headers={"x-api-key": Settings.media_api_key or ""},
            timeout=120.0,
        ) as c:
            upload_resp = await c.post(
                "/f/upload",
                files={"file": (filename, file_bytes)},
                data={"filename": filename},
            )
            upload_resp.raise_for_status()
            file_id = upload_resp.json().get("uid")

            patch_resp = await c.patch(
                f"/f/{file_id}",
                json={"public_permission": {"permission": 10}},
            )
            patch_resp.raise_for_status()
            url: str = upload_resp.json().get("url", "")
            logging.info("Uploaded %s -> %s", filename, url)
            return url
