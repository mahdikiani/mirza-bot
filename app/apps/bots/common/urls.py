"""URL message handling (webpage sync + async media links)."""


from __future__ import annotations

from apps.ai.clients import InsufficientCreditsError
from apps.bots.common import context, media_flow
from apps.bots.common.delivery import deliver_md_result
from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext, sent_message_id
from apps.bots.common.link_router import LinkKind, classify_urls_in_text
from utils.i18n import text


async def _reply_webpage_completion(
    *,
    event: MessageEvent,
    ctx: BotRuntimeContext,
    combined: str,
    user_text: str,
    user_id: str,
    locale: str,
    edit_message_id: int | str | None,
) -> None:
    """Complete against fetched page text, or deliver Markdown when no prompt."""
    if user_text:
        try:
            response = await context.extracted_content_completion(
                combined,
                user_text,
                sender_id=event.sender.id if event.sender else None,
                locale=locale,
            )
        except InsufficientCreditsError:
            await context.notify_admin_insufficient_credits(
                ctx.renderer, event.chat_id
            )
            response = text("messages.insufficient_credits", locale=locale)
        body = response[: ctx.capabilities.max_text_chars or 4096]
        if edit_message_id is not None:
            await ctx.renderer.edit_message(event.chat_id, edit_message_id, body)
        else:
            await ctx.renderer.send_text(
                event.chat_id, body, reply_to=event.message_id
            )
        return

    await deliver_md_result(
        ctx.renderer,
        chat_id=event.chat_id,
        message_id=edit_message_id if edit_message_id is not None else event.message_id,
        result=combined,
        content_type="url",
        user_id=user_id,
        locale=locale,
    )


async def _handle_webpage_only(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    webpage_urls: list[str],
    user_text: str,
    user_id: str,
    locale: str,
) -> None:
    """Sync-fetch webpages and reply (edit the reading placeholder)."""
    reading_msg = await ctx.renderer.send_text(
        event.chat_id,
        text("messages.reading_link", locale=locale),
        reply_to=event.message_id,
    )
    contents = await media_flow.fetch_webpages_parallel(webpage_urls)
    combined = "\n\n".join(contents)
    msg_id = sent_message_id(reading_msg, event.message_id)
    await _reply_webpage_completion(
        event=event,
        ctx=ctx,
        combined=combined,
        user_text=user_text,
        user_id=user_id,
        locale=locale,
        edit_message_id=msg_id,
    )


async def _submit_async_urls(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    async_urls: list[str],
    user_text: str,
    user_id: str,
    locale: str,
) -> None:
    """Enqueue file/YouTube toolkit tasks for each async URL."""
    for url in async_urls:
        processing_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.processing", locale=locale),
            reply_to=event.message_id,
        )
        task_uid = await media_flow.submit_url(
            event=event,
            bot_name=ctx.bot_name,
            url=url,
            response_message_id=sent_message_id(processing_msg, event.message_id),
            user_id=user_id,
            locale=locale,
            user_prompt=user_text or None,
        )
        if task_uid:
            continue
        err_key = (
            "messages.youtube_link_error"
            if "youtube.com" in url.lower() or "youtu.be" in url.lower()
            else "messages.file_processing_error"
        )
        await ctx.renderer.edit_message(
            event.chat_id,
            sent_message_id(processing_msg, event.message_id),
            text(err_key, locale=locale),
        )


async def handle_urls_message(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    text_value: str,
    user_id: str,
    locale: str,
) -> None:
    """
    Route links in a message.

    Pure webpage URLs → sync Jina fetch + chat completion (canonical path).
    File/YouTube URLs → async toolkit tasks (webhook/poller).
    Google Drive → fail-fast with a clear user message (no fake OCR import).
    Mixed messages process async URLs first, then webpage chat if any.
    """
    classified = classify_urls_in_text(text_value)
    webpage_urls = [url for url, kind in classified if kind == LinkKind.webpage]
    gdrive_urls = [url for url, kind in classified if kind == LinkKind.gdrive]
    async_urls = [
        url
        for url, kind in classified
        if kind not in {LinkKind.webpage, LinkKind.gdrive}
    ]

    user_text = text_value
    for url, _ in classified:
        user_text = user_text.replace(url, "").strip()

    for _url in gdrive_urls:
        await ctx.renderer.send_text(
            event.chat_id,
            text("messages.gdrive_unsupported", locale=locale),
            reply_to=event.message_id,
        )

    if webpage_urls and not async_urls and not gdrive_urls:
        await _handle_webpage_only(
            event, ctx, webpage_urls, user_text, user_id, locale
        )
        return

    await _submit_async_urls(event, ctx, async_urls, user_text, user_id, locale)

    if not webpage_urls:
        return
    contents = await media_flow.fetch_webpages_parallel(webpage_urls)
    if not contents:
        return
    combined = "\n\n".join(contents)
    await _reply_webpage_completion(
        event=event,
        ctx=ctx,
        combined=combined,
        user_text=user_text,
        user_id=user_id,
        locale=locale,
        edit_message_id=None,
    )
