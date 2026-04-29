"""FastAPI server configuration."""

import dataclasses
import os
from pathlib import Path

import dotenv
from fastapi_mongo_base.core import config

dotenv.load_dotenv()


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

    # Internal service base URLs
    ai_base_url: str = os.getenv("AI_BASE_URL", "https://ai.uln.me/api/ai/v1")
    ai_chat_base_url: str = os.getenv(
        "AI_CHAT_BASE_URL", "https://ai-chat.uln.me/api/ai-chat/v1"
    )
    promptic_base_url: str = os.getenv(
        "PROMPTIC_BASE_URL", "https://promptic.uln.me/api/promptic/v1"
    )
    media_base_url: str = os.getenv(
        "MEDIA_BASE_URL", "https://media.uln.me/api/media/v1"
    )
    ai_api_key: str | None = os.getenv("AI_API_KEY")
    media_api_key: str | None = os.getenv("MEDIA_API_KEY")

    # Viewer base URL for long MD results
    viewer_base_url: str = os.getenv("VIEWER_BASE_URL", "https://view.uln.me")

    # External API keys for URL content fetching
    rapidapi_key: str | None = os.getenv("RAPIDAPI_KEY")
    youtube_transcript_api_key: str | None = os.getenv("YOUTUBE_TRANSCRIPT_API_KEY")
    jina_api_key: str | None = os.getenv("JINA_API_KEY")  # optional, raises rate limit

    # Set to "1" to skip webhook registration and run all bots in polling mode.
    # Useful for local development or environments where inbound HTTPS is unavailable.
    polling_mode: bool = os.getenv("POLLING_MODE", "0") == "1"

    # Polling interval in seconds when running in full polling mode (default: 2s).
    # The Bale fallback poller always uses 60s regardless of this setting.
    polling_interval_seconds: float = float(os.getenv("POLLING_INTERVAL_SECONDS", "2"))

    @classmethod
    def get_log_config(cls, console_level: str = "INFO", **kwargs: object) -> dict:
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
