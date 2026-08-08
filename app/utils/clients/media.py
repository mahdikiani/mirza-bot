"""Client for the internal media service (file upload & public URL)."""

from __future__ import annotations

import logging

import httpx

from server.config import Settings


class MediaClient:
    """Upload owned files and obtain temporary URLs from Media service."""

    @staticmethod
    async def upload(
        file_bytes: bytes,
        filename: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> str:
        """
        Upload *file_bytes* privately and request temporary signed access.

        Without user_id, the media service attributes every upload to
        mirza-bot's own shared API key instead of the actual Telegram
        user uploading -- no user/workspace ever owns the file.

        Returns the public URL of the uploaded file.
        Raises ValueError if no URL is returned by the service.
        """
        if not user_id:
            raise ValueError("MediaClient.upload requires an owner user_id")

        url, _file_id = await MediaClient.upload_with_id(
            file_bytes, filename, user_id=user_id, workspace_id=workspace_id
        )
        return url

    @staticmethod
    async def upload_with_id(
        file_bytes: bytes,
        filename: str,
        user_id: str | None = None,
        workspace_id: str | None = None,
    ) -> tuple[str, str]:
        """Upload a file and return its signed URL plus stable media UID."""
        if not user_id:
            raise ValueError("MediaClient.upload requires an owner user_id")
        async with httpx.AsyncClient(
            base_url=Settings.media_base_url,
            headers={"x-api-key": Settings.media_api_key or ""},
            timeout=120.0,
        ) as c:
            data = {"filename": filename}
            data["user_id"] = user_id
            if workspace_id:
                data["workspace_id"] = workspace_id
            upload_resp = await c.post(
                "/f/upload",
                files={"file": (filename, file_bytes)},
                data=data,
            )
            upload_resp.raise_for_status()
            file_id = upload_resp.json().get("uid")
            if not file_id:
                raise ValueError(
                    f"MediaClient.upload: no file uid returned for {filename}"
                )

            signed_resp = await c.get(
                f"/f/{file_id}",
                params={"signed_url": True},
            )
            if not signed_resp.is_redirect:
                signed_resp.raise_for_status()
            url: str = signed_resp.headers.get("location", "")
            if not url:
                raise ValueError(
                    f"MediaClient.upload: no signed URL returned for file {filename}"
                )
            logging.info("Uploaded owned media file %s", filename)
            return url, str(file_id)

    @staticmethod
    async def signed_url(file_id: str) -> str:
        """Generate a fresh temporary URL for an existing media file."""
        async with httpx.AsyncClient(
            base_url=Settings.media_base_url,
            headers={"x-api-key": Settings.media_api_key or ""},
            timeout=30.0,
        ) as c:
            response = await c.get(f"/f/{file_id}", params={"signed_url": True})
            if not response.is_redirect:
                response.raise_for_status()
            url = response.headers.get("location", "")
            if not url:
                raise ValueError("MediaClient.signed_url: no signed URL returned")
            return url
