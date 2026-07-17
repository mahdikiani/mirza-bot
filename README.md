# AI Toolkit Bot — PRD, User Flow, Architecture & Implementation Spec

## 1. Product Overview

The project is a messaging-based AI assistant. The bot itself is only the user interface layer. It should not contain core AI logic.

The bot receives user input from messaging platforms, normalizes it, manages sessions and context, then calls backend services such as `ai-toolkit`.

The first production client should be Telegram. The implementation can use Telethon/MTProto to provide a smoother Telegram-native experience. Future clients such as Bale, WhatsApp, Web, or API clients should be added later through separate adapters.

## 2. Core Principle

The bot is a thin client.

It is responsible for:

* receiving messages
* rendering responses
* handling Telegram/Bale-specific UX
* managing chat sessions
* reconstructing context
* forwarding requests to AI Toolkit
* showing account, credit, and package purchase UI

It is not responsible for:

* LLM execution
* OCR
* transcription
* YouTube transcript extraction
* image generation
* prompt execution
* billing calculation
* provider logic
* document parsing

Those belong to backend services, mainly `ai-toolkit`.

---

# 3. Phase 1 Architecture

```text
Telegram Client
    ↓
Bot Gateway
    ↓
Conversation Service
    ↓
AI Toolkit
    ↔
Billing / Usage Metering
```

## 3.1 Bot Gateway

Responsibilities:

* connect to Telegram using Telethon
* normalize Telegram updates into internal events
* receive text, files, audio, voice, video, URLs, inline queries
* detect reply chains
* render text, Markdown files, inline keyboards
* expose main menu
* call AI Toolkit APIs

## 3.2 Conversation Service

Responsibilities:

* create chat sessions
* store messages
* store generated artifacts
* store file references
* reconstruct context
* search chat history
* reopen previous sessions
* rename sessions
* archive/delete sessions

## 3.3 AI Toolkit

Expected tools:

* chat
* completion
* promptic
* OCR
* transcribe
* YouTube transcript
* URL import
* Google Drive import
* document parsing
* summarization
* translation
* formatting
* Markdown generation
* future image generation

## 3.4 Billing

Billing should not trust the bot as the source of usage.

Correct flow:

```text
Bot → AI Toolkit → Billing
```

AI Toolkit should:

* check balance before execution
* reserve estimated credits if needed
* execute the tool
* calculate actual usage
* finalize charge
* refund unused reservation if needed

Bot may show balance and package purchase UI, but actual usage charging must happen behind AI Toolkit.

---

# 4. Phase 2 Architecture With Hermes

Hermes is optional in Phase 1.

Hermes should be introduced when requests need:

* isolated user workspace
* command execution
* file system operations
* persistent workspace state
* multi-step agentic workflows
* script execution
* project-level operations

Future flow:

```text
Bot Gateway
    ↓
Hermes Orchestrator
    ↓
AI Toolkit
    ↔
Billing
```

Hermes should sit in front of AI Toolkit only for workspace/execution-heavy flows.

---

# 5. Main User Flow

## 5.1 First Entry

Goal: user should start chatting immediately with minimum friction.

When user opens the bot:

```text
/start
  ↓
Bot shows short welcome message
  ↓
User can immediately type anything
```

The bot must not force onboarding before first usage.

Welcome message should be short:

```text
Hi. Send me a message, file, voice, video, image, PDF, YouTube link, or Google Drive link.
```

Main menu should be available but not blocking.

## 5.2 Main Menu

Persistent menu items:

```text
New Chat
My Chats
Upload File
My Account
Buy Credits
Help
```

The default behavior should still be free-form chat.

---

# 6. Chat Flow

## 6.1 Normal Text Chat

```text
User sends text
    ↓
Bot creates or continues active session
    ↓
Bot sends message/context to AI Toolkit chat/completion
    ↓
AI Toolkit returns response
    ↓
Bot renders response
```

## 6.2 Response Size Rules

If response is short:

```text
Send normal text message
```

If response exceeds platform limit:

```text
Generate Markdown file
Send .md file
Attach action buttons
```

Telegram message limit should be respected. Long responses should not be split endlessly. Prefer Markdown file for long structured outputs.

---

# 7. Reply-Based Context

Users can reply to previous messages.

