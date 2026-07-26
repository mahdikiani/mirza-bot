"""Normalize Telethon events into shared bot event types."""


from __future__ import annotations

import logging

from apps.bots.common.events import (
    CallbackEvent,
    FileRef,
    MessageEvent,
    MessageRef,
    Sender,
)

logger = logging.getLogger(__name__)


def telethon_chat_type(chat: object | None) -> str:
    """
    Map a Telethon chat entity to private | group | supergroup.

    Basic ``Chat`` groups have a title but no megagroup/broadcast flags;
    those must not be mislabeled as private (which bypasses group gating).
    """
    if chat is None:
        return "private"
    if getattr(chat, "megagroup", False):
        return "supergroup"
    if getattr(chat, "broadcast", False):
        return "group"
    if getattr(chat, "title", None):
        return "group"
    return "private"


async def _resolve_reply_message(event: object) -> object | None:
    """Load the replied-to Telethon message, if available."""
    get_reply = getattr(event, "get_reply_message", None)
    if not callable(get_reply):
        return None
    try:
        return await get_reply()
    except Exception:
        logger.debug("Failed to load reply message for group gating", exc_info=True)
        return None


async def _resolve_reply_sender(reply_msg: object) -> object | None:
    """Resolve sender entity for a replied-to message."""
    reply_sender = getattr(reply_msg, "sender", None)
    if reply_sender is not None:
        return reply_sender
    get_sender = getattr(reply_msg, "get_sender", None)
    if not callable(get_sender):
        return None
    try:
        return await get_sender()
    except Exception:
        logger.debug("Failed to resolve reply sender", exc_info=True)
        return None


def _apply_reply_sender_meta(
    meta: dict,
    *,
    sender_id: int | str | None,
    reply_sender: object | None,
    bot_user_id: int | str | None,
) -> None:
    """Write sender ids and is_bot_reply into reply metadata."""
    if sender_id is not None:
        meta["sender_id"] = sender_id
        meta["from_user_id"] = sender_id
        if bot_user_id is not None:
            meta["is_bot_reply"] = str(sender_id) == str(bot_user_id)
        else:
            meta["is_bot_reply"] = bool(getattr(reply_sender, "bot", False))
        return
    if reply_sender is not None:
        meta["is_bot_reply"] = bool(getattr(reply_sender, "bot", False))


async def enrich_reply_metadata(
    event: object,
    message_event: MessageEvent,
    bot_user_id: int | str | None,
) -> None:
    """
    Fill reply sender ids / is_bot_reply from the replied-to message.

    Aligns Telegram with Bale's normalizer so ``should_respond_in_group``
    only treats replies to the bot as actionable.
    """
    if not message_event.reply_to:
        return
    reply_msg = await _resolve_reply_message(event)
    if reply_msg is None:
        return

    sender_id: int | str | None = getattr(reply_msg, "sender_id", None)
    reply_sender = await _resolve_reply_sender(reply_msg)
    if reply_sender is not None:
        sender_id = getattr(reply_sender, "id", sender_id)

    _apply_reply_sender_meta(
        message_event.reply_to.metadata,
        sender_id=sender_id,
        reply_sender=reply_sender,
        bot_user_id=bot_user_id,
    )


def _telethon_file_content(
    msg: object,
) -> tuple[str, str, str]:
    """Infer content_type, file_name, and mime from a Telethon message."""
    media = getattr(msg, "media", None)
    file_name = getattr(msg.file, "name", "") or ""
    mime = getattr(msg.file, "mime_type", "") or ""

    if getattr(msg, "voice", None) is not None:
        return "voice", file_name or "voice.ogg", mime
    if getattr(msg, "audio", None) is not None:
        return "audio", file_name or "audio.mp3", mime
    if getattr(msg, "video", None) is not None:
        return "video", file_name or "video.mp4", mime
    if getattr(msg, "video_note", None) is not None:
        return "video", "video_note.mp4", mime
    if getattr(msg, "photo", None) is not None:
        return "photo", file_name or "photo.jpg", mime or "image/jpeg"
    if getattr(msg, "sticker", None) is not None:
        return "sticker", file_name or "sticker.webp", mime
    if getattr(media, "document", None) is not None:
        return "document", file_name, mime
    return "document", file_name, mime


def _build_telethon_file_ref(msg: object, chat: object | None) -> FileRef:
    """Build FileRef metadata for an inbound Telethon media message."""
    content_type, file_name, mime = _telethon_file_content(msg)
    return FileRef(
        file_id=str(getattr(msg.file, "id", "")),
        file_name=file_name,
        mime_type=mime,
        size=getattr(msg.file, "size", 0) or 0,
        metadata={
            "platform": "telegram",
            "telegram_chat_id": getattr(chat, "id", 0) if chat else 0,
            "telegram_message_id": getattr(msg, "id", 0),
            "content_type": content_type,
        },
    )


