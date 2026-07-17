"""Billing UI helpers (balance, packages, purchase)."""

from __future__ import annotations

from utils.clients.finance import SaasClient, ShopClient
from utils.i18n import text

# Module default; override via Settings / env ``PRODUCTS_PER_PAGE``.
DEFAULT_PRODUCTS_PER_PAGE = 10


def products_per_page() -> int:
    """Page size for product listing (Settings override when set)."""
    from server.config import Settings

    if Settings.products_per_page is not None:
        return Settings.products_per_page
    return DEFAULT_PRODUCTS_PER_PAGE


async def fetch_balance(user_id: str, locale: str = "fa") -> str:
    """Return formatted balance message."""
    try:
        data = await SaasClient.get_quota("coin", user_id)
        quota = data.get("quota", 0)
        unit = data.get("unit") or text("labels.coin_unit", locale=locale)
        return text("messages.balance", locale=locale, quota=quota, unit=unit)
    except Exception:
        return text("messages.account_error", locale=locale)


async def fetch_products_page(
    locale: str = "fa", page: int = 0
) -> tuple[str, list[dict], int]:
    """Return products message, items, and total count."""
    page_size = products_per_page()
    try:
        data = await ShopClient.list_products(offset=page * page_size, limit=page_size)
        products = data.get("items") or []
        total = int(data.get("total") or len(products))
    except Exception:
        return text("messages.products_error", locale=locale), [], 0

    if not products:
        return text("messages.no_products", locale=locale), [], 0

    msg = text("messages.products_page", locale=locale, page=page + 1)
    return msg, products, total


async def purchase_product(
    product_uid: str,
    user_id: str,
    return_url: str,
) -> str:
    """Create a purchase and return the payment redirect URL."""
    return await ShopClient.purchase(product_uid, user_id, return_url)