The bot should use reply-chain reconstruction.

## 7.1 Private Chat Reply

```text
User replies to bot/user message
    ↓
Bot walks backward through reply chain
    ↓
Bot collects relevant context
    ↓
Bot calls AI Toolkit
    ↓
Bot returns response
```

Reply targets may include:

* text messages
* bot responses
* Markdown files
* extracted documents
* uploaded files
* transcripts
* OCR results

## 7.2 Group Chat Reply

The bot can be added to groups.

In groups, the bot must not read or use the entire group history.

It should only follow reply chains.

```text
Group user replies to a message and mentions/addresses bot
    ↓
Bot follows reply chain backward
    ↓
Bot reconstructs context
    ↓
Bot answers using that context
```

This avoids unrelated group messages polluting context.

---

# 8. Inline Query Mode

Telegram inline query should be supported.

Example:

```text
@BotName summarize this text...
```

Flow:

```text
Telegram inline query
    ↓
Bot sends prompt to AI Toolkit
    ↓
AI Toolkit returns result
    ↓
Bot returns inline result
    ↓
User inserts result into current chat
```

Use cases:

* quick rewrite
* translation
* summarization
* answering questions
* code generation
* message drafting

---

# 9. Chat Sessions

Every conversation must be stored as a named session.

## 9.1 Session Fields

```text
session_id
user_id
platform
platform_chat_id
title
created_at
updated_at
last_message_at
message_count
summary
status
```

## 9.2 Title Generation

Each session should have a human-readable title.

Rules:

* from first meaningful user message
* from uploaded file name
* from transcript summary
* from URL title
* user can rename manually

Examples:

```text
Tax objection letter
Lecture transcription about product management
YouTube summary about AI agents
PILARO campaign image prompts
```

## 9.3 My Chats

User can:

* view recent chats
* search chats
* open old session
* continue old session
* rename session
* archive/delete session

Flow:

```text
Main Menu
  ↓
My Chats
  ↓
Recent Chats / Search
  ↓
Open Session
  ↓
Continue Conversation
```

---

# 10. File Processing

Supported inputs:

* PDF
* image
* scanned document
* Word document
* Markdown
* plain text
* audio
* voice
* video
* direct URL
* YouTube link
* Google Drive link

## 10.1 Document Upload

```text
User uploads file
    ↓
Bot stores file reference
    ↓
Bot sends file to AI Toolkit import/OCR/parser
    ↓
AI Toolkit returns extracted text/artifact
    ↓
Bot sends result
    ↓
Bot attaches action buttons
```

## 10.2 Output Rules

Short result:

```text
Return as text
```

Long result:

```text
Return as Markdown file
```

All extracted/generated content should be saved as an artifact and attached to the session.

---

# 11. Audio / Voice / Video Transcription

Supported:

* Telegram voice
* audio file
* video file

Flow:

```text
User uploads media
    ↓
Bot forwards media to AI Toolkit transcribe
    ↓
AI Toolkit extracts audio if needed
    ↓
AI Toolkit transcribes
    ↓
Bot returns transcript
```

Long transcript should be returned as Markdown.

After transcript generation, user can ask follow-up questions.

---

# 12. URL Import

Supported initially:

* YouTube
* direct file URL
* Google Drive link if accessible

Future:

* Dropbox
* OneDrive
* Notion
* GitHub

Flow:

```text
User sends URL
    ↓
Bot detects URL
    ↓
Bot forwards URL to AI Toolkit importer
    ↓
AI Toolkit selects provider
    ↓
AI Toolkit extracts content
    ↓
Bot returns output
```

---

# 13. Inline Action Buttons

Whenever bot returns a document, transcript, OCR result, imported content, or long AI output, attach inline action buttons.

Initial buttons:

```text
Translate
Summarize
Format as Notes
Ask Question
```

## 13.1 Translate

Translate full content.

## 13.2 Summarize

Generate concise summary.

## 13.3 Format as Notes

Convert raw content into a structured document:

* title
* headings
* H1/H2/H3 hierarchy
* clean paragraphs
* bullet points
* unified style

Useful for:

* lectures
* meeting notes
* speech transcripts
* raw OCR
* long AI output

## 13.4 Ask Question

Starts a follow-up question flow over that artifact.

