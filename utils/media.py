from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from io import BytesIO

import httpx

from server.config import Settings


@asynccontextmanager
async def get_media_client() -> AsyncGenerator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url="https://media.uln.me/api/media/v1/",
        headers={"x-api-key": Settings.media_api_key or ""},
    ) as client:
        yield client


async def upload_file(file: BytesIO, file_name: str | None = None) -> str:
    async with get_media_client() as media_client:
        upload_response = await media_client.post(
            "/f/upload",
            files={"file": file},
            data={"filename": file_name or file.name},
        )
        upload_response.raise_for_status()
        file_id = upload_response.json().get("uid")

        response = await media_client.patch(
            f"/f/{file_id}", json={"public_permission": {"permission": 10}}
        )
        response.raise_for_status()
        return upload_response.json().get("url")
