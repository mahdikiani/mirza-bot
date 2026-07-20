"""Normalize Bale webhook payloads into shared event types."""

from __future__ import annotations

from typing import Any

from apps.bots.common.events import (
    CallbackEvent,
    FileRef,
    MessageEvent,
    MessageRef,
    Sender,
)


def _chat_type(chat: dict[str, Any]) -> str:
    if chat.get("type") == "private":
        return "private"
    if chat.get("type") in {"group", "supergroup"}:
        return str(chat["type"])
    return "private"


def _sender(payload: dict[str, Any]) -> Sender | None:
    sender = payload.get("from") or payload.get("sender") or {}
    if not sender:
        return None
    return Sender(
        id=sender.get("id", 0),
        is_bot=bool(sender.get("is_bot", False)),
        username=sender.get("username"),
        first_name=sender.get("first_name"),
        last_name=sender.get("last_name"),
        metadata={"platform_user_id": sender.get("id", 0)},
    )


def _file_from_message(payload: dict[str, Any]) -> tuple[FileRef | None, str]:
    if document := payload.get("document"):
        return (
            FileRef(
                file_id=str(document.get("file_id", "")),
                file_name=document.get("file_name") or "document.bin",
                mime_type=document.get("mime_type") or "",
                size=int(document.get("file_size") or 0),
            ),
            "document",
        )
    if voice := payload.get("voice"):
        return (
            FileRef(
                file_id=str(voice.get("file_id", "")),
                file_name="voice.ogg",
                mime_type=voice.get("mime_type") or "audio/ogg",
                size=int(voice.get("file_size") or 0),
            ),
            "voice",
        )
    if audio := payload.get("audio"):
        return (
            FileRef(
                file_id=str(audio.get("file_id", "")),
                file_name=audio.get("file_name") or "audio.mp3",
                mime_type=audio.get("mime_type") or "",
                size=int(audio.get("file_size") or 0),
            ),
            "audio",
        )
    if video := payload.get("video"):
        return (
            FileRef(
                file_id=str(video.get("file_id", "")),
                file_name=video.get("file_name") or "video.mp4",
                mime_type=video.get("mime_type") or "",
                size=int(video.get("file_size") or 0),
            ),
            "video",
        )
    if photos := payload.get("photo"):
        photo = photos[-1]
        return (
            FileRef(
                file_id=str(photo.get("file_id", "")),
                file_name="photo.jpg",
                mime_type="image/jpeg",
                size=int(photo.get("file_size") or 0),
            ),
            "photo",
        )
    return None, "text"


def normalize_bale_message(payload: dict[str, Any], bot_name: str) -> MessageEvent:
    """Normalize a Bale message payload into MessageEvent."""
    chat = payload.get("chat") or {}
    file_ref, content_type = _file_from_message(payload)
    reply_to = None
    if reply_payload := payload.get("reply_to_message"):
        reply_from = reply_payload.get("from") or {}
        reply_meta: dict[str, object] = {}
        if sender_id := reply_from.get("id"):
            reply_meta["sender_id"] = sender_id
            reply_meta["from_user_id"] = sender_id
        if reply_from.get("is_bot"):
            reply_meta["is_bot_reply"] = True
        reply_to = MessageRef(
            message_id=reply_payload.get("message_id", 0),
            chat_id=chat.get("id", 0),
            metadata=reply_meta,
        )

    return MessageEvent(
        platform="bale",
        chat_id=chat.get("id", 0),
        chat_type=_chat_type(chat),
        message_id=payload.get("message_id", 0),
        text=payload.get("text"),
        caption=payload.get("caption"),
        content_type=content_type,
        sender=_sender(payload),
        file=file_ref,
        reply_to=reply_to,
        metadata={
            "bot_name": bot_name,
            "platform": "bale",
            "language_code": (payload.get("from") or {}).get("language_code"),
        },
        raw=payload,
    )


def normalize_bale_callback(payload: dict[str, Any], bot_name: str) -> CallbackEvent:
    """Normalize a Bale callback payload into CallbackEvent."""
    message = payload.get("message") or {}
    message_text = message.get("text") or message.get("caption")
    return CallbackEvent(
        platform="bale",
        callback_id=str(payload.get("id", "")),
        chat_id=message.get("chat", {}).get("id", payload.get("chat_id", 0)),
        message_id=message.get("message_id", payload.get("message_id", 0)),
        data=str(payload.get("data", "")),
        message_text=message_text,
        sender=_sender(payload),
        metadata={"bot_name": bot_name, "platform": "bale"},
        raw=payload,
    )


def normalize_bale_contact(
    payload: dict[str, Any], bot_name: str
) -> tuple[MessageEvent, str, int | str]:
    """Return message event, phone number, and contact user id."""
    event = normalize_bale_message(payload, bot_name)
    contact = payload.get("contact") or {}
    phone = str(contact.get("phone_number") or "")
    user_id = contact.get("user_id") or (event.sender.id if event.sender else 0)
    return event, phone, user_id