---

# 14. Account & Credits

Main menu should include:

```text
My Account
Buy Credits
```

## 14.1 My Account

Show:

* remaining credits
* total purchased credits
* consumed credits
* current plan/package if any

Bot should fetch this from Billing or AI Toolkit-facing account endpoint.

## 14.2 Buy Credits

Show available packages.

Initial packages can be simple, for example:

```text
Package A: 10,000 Toman
Package B: 20,000 Toman / 300 coins
```

Payment can be handled through existing Shop service.

Bot handles purchase UI. Billing handles credit ledger.

---

# 15. AI Toolkit API Contract

Bot should call AI Toolkit through clear APIs.

## 15.1 Chat

```http
POST /v1/chat
```

Request:

```json
{
  "user_id": "string",
  "session_id": "string",
  "message": "string",
  "context": [
    {
      "role": "user|assistant|system|tool",
      "content": "string",
      "artifact_id": "string|null"
    }
  ],
  "metadata": {
    "platform": "telegram",
    "platform_chat_id": "string",
    "reply_chain_root_id": "string|null"
  }
}
```

Response:

```json
{
  "type": "text|markdown_file|artifact",
  "content": "string",
  "artifact_id": "string|null",
  "usage": {
    "credits": 12,
    "tokens": 3500
  }
}
```

## 15.2 Completion / Promptic

```http
POST /v1/completion
POST /v1/promptic/run
```

Used for inline query, action buttons, formatting, translation, summarization.

## 15.3 Transcribe

```http
POST /v1/transcribe
```

Input:

* file
* file_url
* platform_file_reference

Output:

```json
{
  "text": "string",
  "artifact_id": "string",
  "duration_seconds": 3600,
  "usage": {}
}
```

## 15.4 OCR / Document Parse

```http
POST /v1/documents/extract
```

Input:

* PDF
* image
* document file

Output:

```json
{
  "text": "string",
  "artifact_id": "string",
  "pages": 12,
  "usage": {}
}
```

## 15.5 URL Import

```http
POST /v1/import/url
```

Input:

```json
{
  "url": "string",
  "user_id": "string",
  "session_id": "string"
}
```

Output:

```json
{
  "title": "string",
  "content": "string",
  "artifact_id": "string",
  "source_type": "youtube|google_drive|direct_file|web"
}
```

## 15.6 Action Run

```http
POST /v1/actions/run
```

Input:

```json
{
  "action": "translate|summarize|format_notes|ask_question",
  "artifact_id": "string",
  "user_input": "string|null",
  "user_id": "string",
  "session_id": "string"
}
```

---

# 16. Internal Domain Model

## 16.1 User

```text
id
platform
platform_user_id
username
first_name
last_name
created_at
updated_at
```

## 16.2 Session

```text
id
user_id
platform
platform_chat_id
title
summary
status
created_at
updated_at
last_message_at
```

## 16.3 Message

```text
id
session_id
user_id
platform_message_id
role
content_type
text
artifact_id
reply_to_message_id
created_at
```

## 16.4 Artifact

```text
id
user_id
session_id
type
title
mime_type
storage_url
text_content
metadata
created_at
```

Artifact types:

```text
markdown
transcript
ocr_result
document_text
image
audio
video
imported_url
ai_response
```

## 16.5 Usage Event

```text
id
user_id
session_id
tool_name
artifact_id
estimated_credits
actual_credits
provider_usage
created_at
```

---

# 17. Localization

No user-facing text should be hardcoded.

Use external text files:

```text
texts/
  en.json
  fa.json
```

All bot messages, buttons, errors, help text, and menu labels should be loaded from localization files.

---

# 18. Error Handling

The bot should handle common failures gracefully.

Examples:

## Not enough credits

```text
You do not have enough credits. Please buy a package to continue.
```

## File too large

```text
This file is too large to process.
```

## Unsupported file

```text
This file type is not supported yet.
```

## AI Toolkit unavailable

```text
The AI service is temporarily unavailable. Please try again later.
```

## Import failed

```text
I could not access this link. Please check that it is public or accessible.
```

Errors should be stored in logs with:

```text
user_id
session_id
platform
tool_name
error_code
trace_id
```

---

# 19. MVP Scope

## Must Have

