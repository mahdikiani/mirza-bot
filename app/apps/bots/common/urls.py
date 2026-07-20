"""URL message handling (webpage sync + async media links)."""

from __future__ import annotations

from apps.bots.common import context, media_flow
from apps.bots.common.events import MessageEvent
from apps.bots.common.handler_context import BotRuntimeContext, sent_message_id
from apps.bots.common.link_router import LinkKind, classify_urls_in_text
from utils.i18n import text


async def handle_urls_message(
    event: MessageEvent,
    ctx: BotRuntimeContext,
    text_value: str,
    user_id: str,
    locale: str,
) -> None:
    """
    Route links in a message.

    Pure webpage URLs → sync Jina fetch + chat completion.
    File/YouTube/Drive URLs → async toolkit tasks (webhook/poller).
    Mixed messages process async URLs first, then webpage chat if any.
    """
    classified = classify_urls_in_text(text_value)
    webpage_urls = [url for url, kind in classified if kind == LinkKind.webpage]
    async_urls = [url for url, kind in classified if kind != LinkKind.webpage]

    user_text = text_value
    for url, _ in classified:
        user_text = user_text.replace(url, "").strip()

    if webpage_urls and not async_urls:
        reading_msg = await ctx.renderer.send_text(
            event.chat_id,
            text("messages.reading_link", locale=locale),
            reply_to=event.message_id,
        )
        contents = await media_flow.fetch_webpages_parallel(webpage_urls)
        combined_parts = [part for part in [user_text, *contents] if part]
        combined = "\n\n".join(combined_parts)
        response = await context.chat_completion(
            event, combined, locale=locale, renderer=ctx.renderer
        )
        await ctx.renderer.edit_message(
            event.chat_id,
            sent_message_id(reading_msg, event.message_id),
            response[: ctx.capabilities.max_text_chars or 4096],
        )
        return

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
        )
        if not task_uid:
            await ctx.renderer.edit_message(
                event.chat_id,
                sent_message_id(processing_msg, event.message_id),
                text("messages.file_processing_error", locale=locale),
            )
    if webpage_urls:
        contents = await media_flow.fetch_webpages_parallel(webpage_urls)
        if contents:
            combined = (
                "\n\n".join([user_text, *contents])
                if user_text
                else "\n\n".join(contents)
            )
            response = await context.chat_completion(
                event, combined, locale=locale, renderer=ctx.renderer
            )
            await ctx.renderer.send_text(
                event.chat_id,
                response[: ctx.capabilities.max_text_chars or 4096],
                reply_to=event.message_id,
            )
