"""File attachment handling for bot messages."""

from __future__ import annotations

from apps.bots.common import context, media_flow
from apps.bots.common import keyboards as kb
from apps.bots.common.docx import extract_docx_text
from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext
from utils.i18n import text


async def handle_file_event(
    *,
    event: MessageEvent,
    ctx: BotRuntimeContext,
    user_id: str,
    locale: str,
    response_message_id: int | str,
    user_prompt: str | None = None,
) -> None:
    """Process an attached file (text ingest or async OCR/transcribe)."""
    if not event.file:
        return

    file_name = event.file.file_name or "file.bin"
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    text_exts = {"txt", "md", "markdown"}

    if ext in text_exts or ext == "docx":
        downloaded = await ctx.renderer.download_attached_file(event)
        if downloaded:
            if ext == "docx":
                content = extract_docx_text(downloaded[0])
            else:
                content = downloaded[0].decode("utf-8", errors="replace")
            await context.store_message(
                platform=event.platform,
                platform_chat_id=str(event.chat_id),
                platform_message_id=str(event.message_id),
                role="user",
                content=content,
                user_id=user_id,
                content_type="document",
            )
            if user_prompt:
                response = await context.extracted_content_completion(
                    content,
                    user_prompt,
                    sender_id=event.sender.id if event.sender else None,
                    locale=locale,
                )
                await ctx.renderer.send_text(
                    event.chat_id,
                    response,
                    reply_to=event.message_id,
                )
            else:
                await ctx.renderer.send_text(
                    event.chat_id,
                    text("messages.content_added_to_chat", locale=locale),
                    reply_to=event.message_id,
                    reply_keyboard=kb.main_menu_keyboard(),
                )
        return

    downloaded = await ctx.renderer.download_attached_file(event)
    if not downloaded:
        raise RuntimeError("Could not download attached file")

    file_bytes, resolved_name = downloaded
    task_uid = await media_flow.submit_file_bytes(
        event=event,
        bot_name=ctx.bot_name,
        file_bytes=file_bytes,
        file_name=resolved_name or file_name,
        response_message_id=response_message_id,
        content_type=event.content_type,
        user_id=user_id,
        locale=locale,
        user_prompt=user_prompt,
    )
    if not task_uid:
        raise RuntimeError("AI Toolkit did not return a task identifier")
