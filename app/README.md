# AI Toolkit Bot

Messaging bot backend for AI Toolkit. Telegram is moving to a Telethon-native
runtime, while FastAPI remains responsible for webhooks, AI task callbacks, and
worker startup.

Start here:

- Product requirements: `docs/ai-toolkit-bot-prd.md`
- Migration roadmap: `docs/implementation-roadmap.md`
- Architecture/editing guide: `docs/project-architecture.md`

Useful checks:

```bash
uv run pytest -q
uv run ruff check <changed-files>
uv run python -m compileall apps server utils main.py
```
