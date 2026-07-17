# Implementation Roadmap

This roadmap moves the current app toward the PRD without a risky one-shot rewrite.

## Phase 0: Stabilize Current UX

- Keep Telegram webhook mode by default.
- Keep Telethon for large Telegram file download.
- Fix text chat response rendering.
- Fix URL UX so raw extracted content is not dumped into chat.
- Keep AI billing in AI Toolkit.
- Add YAML localization and remove hardcoded high-traffic UX strings first.

## Phase 1: Clean User Flows

- Add `apps/bots/messages.py` or equivalent text access helpers.
- Add result/artifact references for callback actions.
- Move action callbacks away from visible message text.
- Disable or implement incomplete menu actions such as My Chats.
- Return long outputs as Markdown files through Media.

## Phase 2: Conversation Domain

- Add async models/repositories for sessions, messages, artifacts, and platform users.
- Persist incoming and outgoing messages.
- Implement active session mapping.
- Generate session titles.
- Implement My Chats and reopen session.

## Phase 3: AI Toolkit Contract Alignment

- Align clients with final AI Toolkit routes for chat, completion, promptic/actions, transcribe, document extract, URL import.
- Add trace ids and retries to external clients.
- Keep all external I/O async.

## Phase 4: Telethon-First Gateway

- Introduce a Telethon gateway and normalized internal event schema.
- Move Telegram-specific rendering into Telegram renderer.
- Keep product flow code platform-independent.
- Retire legacy telebot handler code after parity tests pass.

## Phase 5: Coverage And Quality Gate

- Maintain `uv run ruff check .` passing.
- Maintain `uv run pytest --cov=. --cov-report=term-missing --cov-fail-under=85` passing.
- Add tests for clients, services, repositories, renderers, and event normalization.

Current baseline after Phase 0 UX cleanup: `uv run pytest -q` passes, but global coverage is still below 85% because legacy bot, polling, webhook, Redis, and utility modules are under-tested. Do not lower the threshold or hide files with coverage omissions; raise coverage as code is migrated into smaller tested services.
