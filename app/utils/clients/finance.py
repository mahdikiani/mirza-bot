"""
Clients for financial/commerce internal services.

Covers:
- ShopClient  — services/shop  (product listing, exclusive purchase)
- SaasClient  — services/saas  (quota / balance enquiry)
"""

from __future__ import annotations

from server.config import Settings
from utils.clients._base import service_client


class ShopClient:
    """Client for services/shop — product listing and exclusive purchase."""

    @staticmethod
    async def list_products(offset: int = 0, limit: int = 5) -> dict:
        """Return paginated product list: {items, total, offset, limit}."""
        async with service_client(Settings.shop_base_url, Settings.shop_api_key) as c:
            resp = await c.get(
                "/products",
                params={"offset": offset, "limit": limit},
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def purchase(
        product_uid: str,
        user_id: str,
        callback_url: str,
    ) -> str:
        """Create an exclusive purchase and return the redirect URL."""
        async with service_client(Settings.shop_base_url, Settings.shop_api_key) as c:
            resp = await c.post(
                "/baskets/items/purchase",
                params={"user_id": user_id, "callback_url": callback_url},
                json={"uid": product_uid, "quantity": "1"},
            )
            resp.raise_for_status()
            return resp.json().get("redirect_url", "")

    @staticmethod
    async def redeem_gift_code(code: str, redeeming_user_id: str) -> dict:
        """Redeem an admin-minted gift code for a user."""
        async with service_client(Settings.shop_base_url, Settings.shop_api_key) as c:
            resp = await c.post(
                "/rewards/gift-codes/redeem",
                json={"code": code, "redeeming_user_id": redeeming_user_id},
            )
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    async def create_gift_code(max_uses: int) -> dict:
        """Mint a new admin gift code."""
        async with service_client(Settings.shop_base_url, Settings.shop_api_key) as c:
            resp = await c.post(
                "/rewards/gift-codes",
                json={"max_uses": max_uses},
            )
            resp.raise_for_status()
            return resp.json()


class SaasClient:
    """Client for services/saas — quota enquiry."""

    @staticmethod
    async def get_quota(
        asset: str, user_id: str, workspace_id: str | None = None
    ) -> dict:
        """Return QuotasResponseSchema: {asset, quota, unit, user_id, variant}."""
        params: dict[str, str] = {"asset": asset, "user_id": user_id}
        if workspace_id:
            params["workspace_id"] = workspace_id
        async with service_client(Settings.saas_base_url, Settings.saas_api_key) as c:
            resp = await c.get("/enrollments/quotas", params=params)
            resp.raise_for_status()
            return resp.json()
