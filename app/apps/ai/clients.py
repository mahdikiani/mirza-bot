"""
AI Toolkit HTTP clients.

Verified against live OpenAPI at https://toolkit.uln.me/api/ai/v1/openapi.json
"""

from __future__ import annotations

from typing import Any

from utils.clients.toolkit import (
    ToolkitTaskNotCompletedError,
    completed_result_or_raise,
    toolkit_client,
)


class OCRClient:
    """Submit OCR tasks to AI Toolkit and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        """Submit an OCR task to AI Toolkit."""
        async with toolkit_client() as c:
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
        """Fetch the result of a completed OCR task."""
        async with toolkit_client() as c:
            resp = await c.get(f"/ocrs/{task_uid}")
            resp.raise_for_status()
            return completed_result_or_raise(resp.json(), task_uid, "OCR")


class TranscribeClient:
    """Submit transcription tasks to AI Toolkit and receive results via webhook."""

    @staticmethod
    async def submit(
        file_url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        """Submit a transcription task to AI Toolkit."""
        async with toolkit_client() as c:
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
        """Fetch the result of a completed transcription task."""
        async with toolkit_client() as c:
            resp = await c.get(f"/transcribes/{task_uid}")
            resp.raise_for_status()
            return completed_result_or_raise(resp.json(), task_uid, "Transcribe")


class YoutubeClient:
    """Submit YouTube transcript tasks."""

    @staticmethod
    async def submit(
        video_id: str,
        user_id: str,
        webhook_url: str | None = None,
        meta_data: dict | None = None,
    ) -> dict:
        """Submit a YouTube transcription task."""
        payload: dict[str, object] = {"video_id": video_id, "user_id": user_id}
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if meta_data:
            payload["meta_data"] = meta_data
        async with toolkit_client() as c:
            resp = await c.post("/youtube", json=payload)
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def get_result(task_uid: str) -> str:
        """Fetch the result of a completed YouTube task."""
        async with toolkit_client() as c:
            resp = await c.get(f"/youtube/{task_uid}")
            resp.raise_for_status()
            return completed_result_or_raise(resp.json(), task_uid, "YouTube")


class WebpageClient:
    """Submit webpage extraction tasks (webhook-based)."""

    @staticmethod
    async def submit(
        url: str,
        user_id: str,
        webhook_url: str,
        meta_data: dict | None = None,
    ) -> dict:
        """Submit a webpage extraction task."""
        async with toolkit_client() as c:
            resp = await c.post(
                "/webpages",
                json={
                    "url": url,
                    "user_id": user_id,
                    "webhook_url": webhook_url,
                    "meta_data": meta_data or {},
                },
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def get_result(task_uid: str) -> str:
        """Fetch the result of a completed webpage extraction task."""
        async with toolkit_client() as c:
            resp = await c.get(f"/webpages/{task_uid}")
            resp.raise_for_status()
            return completed_result_or_raise(resp.json(), task_uid, "Webpage")


class PrompticClient:
    """Execute named prompt templates via AI Toolkit promptic."""

    @staticmethod
    async def execute(
        prompt_name: str,
        input_variables: dict[str, object],
        webhook_url: str | None = None,
        user_id: str | None = None,
        blocking: bool = False,
        meta_data: dict[str, object] | None = None,
    ) -> dict:
        """Run a prompt template and return the task payload."""
        meta: dict[str, object] = dict(meta_data) if meta_data else {}
        if user_id:
            meta.setdefault("user_id", user_id)

        payload: dict[str, Any] = {"input_variables": input_variables}
        if webhook_url:
            payload["webhook_url"] = webhook_url
        if meta:
            payload["meta_data"] = meta

        async with toolkit_client() as c:
            resp = await c.post(
                "/promptic",
                params={
                    "prompt_name": prompt_name,
                    "blocking": str(blocking).lower(),
                    "stream": "false",
                },
                json=payload,
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def get_result(task_uid: str) -> str:
        """Fetch the result of a completed promptic task."""
        async with toolkit_client() as c:
            resp = await c.get(f"/promptic/{task_uid}")
            resp.raise_for_status()
            return completed_result_or_raise(resp.json(), task_uid, "Promptic")

    @staticmethod
    async def execute_sync(
        prompt_name: str,
        input_variables: dict[str, Any],
        user_id: str | None = None,
    ) -> str:
        """Run a prompt template synchronously and return result text."""
        data = await PrompticClient.execute(
            prompt_name=prompt_name,
            input_variables=input_variables,
            user_id=user_id,
            blocking=True,
        )
        return data.get("result") or ""


class CompletionClient:
    """Stateless OpenAI-compatible chat completions."""

    @staticmethod
    async def complete(
        messages: list[dict[str, str]],
        model: str | None = None,
    ) -> str:
        """Send messages to /chat/completions and return assistant content."""
        body: dict[str, Any] = {"messages": messages}
        if model:
            body["model"] = model

        async with toolkit_client(request_timeout=120.0) as c:
            resp = await c.post("/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") or {}
            return message.get("content") or ""


__all__ = [
    "CompletionClient",
    "OCRClient",
    "PrompticClient",
    "ToolkitTaskNotCompletedError",
    "TranscribeClient",
    "WebpageClient",
    "YoutubeClient",
    "completed_result_or_raise",
    "toolkit_client",
]
