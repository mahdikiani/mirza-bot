"""
Internal service clients — HTTP infra re-exports.

Domain AI clients: ``apps.ai.clients``.
USSO: ``apps.accounts.clients``.
"""

from utils.clients.finance import SaasClient, ShopClient
from utils.clients.media import MediaClient

__all__ = [
    "MediaClient",
    "SaasClient",
    "ShopClient",
]
