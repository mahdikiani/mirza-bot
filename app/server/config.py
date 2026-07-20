"""FastAPI server configuration."""

import dataclasses
import os
from pathlib import Path

import dotenv
from fastapi_mongo_base.core import config

# Always load from repo-root .env (parent of app/), not whatever cwd happens to be.
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
dotenv.load_dotenv(_ENV_FILE)
dotenv.load_dotenv()  # also allow cwd overrides for local/dev


@dataclasses.dataclass
class Settings(config.Settings):
    """Server config settings."""

    project_name: str = os.getenv("PROJECT_NAME", "pishrun bot")
    base_dir: Path = Path(__file__).resolve().parent.parent
    base_path: str = "/api/bot/v1"

    mongo_uri: str = os.getenv("MONGO_URI", default="mongodb://localhost:27017/")
    redis_uri: str = os.getenv("REDIS_URI", default="redis://localhost:6379/")

    usso_base_url: str = os.getenv("USSO_BASE_URL", "https://usso.uln.me")
    usso_namespace: str = os.getenv("USSO_NAMESPACE", "bot")

    coverage_dir: Path = base_dir / "htmlcov"
    currency: str = "IRR"

    # Admin API key used when calling internal services on behalf of a user
    usso_api_key: str | None = os.getenv("USSO_API_KEY")
    admin_chat_id: str | None = os.getenv("ADMIN_CHAT_ID")
    bale_admin_chat_id: str | None = os.getenv("BALE_ADMIN_CHAT_ID", "2029068767")

    # Unified AI Toolkit API. It owns AI task execution and AI usage billing.
    ai_toolkit_base_url: str = os.getenv(
        "AI_TOOLKIT_BASE_URL", "https://toolkit.uln.me/api/ai/v1"
    )
    media_base_url: str = os.getenv(
        "MEDIA_BASE_URL", "https://media.uln.me/api/media/v1"
    )
    ai_api_key: str | None = os.getenv("AI_API_KEY")
    media_api_key: str | None = os.getenv("MEDIA_API_KEY")
    shop_api_key: str | None = os.getenv("SHOP_API_KEY") or os.getenv("AI_API_KEY")
    saas_api_key: str | None = os.getenv("SAAS_API_KEY") or os.getenv("AI_API_KEY")
    webhook_api_key: str | None = (
        os.environ["WEBHOOK_API_KEY"]
        if "WEBHOOK_API_KEY" in os.environ
        else os.getenv("AI_API_KEY")
    )
    usso_user_cache_ttl_seconds: int = int(
        os.getenv("USSO_USER_CACHE_TTL_SECONDS", "600")
    )

    # Viewer base URL for long MD results
    viewer_base_url: str = os.getenv("VIEWER_BASE_URL", "https://view.uln.me")

    # Shop and SaaS service URLs
    shop_base_url: str = os.getenv("SHOP_BASE_URL", "https://shop.uln.me/api/shop/v1")
    saas_base_url: str = os.getenv("SAAS_BASE_URL", "https://saas.uln.me/api/saas/v1")

    # Telegram uses Telethon only. Bale uses telebot + getUpdates polling.
    telegram_api_id: int = int(os.getenv("TELEGRAM_API_ID", "0"))
    telegram_api_hash: str | None = os.getenv("TELEGRAM_API_HASH")

    # Sleep between Bale getUpdates cycles (each cycle uses long-poll timeout=10s).
    polling_interval_seconds: float = float(os.getenv("POLLING_INTERVAL_SECONDS", "2"))

    # Bot UX knobs (None → module defaults in apps/bots/common/*).
    products_per_page: int | None = (
        int(os.environ["PRODUCTS_PER_PAGE"]) if os.getenv("PRODUCTS_PER_PAGE") else None
    )

    @classmethod
    def get_log_config(cls, console_level: str = "INFO", **kwargs: object) -> dict:
        """Return a logging configuration dictionary for the server."""
        log_config = {
            "formatters": {
                "standard": {
                    "format": "[{levelname} {name} : {filename}:{lineno} : {asctime} -> {funcName:10}] {message}",  # noqa: E501
                    "style": "{",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "level": console_level,
                    "formatter": "standard",
                },
                "file": {
                    "class": "logging.FileHandler",
                    "level": "INFO",
                    "formatter": "standard",
                    "filename": "logs/app.log",
                },
            },
            "loggers": {
                "": {
                    "handlers": [
                        "console",
                        "file",
                    ],
                    "level": console_level,
                    "propagate": True,
                },
            },
            "version": 1,
        }
        return log_config
