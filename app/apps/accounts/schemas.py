"""Pydantic schemas for user profiles and engine configuration."""

import uuid

from fastapi_mongo_base.schemas import UserOwnedEntitySchema
from pydantic import BaseModel


class EngineConfig(BaseModel):
    """AI engine configuration including model and language preferences."""

    model: str = "openai/gpt-4o-mini"
    personal_prompt: str | None = None
    summary_style: str = "concise"
    language: str = "fa"


class ProfileData(BaseModel):
    """User profile data containing engine configuration."""

    engine_config: EngineConfig = EngineConfig()


class Profile(UserOwnedEntitySchema):
    """User profile document stored in the database."""

    profile_data: ProfileData = ProfileData()


class ProfileCreate(BaseModel):
    """Schema for creating a new user profile."""

    user_id: uuid.UUID
    profile_data: ProfileData = ProfileData()
