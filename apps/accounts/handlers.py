from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from aiocache import cached
from usso import UserData
from usso.client import AsyncUssoClient

from apps.accounts.schemas import Profile
from server.config import Settings


@asynccontextmanager
async def get_usso_client() -> AsyncGenerator[AsyncUssoClient]:
    async with AsyncUssoClient(
        usso_base_url=Settings.usso_base_url, api_key=Settings.usso_api_key
    ) as client:
        yield client


@cached(ttl=60 * 60)
async def get_usso_user(credentials: dict) -> UserData:
    async with get_usso_client() as client:
        u = await client.get_users(params=credentials)
        if u:
            return u[0]
        return await client.create_users(data=credentials)


@cached(ttl=60 * 5)
async def get_user_profile(user_id: str, **kwargs: object) -> Profile:
    async with get_usso_client() as client:
        response = await client.get(f"/api/sso/v1/profiles/{user_id}", timeout=20)
        response.raise_for_status()
        return Profile(**response.json())
