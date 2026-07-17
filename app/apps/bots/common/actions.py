"""Promptic inline action buttons."""

from __future__ import annotations

import logging

from apps.ai.clients import PrompticClient
from apps.bots.common.media_flow import webhook_url_for

logger = logging.getLogger(__name__)

ACTION_PROMPTS = {
    "summarize": "summarize",
    "structure": "structure",
    "translate": "translate",
    "format_notes": "format_notes",
}


async def run_promptic_action(
    *,
    prompt_name: str,
    content: str,
    user_id: str,
    target_language: str,
    meta_data: dict,
) -> dict:
    """Dispatch a Promptic action asynchronously."""
    webhook_path = webhook_url_for("promptic_webhook")
    return await PrompticClient.execute(
        prompt_name=prompt_name,
        input_variables={
            "content": content,
            "language": target_language,
            "target_language": target_language,
        },
        webhook_url=webhook_path,
        user_id=user_id,
        blocking=False,
        meta_data=meta_data,
    )


def map_callback_action(action: str) -> str | None:
    """Map callback action key to prompt template name."""
    return ACTION_PROMPTS.get(action)
