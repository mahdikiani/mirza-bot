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
    "cleanup": "cleanup",
    "minutes": "minutes",
    "quiz": "quiz",
}

_ACTION_FILE_PREFIXES = {
    "fa": {
        "summarize": "خلاصه",
        "structure": "جزوه",
        "format_notes": "جزوه",
        "translate": "ترجمه",
        "cleanup": "پاک‌نویس",
        "minutes": "صورت‌جلسه",
        "quiz": "آزمون",
    },
    "en": {
        "summarize": "summary",
        "structure": "note",
        "format_notes": "note",
        "translate": "translation",
        "cleanup": "cleaned",
        "minutes": "minutes",
        "quiz": "quiz",
    },
}


def action_file_name_hint(
    action_name: str, source_name: str | None, locale: str
) -> str | None:
    """Prefix an action result with its localized, meaningful operation name."""
    if not source_name:
        return None
    language = "fa" if locale.lower().startswith("fa") else "en"
    prefixes = _ACTION_FILE_PREFIXES[language]
    prefix = prefixes.get(action_name, action_name.replace("_", "-"))
    clean_source = source_name.strip()
    if clean_source.lower().endswith(".md"):
        clean_source = clean_source[:-3].rstrip(" .-")
    return f"{prefix}-{clean_source}" if clean_source else prefix


async def run_promptic_action(
    *,
    prompt_name: str,
    content: str,
    user_id: str,
    target_language: str,
    meta_data: dict,
    workspace_id: str | None = None,
) -> dict:
    """Dispatch a Promptic action asynchronously."""
    webhook_path = webhook_url_for("promptic_webhook")
    result = await PrompticClient.execute(
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
        workspace_id=workspace_id,
    )
    task_uid = str(result.get("uid") or result.get("id") or "") or None
    if task_uid:
        from apps.ai.pending_tasks import add as add_pending_task

        await add_pending_task(
            task_uid=task_uid,
            task_type="promptic",
            user_id=user_id,
            meta_data=meta_data,
        )
    return result


def map_callback_action(action: str) -> str | None:
    """Map callback action key to prompt template name."""
    return ACTION_PROMPTS.get(action)
