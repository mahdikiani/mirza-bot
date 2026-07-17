🛠️ Engineering & Implementation Guide -- AI Toolkit Bot
=======================================================

> **Context:** This document outlines the technical architecture, coding standards, and implementation roadmap for the AI Toolkit Bot. The backend relies on a hybrid **FastAPI (for HTTP Webhooks) + Telethon (for MTProto)** architecture, driven entirely by **Asynchronous (asyncio)** programming and **Test-Driven Development (TDD)**.

1\. Core Engineering Paradigms
------------------------------

### 1.1 The "Async-First" Mandate

To achieve high concurrency and handle thousands of users across different platforms (Telegram, Bale) without blocking, the entire stack must be asynchronous.

-   **No blocking I/O:** Synchronous libraries like `requests` or `urllib` are strictly forbidden. Use `httpx.AsyncClient` for all inter-microservice communication.

-   **Event Loop Sharing:** FastAPI (Uvicorn) and Telethon must run on the exact same `asyncio` event loop.

-   **File I/O:** Use `aiofiles` for any local file reading/writing and use `aiocache` for caching (e.g., generating `.md` files). Don't create file until needed and use BytesIO instead.

### 1.2 Test-Driven Development (TDD) Protocol

Code is only written to make a failing test pass. The flow must be: **Red ➔ Green ➔ Refactor**.

-   All business logic, HTTP clients, and webhook handlers must be tested independently of the messenger platforms.

-   **Pytest & Asyncio:** Use `pytest-asyncio` for all tests.

-   **Mocking:** * Mock external microservices (USSO, AI Toolkit) using `pytest-httpx`.

    -   Mock incoming Webhook payloads (for Bale) and MTProto events (for Telegram) to test handlers without actual network I/O.

-   **Coverage:** Minimum acceptable test coverage is 85%.

2\. Refined Project Structure (Apps-Centric)
--------------------------------------------

The folder structure is strictly domain-driven (Apps-centric). The `app` directory serves as the isolated container context.

```
.
├── docker-compose.yml           # Orchestrates the container(s) and external network
├── README.md
└── app/                         # Everything inside goes into the Docker container
    ├── Dockerfile               # Container definition for the app
    ├── pyproject.toml           # Dependencies, Ruff, Mypy, and Pytest config
    ├── main.py                  # Application entry point (Mounts routers & lifespans)
    ├── server/                  # Core infrastructure
    │   ├── server.py            # FastAPI initialization and middleware injection
    │   ├── config.py            # Environment variables (Pydantic BaseSettings)
    │   └── db.py                # Shared async db clients
    ├── apps/                    # Domain-centric applications
    │   ├── ai/                  # AI Toolkit interactions
    │   │   ├── clients.py       # httpx client for AI Toolkit
    │   │   ├── routes.py        # Webhooks for async task completion (e.g., OCR callbacks)
    │   │   └── services.py
    │   ├── accounts/            # USSO integration
    │   │   ├── clients.py
    │   │   └── schemas.py
    │   └── bots/                # Client gateways (Multi-platform)
    │       ├── common/          # Shared logic (handler, events, keyboards, billing)
    │       ├── runtime/         # Bot lifecycle, registry, Bale poller
    │       ├── telegram/        # Telethon gateway (MTProto)
    │       └── bale/            # Bale telebot adapter
    ├── tests/                   # TDD Test Suites
    │   ├── conftest.py          # Pytest fixtures
    │   ├── apps/                # App-specific tests (mirroring the apps folder)
    │   └── utils/
    ├── texts/                   # Localization Strings
    │   ├── en.yaml
    │   └── fa.yaml
    └── utils/
        ├── i18n.py              # YAML localization parser
        ├── texttools.py         # Markdown generation, chunking
        └── ...

```

3\. Decentralized Routing & Hybrid Initialization
-------------------------------------------------

Putting all routes in a single folder is an anti-pattern. Every app owns its `routes.py`. FastAPI acts as the HTTP server for both **Internal Microservice Callbacks** (AI Toolkit) and **External Webhooks** (Bale Bot).

4\. Multi-Platform Bot Architecture (Telegram vs. Bale)
-------------------------------------------------------

The architecture supports multiple bot paradigms running simultaneously.

### 4.1 Telegram (Telethon - MTProto)

Because we need to support files up to 2GB, we use Telethon. It does not use HTTP webhooks; it runs a persistent socket connection within the `asyncio` loop.

### 4.2 Bale (FastAPI - HTTP Webhook)

Bale uses a standard Telegram-like Bot API but operates via HTTP Webhooks.

-   **Flow:** 
```python
from fastapi import APIRouter, Request from app.apps.bots.common.context import process_bot_message

router = APIRouter()

@router.post("/webhook")
async def bale_webhook(payload: dict):
    # Parse standard HTTP Webhook payload
    user_id = payload.get("message", {}).get("from", {}).get("id")
    text = payload.get("message", {}).get("text")

    # Hand off to the shared common logic used by both Bale and Telegram
    asyncio.create_task(process_bot_message(platform="bale", user_id=user_id, text=text))
    return {"status": "ok"}
```

5\. Use this other micro services
---------------------------------

Usso           (user management): https://usso.uln.me/api/sso/v1/docs
Media          (online file management): https://media.uln.me/api/media/v1/docs
Shop           (product list and buy mchanism): https://shop.uln.me/api/shop/v1/docs
AI-toolkit     (ai tools including (chat, openai compatible, promptic, ocr, transcribe, youtube)) https://toolkit.uln.me/api/ai/v1/docs


6\. Rendering & Large Outputs
-----------------------------

Messaging platforms have character limits (e.g., 4096).

8\. Code Quality & Formatting
-----------------------------

-   **Ruff:** Used as the primary linter and formatter. Run `ruff check .` and `ruff format .` via pre-commit hooks.

-   **Type Hinting:** `ty` and `mypy` is strictly enforced. Avoid `Any` and use `object` only where really needed. Try to use Pydantic models for all webhook and API request/response payloads in their respective `schemas.py`.
