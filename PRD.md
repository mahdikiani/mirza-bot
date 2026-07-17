📄 Product Requirements Document (PRD) -- AI Toolkit Bot
=======================================================

1\. Product Overview & Vision
-----------------------------

The **AI Toolkit Bot** is a messaging-based AI assistant that acts as a unified interface for a broader AI microservices ecosystem. The product is not just "a Telegram bot"; it is an AI Toolkit designed to help users perform complex, AI-powered tasks (transcription, summarization, OCR, translation) seamlessly within their daily chat environments.

The bot itself is strictly a **Thin Client**. It contains zero core AI logic, model orchestration, or heavy file processing capabilities. Its sole responsibility is to handle user interactions, manage UI/UX on messaging platforms (starting with Telegram), and orchestrate requests between the user and the backend microservices.

2\. System Architecture & Boundaries
------------------------------------

The system is designed around a microservices architecture to ensure high scalability and separation of concerns.

-   **Bot Gateway (Thin Client):** Built using **Telethon/MTProto** to support files up to 2GB. Normalizes Telegram events, manages reply-chain context gathering, handles UI rendering (inline keyboards, Markdown files), and executes asynchronous API calls.

-   **USSO (User Single Sign-On):** Manages user identity, account creation, phone-based lookup, and linking Telegram identities to universal user profiles.

-   **Media Service:** The central hub for file I/O. Handles uploading, downloading, storage, and access control. The Bot passes raw files here to obtain a reference URL.

-   **AI Toolkit:** The "Brain". Handles all AI execution. Exposes endpoints for:

    -   Native Chat & Threading (`/api/ai/v1/chat/...`)

    -   Dynamic Promptic Actions (`/api/ai/v1/promptic`)

    -   Async Task Engines (`/ocrs`, `/transcribes`, `/translates`, `/youtube`)

-   **Billing/Shop:** Manages credits, packages, and ledger calculations behind the AI Toolkit. The bot only displays UI balances.

3\. MVP Scope (Phase 1)
-----------------------

### ✅ Must Have (In-Scope)

-   **Telegram Native Integration:** Built with Telethon.

-   **Frictionless Onboarding:** Free-form chat enabled immediately. Phone number requested strictly via Telegram Contact button.

-   **Multi-Modal Input Support:** Text, PDF, Images, Audio, Voice, Video, and URLs (YouTube, Google Drive, Direct).

-   **Reply-Chain Context:** Context window is built by walking backward through Telegram reply chains, not by dumping the entire chat history.

-   **Asynchronous Processing (Webhooks):** Long-running tasks (OCR, Transcribe) are dispatched as non-blocking tasks with internal bot webhooks handling the callbacks.

-   **Action-Driven UX:** Inline Promptic buttons attached to outputs (e.g., `[Make Study Notes]`, `[Summarize]`, `[Translate]`).

-   **Output Formatting:** Responses exceeding Telegram's 4096-character limit are automatically converted to and sent as `.md` (Markdown) files.

-   **Group Chat Privacy:** The bot only processes group messages if explicitly mentioned (`@bot`) or directly replied to.

-   **Silent Health Check:** Bot utilizes a scheduled `is_typing` action to detect user blocks (yielding HTTP 403) without spamming the user's chat with menus.

-   **Strict Development Standards:** TDD, Pytest, Ruff (linting), Type Checking, and Dockerization.

### ❌ Out of Scope (Phase 2+)

-   Bale, WhatsApp, or Web clients (Architecture remains platform-agnostic to support these later).

-   Hermes agentic workspace (isolated user filesystems, multi-step agentic workflows).

-   Image and video generation features.

4\. Core User Flows
-------------------

### 4.1 Onboarding & Registration

1.  **Trigger:** User sends `/start`.

2.  **Resolution:** Bot checks local DB for `telegram_user_id`.

3.  **Authentication:** If unregistered, bot asks for the user's phone number strictly via the Telegram "Share Contact" button.

4.  **Validation:** Bot verifies `contact.user_id == telegram_user_id`. (Manual number entry is rejected to prevent spoofing).

5.  **Provisioning:** Bot syncs with USSO. User is activated. A brief welcome message introduces supported inputs (Files, Voices, Links).

### 4.2 Standard Text Chat

1.  **Trigger:** User sends text.

2.  **Context Assembly:**

    -   If standalone: Creates a new session/thread.

    -   If reply: Bot walks backward up the reply chain to compile context.