def _build_telethon_sender(
    msg: object | None, event: object
) -> tuple[Sender | None, str]:
    """Build Sender and content_type defaults for a Telethon message."""
    content_type = "text"
    sender = None
    if msg and getattr(msg, "sender", None):
        sender_obj = msg.sender
        sender = Sender(
            id=getattr(sender_obj, "id", 0),
            is_bot=bool(getattr(sender_obj, "bot", False)),
            username=getattr(sender_obj, "username", None),
            first_name=getattr(sender_obj, "first_name", None),
            last_name=getattr(sender_obj, "last_name", None),
            metadata={
                "platform_user_id": getattr(sender_obj, "id", 0),
                "telegram_user_id": getattr(sender_obj, "id", 0),
            },
        )
    if sender is None and getattr(event, "sender_id", None):
        sender = Sender(
            id=event.sender_id,
            metadata={
                "platform_user_id": event.sender_id,
                "telegram_user_id": event.sender_id,
            },
        )
    return sender, content_type


def _build_telethon_reply_to(
    msg: object | None, chat: object | None
) -> MessageRef | None:
    """Build MessageRef for reply_to_msg_id when present."""
    reply_to_msg_id = getattr(msg, "reply_to_msg_id", None) if msg else None
    if not reply_to_msg_id:
        return None
    return MessageRef(
        message_id=reply_to_msg_id,
        chat_id=getattr(chat, "id", 0) if chat else 0,
        metadata={
            "telegram_chat_id": getattr(chat, "id", 0) if chat else 0,
            "telegram_message_id": reply_to_msg_id,
        },
    )


def normalize_telethon_message(event: object, bot_name: str) -> MessageEvent:
    """Normalize a Telethon NewMessage-like object into MessageEvent."""
    from telethon import events as telethon_events

    if not isinstance(event, telethon_events.NewMessage) and not hasattr(
        event, "message"
    ):
        return MessageEvent(platform="telegram")

    msg = event.message
    chat = event.chat
    chat_type = telethon_chat_type(chat)

    file_ref = None
    content_type = "text"
    if msg and msg.file:
        file_ref = _build_telethon_file_ref(msg, chat)
        content_type = file_ref.metadata.get("content_type", "document")

    sender, _ = _build_telethon_sender(msg, event)
    reply_to = _build_telethon_reply_to(msg, chat)

    chat_id = getattr(chat, "id", 0) if chat else getattr(event, "chat_id", 0)
    message_id = getattr(msg, "id", 0) if msg else getattr(event, "id", 0)

    return MessageEvent(
        platform="telegram",
        chat_id=chat_id,
        chat_type=chat_type,  # type: ignore[arg-type]
        message_id=message_id,
        text=getattr(msg, "text", None) if msg else None,
        content_type=content_type,  # type: ignore[arg-type]
        sender=sender,
        file=file_ref,
        reply_to=reply_to,
        metadata={
            "platform": "telegram",
            "chat_id": chat_id,
            "chat_type": chat_type,
            "message_id": message_id,
            "telegram_chat_id": chat_id,
            "telegram_message_id": message_id,
            "bot_name": bot_name,
        },
        raw=event,
    )


def normalize_telethon_callback(event: object, bot_name: str) -> CallbackEvent:
    """Normalize a Telethon CallbackQuery-like object into CallbackEvent."""
    from telethon import events as telethon_events

    if not isinstance(event, telethon_events.CallbackQuery) and not hasattr(
        event, "data"
    ):
        return CallbackEvent(platform="telegram")

    callback_id = getattr(event, "id", "")
    chat_id = getattr(event, "chat_id", 0)
    message_id = getattr(event, "message_id", 0)
    data = getattr(event, "data", b"")
    message_text = None
    if hasattr(event, "message") and event.message:
        message_text = getattr(event.message, "message", None) or getattr(
            event.message, "text", None
        )

    sender = None
    sender_id = getattr(event, "sender_id", None)
    if sender_id:
        sender = Sender(
            id=sender_id,
            metadata={
                "platform_user_id": sender_id,
                "telegram_user_id": sender_id,
            },
        )

    return CallbackEvent(
        platform="telegram",
        callback_id=str(callback_id),
        chat_id=chat_id,
        message_id=message_id,
        data=data.decode() if data else "",
        message_text=message_text,
        sender=sender,
        metadata={
            "platform": "telegram",
            "chat_id": chat_id,
            "message_id": message_id,
            "telegram_callback_id": callback_id,
            "telegram_chat_id": chat_id,
            "telegram_message_id": message_id,
            "bot_name": bot_name,
        },
        raw=event,
    )
