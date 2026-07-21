"""Reply-chain context building and stateless chat completions."""

from __future__ import annotations

import asyncio
import logging

from apps.ai.clients import CompletionClient, InsufficientCreditsError
from apps.bots.common import models
from apps.bots.common.events import MessageEvent
from server.config import Settings

logger = logging.getLogger(__name__)


async def store_message(
    *,
    platform: str,
    platform_chat_id: str,
    platform_message_id: str,
    role: str,
    content: str,
    user_id: str,
    reply_to_platform_message_id: str | None = None,
    content_type: str = "text",
    artifact_id: str | None = None,
    meta_data: dict | None = None,
) -> models.Message:
    """Persist a message for reply-chain reconstruction."""
    msg = models.Message(
        user_id=user_id,
        platform=platform,
        platform_chat_id=str(platform_chat_id),
        platform_message_id=str(platform_message_id),
        reply_to_platform_message_id=(
            str(reply_to_platform_message_id) if reply_to_platform_message_id else None
        ),
        role=role,
        content=content,
        content_type=content_type,
        artifact_id=artifact_id,
        meta_data=meta_data,
    )
    await msg.save()
    return msg


async def get_message_by_platform_id(
    platform: str,
    platform_chat_id: str,
    platform_message_id: str,
) -> models.Message | None:
    """Look up a stored message by platform identifiers."""
    return await models.Message.find_one({
        "platform": platform,
        "platform_chat_id": str(platform_chat_id),
        "platform_message_id": str(platform_message_id),
    })


async def _message_content_with_artifact(stored: models.Message) -> str:
    content = stored.content
    if stored.artifact_id:
        try:
            artifact = await models.Artifact.get(stored.artifact_id)
            if artifact and artifact.content:
                content = (
                    f"{content}\n\n[attachment]:\n{artifact.content}"
                    if content
                    else artifact.content
                )
        except Exception:
            logger.exception("Failed to load artifact %s", stored.artifact_id)
    return content


async def build_reply_chain_messages(
    event: MessageEvent,
    current_text: str,
    renderer: object | None = None,
) -> list[dict[str, str]]:
    """Walk reply chain and build OpenAI-style messages for completions."""
    chain: list[dict[str, str]] = []
    reply_id: str | None = str(event.reply_to.message_id) if event.reply_to else None

    while reply_id:
        stored = await get_message_by_platform_id(
            event.platform,
            str(event.chat_id),
            reply_id,
        )
        content = ""
        if stored:
            content = await _message_content_with_artifact(stored)
        elif renderer and hasattr(renderer, "download_document"):
            data = await renderer.download_document(event.chat_id, int(reply_id))
            if data:
                content = data.decode("utf-8", errors="replace")
        if content:
            valid_roles = {"user", "assistant", "system"}
            role = stored.role if stored and stored.role in valid_roles else "user"
            chain.append({"role": role, "content": content})
            if stored:
                reply_id = stored.reply_to_platform_message_id
            else:
                break
        else:
            break

    chain.reverse()
    if current_text:
        chain.append({"role": "user", "content": current_text})
    return chain


def should_respond_in_group(
    event: MessageEvent,
    bot_username: str,
    bot_user_id: int | str | None,
) -> bool:
    """Group chats: only @mention or direct reply to the bot's own message."""
    if event.chat_type not in {"group", "supergroup"}:
        return True

    text_value = (event.text or event.caption or "").strip()
    if bot_username and f"@{bot_username}" in text_value:
        return True

    reply_ref = event.reply_to
    if not reply_ref:
        return False

    reply_sender_id = reply_ref.metadata.get("sender_id") or reply_ref.metadata.get(
        "from_user_id"
    )
    if bot_user_id is not None and reply_sender_id is not None:
        return str(reply_sender_id) == str(bot_user_id)

    return bool(reply_ref.metadata.get("is_bot_reply"))


async def chat_completion(
    event: MessageEvent,
    user_text: str,
    *,
    locale: str = "fa",
    renderer: object | None = None,
) -> str:
    """Run stateless chat completion using reply-chain context."""
    messages = await build_reply_chain_messages(event, user_text, renderer=renderer)
    if not messages:
        messages = [{"role": "user", "content": user_text}]
    model = None
    sender_id = str(event.sender.id) if event.sender else None
    if sender_id:
        from apps.bots.common.settings import get_user_model

        model = await get_user_model(sender_id)
    try:
        return await CompletionClient.complete(messages, model=model)
    except InsufficientCreditsError:
        raise
    except Exception:
        logger.exception("Completion error")
        from utils.i18n import text as t

        return t("messages.ai_error", locale=locale)


async def extracted_content_completion(
    content: str,
    prompt: str,
    *,
    sender_id: int | str | None = None,
    locale: str = "fa",
) -> str:
    """Answer a prompt after the referenced attachment has been extracted."""
    model = None
    if sender_id:
        from apps.bots.common.settings import get_user_model

        model = await get_user_model(str(sender_id))
    message = f"[محتوای استخراج‌شده]\n{content}\n\n[درخواست کاربر]\n{prompt}"
    try:
        return await CompletionClient.complete(
            [{"role": "user", "content": message}], model
        )
    except InsufficientCreditsError:
        raise
    except Exception:
        logger.exception("Extracted-content completion error")
        from utils.i18n import text as t

        return t("messages.ai_error", locale=locale)


async def notify_admin_insufficient_credits(
    renderer: object, chat_id: int | str
) -> None:
    """Notify the configured admin about exhausted OpenRouter credits."""
    admin_id = Settings.admin_chat_id
    if not admin_id:
        return
    if isinstance(admin_id, str) and admin_id.isdecimal():
        admin_id = int(admin_id)
    if str(admin_id) == str(chat_id):
        return
    try:
        await asyncio.wait_for(
            renderer.send_text(  # type: ignore[union-attr]
                admin_id,
                "⚠️ اعتبار OpenRouter تمام شده است. لطفاً حساب را شارژ کنید.",
            ),
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to notify admin about insufficient credits")