3.  **Execution:** Bot calls `POST /api/ai/v1/chat/sessions/{session_uid}/threads/{thread_uid}/messages` with `generate_reply=true`.

4.  **Response:** AI Toolkit generates the response. Bot renders it to the user.

### 4.3 Heavy Media Processing (OCR / Transcribe / YouTube)

1.  **Ingestion:** User sends a PDF, Video, or YouTube URL.

2.  **Media Handoff:** Bot uploads the file to the Media service and gets a `file_url` (skipped for YouTube URLs).

3.  **Task Dispatch:** Bot calls the relevant AI Toolkit endpoint (e.g., `/api/ai/v1/ocrs` or `/api/ai/v1/transcribes`) with `blocking=false` and a specific `webhook_url`.

4.  **Progress State:** Bot replies with an initial "Processing..." message and utilizes `is_typing` / `upload_document` chat actions.

5.  **Webhook Callback:** AI Toolkit finishes the task and posts the result to the bot's webhook endpoint.

6.  **Delivery:** Bot receives the payload, formatting it as text or an `.md` file, and sends it to the user.

7.  **Next Actions:** Bot attaches inline Promptic buttons (e.g., `[Make Study Notes]`).

### 4.4 Promptic Actions (Inline Buttons)

1.  **Trigger:** User clicks an inline button (e.g., `Summarize` on a transcribed lecture).

2.  **Execution:** Bot calls `POST /api/ai/v1/promptic` passing the `prompt_name` (e.g., "summarize"), the target `artifact_id`/text, and the `webhook_url`.

3.  **Delivery:** via webhook callback, bot delivers the formatted summary.

5\. Telegram-Specific Mechanics
-------------------------------

-   **File Size Limits:** By utilizing Telethon (MTProto), the bot bypasses the standard 20MB bot API limit, supporting downloads/uploads up to 2GB.

-   **Long Outputs:** If a generated text exceeds `4096` characters, the bot must save it as a UTF-8 `.md` file, upload it, and send it as a document.

-   **Group Chats:**

    -   The bot ignores all standard group chatter.

    -   Only activates on `@BotName` mentions or direct replies to the bot's messages.

    -   Context is strictly limited to the specific reply chain to prevent data leakage and hallucination.

-   **Inline Queries:** Supports `@BotName translate [text]` for rapid, stateless, one-shot completions without storing chat sessions.

6\. API Integration Contracts (AI Toolkit OpenAPI)
--------------------------------------------------

The bot integrates with the AI Toolkit using the following schema standards:

### 6.1 Native Threading

Instead of manually calling an LLM, the bot leverages the native thread management of the AI Toolkit:

-   **Endpoint:** `POST /api/ai/v1/chat/sessions/{session}/threads/{thread}/messages`

-   **Payload Requirement:** Must include `"generate_reply": true` so the toolkit appends the user message and automatically triggers the assistant completion.

### 6.2 Async Tasks & Webhooks

For all heavy operations (`/ocrs`, `/transcribes`, `/youtube`, `/promptic`):

-   **Dispatch Payload:** Must include `"blocking": false` (query param) and `"webhook_url": "https://bot.uln.me/webhooks/..."` in the JSON body.

-   **Webhook Ingestion:** The bot must expose routes to receive payloads matching:

    ```
    {
      "uid": "task_id",
      "task_status": "completed",
      "result": "Generated or extracted content...",
      "usage_amount": 10.5
    }

    ```

7\. Non-Functional Requirements (NFRs)
--------------------------------------

-   **Localization (i18n):** Zero hardcoded user-facing strings in the codebase. All texts, buttons, and error messages must reside in `texts/fa.yaml` and `texts/en.yaml`.

-   **Error Handling:**

    -   Graceful degradation for common errors: *File too large*, *Invalid Phone Number*, *Insufficient Credits*, *Unsupported Format*.

    -   If a webhook returns `task_status: "error"`, the bot parses `task_report` and informs the user politely.

-   **Observability:** All internal logs must include `trace_id`, `user_id`, and `session_id`. Billing/usage logging must not be calculated by the bot; the bot only logs the `usage_amount` provided by the AI Toolkit webhook.

-   **Code Quality:** Strictly TDD (Test-Driven Development). Enforced static typing (`mypy`/`pyright`) and linting (`ruff`).

-   **Deployment:** Fully containerized (`Dockerfile`, `docker-compose.yml`) utilizing Redis for temporary webhook state caching and rate limiting.