from pydantic import BaseModel


class MessengerMetaDataSchema(BaseModel):
    message_id: int | None = None
    chat_id: int | None = None
    user_id: str | None = None
    bot_name: str | None = None
