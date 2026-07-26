# User journeys (Telegram + Bale)

Shared logic lives in `apps/bots/common/`. Transport differs; product behavior should match.

| Journey | Telegram | Bale | Notes |
|---------|----------|------|-------|
| `/start` → contact → main menu | Yes | Yes | USSO sync best-effort |
| Text chat + reply-chain | Yes | Yes | `CompletionClient` |
| Photo/file → OCR | Yes | Yes | Async + webhook/poller |
| Voice/video → transcribe | Yes | Yes | Async + webhook/poller |
| YouTube link | Yes | Yes | Async |
| Webpage link | Yes | Yes | Sync Jina (canonical) |
| Google Drive link | Fail-fast message | Same | No fake OCR |
| Language / model / buy credits | Yes | Yes | |
| Convert → Word / Markdown | Yes | Yes | Stub formats removed from UI |
| Groups: mention or reply-to-bot | Yes | Yes | TG chat_type + reply meta fixed |
| Inline query | Yes (auth required) | Disabled | Capability flag |
| Async error UX | Edit processing msg | Same | Empty result → task_error |

See also [README.md](./README.md) and [project-architecture.md](./project-architecture.md).
