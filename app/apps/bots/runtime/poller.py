"""Bale polling worker (telebot)."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def _supports_polling(bot: object) -> bool:
    return all(
        hasattr(bot, attr)
        for attr in ("get_updates", "process_new_updates", "last_update_id", "me")
    )


async def _fetch_updates(bot: object) -> list | None:
    try:
        offset: int | None = bot.last_update_id + 1 if bot.last_update_id is not None else 0
        return await bot.get_updates(
            offset=offset,
            timeout=10,
            limit=100,
        )
    except Exception:
        logger.exception("Polling: failed to get updates for %s", bot.me)
        return None


def _advance_last_update_id(bot: object, updates: list) -> None:
    for update in updates:
        update_id = getattr(update, "update_id", 0)
        if update_id > (bot.last_update_id or 0):
            bot.last_update_id = update_id


def _update_to_payload(update: object) -> dict:
    payload: dict = {}
    msg = getattr(update, "message", None)
    if msg:
        payload["message"] = _msg_to_dict(msg)
    cb = getattr(update, "callback_query", None)
    if cb:
        payload["callback_query"] = _cb_to_dict(cb)
    return payload


async def _process_updates(bot: object, updates: list) -> None:
    from apps.bots.bale.handler import handle_bale_update

    for update in updates:
        try:
            payload = _update_to_payload(update)
            if payload:
                await handle_bale_update(payload, getattr(bot, "me", ""))
        except Exception:
            logger.exception("Bale: failed to process update")


async def _poll_once(bot: object) -> None:
    if not _supports_polling(bot):
        return

    updates = await _fetch_updates(bot)
    if not updates:
        return

    await _process_updates(bot, updates)
    _advance_last_update_id(bot, updates)


def _optional_attr(d: dict, msg: object, key: str, attr: str | None = None) -> None:
    value = getattr(msg, attr or key, None)
    if value:
        d[key] = value


def _chat_dict(chat: object) -> dict:
    return {
        "id": getattr(chat, "id", 0),
        "type": getattr(chat, "type", "private"),
    }


def _contact_dict(contact: object) -> dict:
    return {
        "phone_number": getattr(contact, "phone_number", ""),
        "user_id": getattr(contact, "user_id", 0),
    }


def _media_dict(media: object, ftype: str) -> dict:
    entry = {
        "file_id": getattr(media, "file_id", ""),
        "file_size": getattr(media, "file_size", 0),
    }
    # file_name/mime_type matter beyond documents: Bale sends audio files
    # sent as a generic attachment (not a voice note) through the same
    # "document" field, and normalize_bale_message relies on these to
    # detect audio/* content and route to transcription instead of OCR.
    file_name = getattr(media, "file_name", None)
    if file_name:
        entry["file_name"] = file_name
    mime_type = getattr(media, "mime_type", None)
    if mime_type:
        entry["mime_type"] = mime_type
    if ftype in ("voice", "audio", "video") and hasattr(media, "duration"):
        entry["duration"] = getattr(media, "duration", 0)
    if ftype == "video" and hasattr(media, "width"):
        entry.update({
            "width": getattr(media, "width", 0),
            "height": getattr(media, "height", 0),
        })
    return entry


def _attach_media(d: dict, msg: object) -> None:
    for ftype in ("voice", "audio", "video", "document", "sticker", "animation"):
        media = getattr(msg, ftype, None)
        if media:
            d[ftype] = _media_dict(media, ftype)
            return
    photo = getattr(msg, "photo", None)
    if photo:
        d["photo"] = [
            {
                "file_id": getattr(p, "file_id", ""),
                "file_size": getattr(p, "file_size", 0),
            }
            for p in photo
        ]


def _msg_to_dict(msg: object) -> dict:
    d: dict = {
        "message_id": getattr(msg, "message_id", 0),
        "date": getattr(msg, "date", 0),
    }
    chat = getattr(msg, "chat", None)
    if chat:
        d["chat"] = _chat_dict(chat)
    from_user = getattr(msg, "from_user", None)
    if from_user:
        d["from"] = {"id": getattr(from_user, "id", 0)}
    _optional_attr(d, msg, "text")
    _optional_attr(d, msg, "caption")
    contact = getattr(msg, "contact", None)
    if contact:
        d["contact"] = _contact_dict(contact)
    _attach_media(d, msg)
    reply_to = getattr(msg, "reply_to_message", None)
    if reply_to:
        reply_dict: dict = {"message_id": getattr(reply_to, "message_id", 0)}
        reply_from = getattr(reply_to, "from_user", None)
        if reply_from:
            reply_dict["from"] = {
                "id": getattr(reply_from, "id", 0),
                "is_bot": getattr(reply_from, "is_bot", False),
            }
        d["reply_to_message"] = reply_dict
    return d


def _cb_to_dict(cb: object) -> dict:
    msg = getattr(cb, "message", None)
    return {
        "id": getattr(cb, "id", ""),
        "data": getattr(cb, "data", ""),
        "from": {"id": getattr(getattr(cb, "from_user", None), "id", 0)},
        "message": {
            "message_id": getattr(msg, "message_id", 0),
            "chat": {"id": getattr(getattr(msg, "chat", None), "id", 0)},
            "text": getattr(msg, "text", ""),
        } if msg else {},
        "chat_id": getattr(getattr(getattr(cb, "message", None), "chat", None), "id", getattr(cb, "chat_id", 0)),
        "message_id": getattr(getattr(cb, "message", None), "message_id", 0),
    }


def _bale_bots() -> list[object]:
    from apps.bots.bale.bot import BaleBot
    from apps.bots.runtime import registry

    bots: list[object] = []
    for bot in registry.all_bots():
        if getattr(bot, "bot_type", None) == "bale":
            if isinstance(bot, BaleBot) and not BaleBot.is_configured():
                continue
            bots.append(bot)
    if not bots and BaleBot.is_configured():
        bots.append(BaleBot())
    return bots


async def _polling_loop(interval: float) -> None:
    logger.info(
        "Bale polling started (interval=%.1fs, long-poll timeout=10s)", interval
    )
    heartbeat_interval = max(300, interval * 10)
    total_slept = 0.0
    while True:
        for bot in _bale_bots():
            try:
                await _poll_once(bot)
            except Exception:
                logger.exception("Bale polling: error for %s", bot)

        total_slept += interval
        if total_slept >= heartbeat_interval:
            first = next(iter(_bale_bots()), None)
            uid = getattr(first, "last_update_id", None) if first else None
            logger.info("Polling heartbeat (%.0fs): updates_consumed=%s", heartbeat_interval, uid)
            total_slept = 0.0

        await asyncio.sleep(interval)


def start_bale_polling(interval: float = 2.0) -> asyncio.Task:
    """Start the background Bale long-polling loop."""
    return asyncio.create_task(_polling_loop(interval), name="bale-poller")
