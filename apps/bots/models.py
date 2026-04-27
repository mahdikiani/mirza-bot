from fastapi_mongo_base.models import UserOwnedEntity


class Message(UserOwnedEntity):
    content: str = ""
    content_type: str = "text"  # text | voice | ocr | chat | video
    source_chat_id: str | None = None  # group chat id that produced this message
    meta_data: dict | None = None  # bot_name, message_id, session_id, etc.