* Telegram client using Telethon
* `/start`
* free-form chat
* session creation
* automatic session title
* My Chats
* reply-chain context
* file upload
* OCR/document extract via AI Toolkit
* voice/audio/video transcription via AI Toolkit
* YouTube/URL import via AI Toolkit
* Markdown output for long responses
* inline action buttons
* Translate/Summarize/Format as Notes
* My Account
* Buy Credits
* Billing integration through AI Toolkit
* localization files
* basic logs and trace IDs

## Should Have

* inline query mode
* group chat reply-chain support
* chat search
* rename/archive sessions
* Google Drive import

## Later

* Bale client
* WhatsApp client
* Hermes workspace
* image generation
* image editing
* command execution
* data analysis
* agentic workflows

---

# 20. Implementation Backlog

## Epic 1: Telegram Client

Tasks:

* setup Telethon client
* handle `/start`
* handle text messages
* handle file messages
* handle voice/audio/video
* handle inline keyboard callbacks
* handle inline queries
* handle group messages
* normalize all incoming events

## Epic 2: Conversation System

Tasks:

* create User model
* create Session model
* create Message model
* create Artifact model
* save incoming/outgoing messages
* generate session title
* implement My Chats
* implement search
* implement reopen session
* implement rename/archive/delete

## Epic 3: AI Toolkit Integration

Tasks:

* implement client for `/v1/chat`
* implement client for `/v1/completion`
* implement client for `/v1/transcribe`
* implement client for `/v1/documents/extract`
* implement client for `/v1/import/url`
* implement client for `/v1/actions/run`
* add retries/timeouts
* add trace IDs

## Epic 4: File Handling

Tasks:

* download Telegram files
* store file temporarily or permanently
* send file to AI Toolkit
* save returned artifact
* render short output as text
* render long output as Markdown file

## Epic 5: Inline Actions

Tasks:

* define action buttons
* map callback data to artifact/action
* call AI Toolkit action endpoint
* render result
* save result as message/artifact

## Epic 6: Billing UI

Tasks:

* fetch balance
* show My Account
* show packages
* integrate Shop payment
* handle successful payment callback
* refresh credit balance

## Epic 7: Group Chat

Tasks:

* detect group chat messages
* respond only when mentioned/replied/triggered
* reconstruct reply-chain context
* avoid reading unrelated group history
* store group sessions separately

## Epic 8: Inline Query

Tasks:

* handle inline query
* call AI Toolkit completion
* return inline result
* support short generated text
* optionally support generated article result

## Epic 9: Localization

Tasks:

* create text resource files
* replace hardcoded strings
* support Persian and English
* centralize buttons and menu labels

## Epic 10: Observability

Tasks:

* structured logging
* trace ID per request
* error reporting
* tool latency metrics
* AI Toolkit response time
* failed job logs
* billing failure logs

---

# 21. Codex Implementation Instruction

Implement this project as a modular Python backend.

Recommended structure:

```text
app/
  main.py
  config.py

  clients/
    telegram/
      telethon_client.py
      handlers.py
      renderers.py
      normalizer.py

    ai_toolkit/
      client.py
      schemas.py

    shop/
      client.py

  domain/
    users.py
    sessions.py
    messages.py
    artifacts.py
    usage.py

  services/
    conversation_service.py
    context_service.py
    session_title_service.py
    file_service.py
    action_service.py
    billing_service.py

  repositories/
    users_repo.py
    sessions_repo.py
    messages_repo.py
    artifacts_repo.py

  texts/
    en.json
    fa.json

  utils/
    ids.py
    logging.py
    markdown.py
    limits.py
```

Hard rules:

* Keep Telegram-specific logic inside `clients/telegram`.
* Keep AI Toolkit logic inside `clients/ai_toolkit`.
* Do not put AI logic inside the bot.
* Do not calculate actual usage inside the bot.
* Store sessions and messages in the bot backend.
* Store or reference artifacts.
* All user-facing text must come from `texts/*.json`.
* Every external request must have timeout, retry policy, and trace ID.
* Long outputs must become Markdown files.
* Reply chains must be supported.
* Group chat must use reply-chain context only.
* Session history and search must be implemented.
* The code should allow future Bale/WhatsApp clients without rewriting core services.
