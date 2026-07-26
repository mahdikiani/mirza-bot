# Mirza Bot — overview

Mirza is a multi-messenger AI assistant. Users talk in Telegram or Bale; the bot
normalizes events, keeps continuity via **reply-chains** (not Toolkit chat
sessions), and calls AI Toolkit for completions, OCR, transcription, YouTube,
and related tasks.

## Layers

| Layer | Path | Role |
|-------|------|------|
| Telegram transport | `apps/bots/telegram/` | Telethon gateway + normalizer + renderer |
| Bale transport | `apps/bots/bale/` | telebot polling + normalizer + renderer |
| Shared product logic | `apps/bots/common/` | handlers, media, billing, auth, keyboards |
| Domain AI / accounts | `apps/ai/`, `apps/accounts/` | webhooks, clients, USSO |

```text
User → messenger adapter → common handler → AI Toolkit / USSO / Media / Shop
         ↑ delivery ← webhook or task poller ← async toolkit tasks
```

## Message flow

1. Adapter normalizes to `MessageEvent` / `CallbackEvent` / `InlineQueryEvent`.
2. Auth gate: verified phone + USSO (with TTL cache; last-known on USSO outage).
3. Route: text chat (reply-chain), file (OCR/transcribe), URL, settings, convert.
4. Async work stores pending meta in Redis; toolkit calls `/ai/*/webhook/` or
   the poller falls back; delivery uses **pending meta only** (payload meta is
   ignored), then edits the processing message.

## Auth

- USSO is source of truth for users/identifiers (`telegram_id` / `bale_id`).
- Local `BotUser` holds prefs and last-known verification.
- Inline query (Telegram only) requires the same verified user as chat.
- Bale does **not** support inline query (`supports_inline_query=False`).

## Links → behavior

| Link kind | Behavior |
|-----------|----------|
| YouTube | Async toolkit YouTube task |
| Direct file URL | Async OCR or transcribe by extension |
| Webpage | Sync Jina Reader + optional completion |
| Google Drive | Fail-fast: ask user to upload / send direct file URL |

## Groups

Respond only on `@bot` mention or reply to the bot’s own message
(`should_respond_in_group`). Telegram group/`chat_type` and reply sender meta
match the Bale normalizer.

## Webhooks

- Require `WEBHOOK_API_KEY` (separate from `AI_API_KEY`; fail-closed if unset);
  compare with `hmac.compare_digest`.
- Delivery routing uses pending-task meta only — no fallback to payload meta.

## Out of scope

Celery/queues; Toolkit chat sessions / “My Chats” UI contrary to reply-chain.
