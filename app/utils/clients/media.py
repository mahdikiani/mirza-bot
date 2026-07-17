"""Client for the internal media service (file upload & public URL)."""

from __future__ import annotations

import logging

import httpx

from server.config import Settings


class MediaClient:
    """Upload files to services/media and return a public URL."""

    @staticmethod
    async def upload(file_bytes: bytes, filename: str) -> str:
        """
        Upload *file_bytes* and make it publicly accessible.

        Returns the public URL of the uploaded file.
        Raises ValueError if no URL is returned by the service.
        """
        async with httpx.AsyncClient(
            base_url=Settings.media_base_url,
            headers={"x-api-key": Settings.media_api_key or ""},
            timeout=120.0,
        ) as c:
            upload_resp = await c.post(
                "/f/upload",
                files={"file": (filename, file_bytes)},
                data={"filename": filename},
            )
            upload_resp.raise_for_status()
            file_id = upload_resp.json().get("uid")

            patch_resp = await c.patch(
                f"/f/{file_id}",
                json={"public_permission": {"permission": 10}},
            )
            patch_resp.raise_for_status()

            # Prefer URL from patch response (Req 16.1)
            url: str = patch_resp.json().get("url") or upload_resp.json().get("url", "")
            if not patch_resp.json().get("url"):
                logging.warning(
                    "patch_resp missing url field for %s, falling back to upload_resp",
                    filename,
                )
            if not url:
                raise ValueError(
                    f"MediaClient.upload: no URL returned for file {filename}"
                )
            logging.info("Uploaded %s -> %s", filename, url)
            return url
