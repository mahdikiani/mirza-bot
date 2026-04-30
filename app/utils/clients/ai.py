"""Clients for AI-related internal services.

Covers:
- OCRClient       — services/ai  (OCR tasks)
- TranscribeClient — services/ai  (transcription tasks)
- AIChatClient    — services/ai-chat (chat sessions & messages)
- PrompticClient  — services/promptic (prompt template execution)
"""

from __future__ import annotations

from typing import Any

from server.config import Settings
from utils.clients._base import service_client


class OCRClient:
    """Submit OCR tasks to services/ai and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        async with service_client(Settings.ai_base_url) as c:
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
        async with service_client(Settings.ai_base_url) as c:
            resp = await c.get(f"/ocrs/{task_uid}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("task_status") != "completed":
                status = data.get("task_status")
                msg = f"OCR task {task_uid} not completed: {status}"
                raise ValueError(msg)
            return data.get("result") or ""


class TranscribeClient:
    """Submit transcription tasks to services/ai and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        async with service_client(Settings.ai_base_url) as c:
            resp = await c.post(
                "/transcribes",
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
        async with service_client(Settings.ai_base_url) as c:
            resp = await c.get(f"/transcribes/{task_uid}")
            resp.raise_for_status()
            data = resp.json()
            if data.get("task_status") != "completed":
                status = data.get("task_status")
                msg = f"Transcribe task {task_uid} not completed: {status}"
                raise ValueError(msg)
            return data.get("result") or ""


class AIChatClient:
    """Manage chat sessions and messages via services/ai-chat."""

    @staticmethod
    async def get_or_create_session(
        user_id: str,
        chat_id: str,
        engine_config: dict | None = None,
    ) -> dict:
        async with service_client(Settings.ai_chat_base_url) as c:
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
    async def send_message(session_id: str, content: str) -> str:
        async with service_client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                f"/sessions/{session_id}/messages",
                json={"content": content, "role": "user"},
            )
            resp.raise_for_status()
            return resp.json().get("content", "")

    @staticmethod
    async def set_context(session_id: str, context: str, context_type: str) -> None:
        async with service_client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                f"/sessions/{session_id}/context",
                json={"content": context, "context_type": context_type},
            )
            resp.raise_for_status()

    @staticmethod
    async def new_session(user_id: str, chat_id: str) -> dict:
        async with service_client(Settings.ai_chat_base_url) as c:
            resp = await c.post(
                "/sessions",
                json={"user_id": user_id, "chat_id": chat_id, "force_new": True},
            )
            resp.raise_for_status()
            return resp.json()


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
        async with service_client(Settings.promptic_base_url) as c:
            resp = await c.post("/execute", json=payload)
            resp.raise_for_status()
            return resp.json().get("result", "")

    @staticmethod
    async def render(template: str, variables: dict[str, Any]) -> str:
        async with service_client(Settings.promptic_base_url) as c:
            resp = await c.post(
                "/render", json={"template": template, "variables": variables}
            )
            resp.raise_for_status()
            return resp.json().get("result", "")
