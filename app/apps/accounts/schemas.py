import uuid

from fastapi_mongo_base.schemas import UserOwnedEntitySchema
from pydantic import BaseModel


class EngineConfig(BaseModel):
    model: str = "openai/gpt-4o-mini"
    personal_prompt: str | None = None
    summary_style: str = "concise"
    language: str = "fa"


class ProfileData(BaseModel):
    engine_config: EngineConfig = EngineConfig()


class Profile(UserOwnedEntitySchema):
    profile_data: ProfileData = ProfileData()


class ProfileCreate(BaseModel):
    user_id: uuid.UUID
    profile_data: ProfileData = ProfileData()
