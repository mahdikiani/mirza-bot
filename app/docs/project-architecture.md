# Project Architecture Guide

This project is a multi-messenger bot backend. Telegram runs through Telethon;
Bale runs through telebot/`telegram-bale-bot`. Both adapters normalize updates
into shared events and call the same product logic in `apps/bots/common/`.

## Product Boundary

The bot is a thin async client. It receives user input, normalizes platform
events, manages local conversation state (reply-chain), calls backend services,
and renders responses. It must not implement LLM execution, billing calculation,
OCR, transcription, or provider-specific AI logic.

Backend services own those responsibilities:

- AI Toolkit: completions, promptic, OCR, transcription, YouTube/webpage.
- USSO: user identity and profiles.
- Media: uploaded files and result artifacts.
- Shop/SaaS: packages, purchase links, quota display.

## Architecture Model

```text
کاربر در پیام‌رسان
        │
        ▼
apps/bots/<messenger>/     # telegram | bale | …
  - receive update
  - normalize → MessageEvent / CallbackEvent / …
  - render outbound replies
  - own transport (Telethon or telebot)
        │
        ▼
apps/bots/common/          # shared product logic only
  - handler, media_flow, billing, context, …
```

```text
FastAPI app
├── AI task webhooks
├── Bale getUpdates poller (always on)
└── Telethon gateway (Telegram)
```

## Transport Boundary

| Messenger | Folder | Library |
|-----------|--------|---------|
| Telegram | `apps/bots/telegram/` | Telethon only |
| Bale | `apps/bots/bale/` | telebot / telegram-bale-bot + **getUpdates polling** |

There is no shared `BaseBot` across messengers. Shared abstraction is
`EventRenderer` + normalized events in `common/`.

## Important Modules

### `apps/bots/common/`

- `events.py` — `MessageEvent`, `CallbackEvent`, …
- `handler.py` — orchestration entry (`handle_message_event`, …)
- `media_flow.py`, `billing.py`, `context.py`, `actions.py`, …
- `renderer_registry.py` — bot_name → renderer for AI webhooks

### `apps/bots/telegram/`

- `bot.py` — token / username config
- `gateway.py` — Telethon loop + `TelethonEventRenderer`

### `apps/bots/bale/`

- `bot.py` — `BaleBot(AsyncTeleBot)`
- `routes.py`, `handler.py`, `normalizer.py`, `renderer.py`, `markup.py`

### `apps/bots/runtime/`

- `handlers.py` — startup orchestration
- `registry.py` — explicit bot registry
- `poller.py` — Bale getUpdates loop (primary transport)

### Clients

```text
utils/clients/           → HTTP infra (_base, toolkit, finance, media)
apps/ai/clients.py       → OCR, Transcribe, Youtube, Webpage, Promptic, Completion
apps/accounts/clients.py → USSO
```

Feature code calls these clients — not raw `httpx`.

## Configuration

```text
TELEGRAM_TOKEN=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
BALE_BOT_TOKEN=...
BALE_BOT_NAME=...
POLLING_INTERVAL_SECONDS=2
MONGO_URI=...
REDIS_URI=...
AI_TOOLKIT_BASE_URL=...
AI_API_KEY=...
MEDIA_BASE_URL=...
MEDIA_API_KEY=...
```

Bale always polls via getUpdates. Telegram always uses Telethon.

## How To Add A Feature

1. Identify the normalized event.
2. Add logic in `apps/bots/common/` (handler or feature module).
3. Store platform IDs in event metadata, not native SDK objects.
4. Call `apps.ai.clients` / `apps.accounts.clients` / `utils.clients.*`.
5. Render via the adapter's `EventRenderer`.

## How To Add A Platform

1. Create `apps/bots/<platform>/`.
2. Normalize native updates into shared events.
3. Implement an `EventRenderer`.
4. Register the bot in `runtime` startup and renderer registry.
5. Keep transport SDK imports inside that folder only.
