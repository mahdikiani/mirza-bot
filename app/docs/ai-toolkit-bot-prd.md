# AI Toolkit Bot PRD

Status: Target product and implementation contract.

Current implementation: partially aligned. The existing code still contains legacy `telebot` flows, while the target architecture is Telethon-first with clean domain services and async service clients.

## Product Overview

The project is a messaging-based AI assistant. The bot is only the user interface layer. Core AI logic belongs to backend services, mainly AI Toolkit.

The bot receives user input from messaging platforms, normalizes it, manages sessions and context, then calls backend services such as AI Toolkit, USSO, Media, and Shop/Billing services.

Telegram is the first production client. Telethon/MTProto should provide Telegram-native behavior and large-file support. Future clients such as Bale, WhatsApp, Web, or API clients should be added through separate adapters.

## Core Principle

The bot is a thin async client.

It is responsible for receiving messages, rendering responses, handling platform-specific UX, managing chat sessions, reconstructing context, forwarding requests to AI Toolkit, and showing account/credit/package UI.

It is not responsible for LLM execution, OCR, transcription, YouTube transcript extraction, image generation, prompt execution, billing calculation, provider logic, or document parsing.

## Service Boundaries

The bot must use existing side services instead of reimplementing them:

- USSO: identity, users, profiles, auth/service permissions.
- Media: uploaded files, markdown result files, artifact URLs.
- AI Toolkit: chat, promptic/actions, OCR, transcription, URL import, usage metering.
- Shop/Billing UI: packages, purchase links, balance display when exposed.

Correct AI billing flow:

```text
Bot -> AI Toolkit -> Billing
```

AI Toolkit should check balance, reserve estimated credits when needed, execute tools, calculate actual usage, finalize charge, and refund unused reservation.

## Main User Flow

### First Entry

`/start` should show a short welcome message. It must not block usage with onboarding.

Main menu:

- New Chat
- My Chats
- Upload File
- My Account
- Buy Credits
- Help

Default behavior remains free-form chat.

### Text Chat

User sends text, the bot creates or continues the active session, sends the message/context to AI Toolkit, then renders the response.

Short responses are sent as text. Long responses become Markdown files instead of endless message chunks.

### Reply Context

Users can reply to previous messages. The bot should reconstruct reply-chain context.

In group chats the bot must not read full group history. It only follows reply chains when mentioned, replied to, or explicitly triggered.

### Inline Query

Telegram inline query should call AI Toolkit completion/chat and return insertable results for quick rewrite, translation, summarization, answers, code generation, and drafting.

### Sessions

Every conversation is a named session with user, platform, chat id, title, timestamps, message count, summary, and status.

Users can view recent chats, search chats, open old sessions, continue sessions, rename sessions, and archive/delete sessions.

Session titles come from first meaningful message, uploaded filename, transcript summary, URL title, or manual rename.

### File Processing

Supported inputs include PDF, image, scanned document, Word, Markdown, text, audio, voice, video, URL, YouTube, and accessible Google Drive links.

The bot stores or references artifacts and delegates OCR/document parsing/transcription/import to AI Toolkit.

### URL Import

The bot detects URLs and forwards them to AI Toolkit import. The bot should not dump raw imported content into chat by default. It should summarize or answer the user's question.

### Action Buttons

Whenever the bot returns a document, transcript, OCR result, imported content, or long AI output, attach inline actions:

- Translate
- Summarize
- Format as Notes
- Ask Question

Actions operate on stored artifacts/content refs, not visible Telegram message text.

### Account And Credits

The main menu includes My Account and Buy Credits. The bot shows account/package UI, but actual AI usage charging happens behind AI Toolkit.

## Internal Domain Model

The bot backend owns local conversation state only:

- User: local platform-user reference, not a USSO replacement.
- Session: conversation identity, title, summary, status.
- Message: incoming/outgoing platform message references.
- Artifact: references to Media/AI Toolkit artifacts and text snapshots when needed.
- Usage event: reference/trace data only; actual AI charging is not calculated by bot.

## Localization

No user-facing text should be hardcoded. Use YAML files:

```text
texts/fa.yaml
texts/en.yaml
```

All bot messages, buttons, errors, help text, and menu labels should be loaded from localization files.

## Error Handling

The bot should gracefully handle not enough credits, file too large, unsupported files, AI Toolkit unavailable, and import failures.

Logs should include user id, session id, platform, tool name, error code, and trace id.

## MVP Scope

Must have: Telegram client, `/start`, free-form chat, session creation, automatic title, My Chats, reply-chain context, file upload, OCR/document extract, transcribe, URL import, Markdown output for long responses, action buttons, My Account, Buy Credits, billing through AI Toolkit, YAML localization, logs and trace ids.

Should have: inline query mode, group reply-chain support, chat search, rename/archive sessions, Google Drive import.

Later: Bale client, WhatsApp client, Hermes workspace, image generation/editing, command execution, data analysis, and agentic workflows.

## Hard Rules

- Keep platform-specific logic inside platform clients/adapters.
- Keep AI Toolkit logic inside AI Toolkit clients.
- Do not put AI logic inside the bot.
- Do not calculate actual AI usage inside the bot.
- Store sessions and messages in the bot backend.
- Store or reference artifacts.
- All user-facing text must come from YAML localization files.
- Every external request must have timeout, retry policy, and trace id.
- Long outputs must become Markdown files.
- Reply chains must be supported.
- Group chat must use reply-chain context only.
- Session history and search must be implemented.
- The code should allow future Bale/WhatsApp clients without rewriting core services.
