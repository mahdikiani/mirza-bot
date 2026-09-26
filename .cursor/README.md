# Cloud Agent development environment

This directory configures the [Cursor Cloud Agent](https://cursor.com/docs/cloud-agent/setup)
environment for Mirza Bot.

## Base image

System dependencies are baked into the base snapshot:

- **uv** — Python package/toolchain manager (installs Python 3.13)
- **MongoDB 8.0** — primary datastore (`mongod`)
- **Redis 7** — pending-task / result cache
- **pandoc** — Markdown → DOCX conversion

## Lifecycle scripts

| Script | Phase | Purpose |
| --- | --- | --- |
| [`install.sh`](install.sh) | `install` | `uv sync` (deps + Python 3.13) and seed a local dev `.env` from [`dev.env.example`](dev.env.example) if none exists. Idempotent. |
| [`start.sh`](start.sh) | `start` | Start MongoDB + Redis on localhost, only if not already running, and wait for MongoDB readiness. Idempotent. |

The bot gateway (`app/main.py`, FastAPI + Uvicorn) is launched as a persistent
terminal so its logs stay visible.

## Local commands

```bash
cd app
uv sync                 # install dependencies
uv run pytest -q        # test suite (85% coverage gate)
uv run ruff check .     # lint
uv run python main.py   # run the gateway (needs MongoDB + Redis)
```

Telegram/Bale adapters are skipped unless their tokens are supplied in `.env`;
the gateway still boots and serves webhooks, health, and readiness endpoints.
