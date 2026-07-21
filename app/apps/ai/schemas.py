"""Webhook payload schemas for AI Toolkit task callbacks."""

from __future__ import annotations

from pydantic import BaseModel


class TaskWebhookPayload(BaseModel):
    """Payload schema for AI task webhook callbacks."""

    uid: str
    task_status: str | None = None
    meta_data: dict | None = None
    result: str | None = None
    file_url: str | None = None
    usage_amount: float | None = None
    task_report: str | None = None
    error: str | None = None
    provider_meta: dict | None = None
