🗺️ User Flow Document -- AI Toolkit Bot
=======================================

Context: This document maps the exact user journeys for the AI Toolkit Telegram Bot. The bot acts strictly as a UI layer (Thin Client), delegating core logic to USSO, Media, and AI Toolkit microservices.

1\. Onboarding & Registration Flow
----------------------------------

Goal: Identify the user, link their Telegram account to the universal USSO identity, and grant access securely without typing phone numbers manually, while respecting their language preference.

1.  Trigger: User sends /start.

2.  Local Lookup & Language Detection: * Bot extracts telegram_user_id and language_code from the Telegram event.

-   If language_code is fa (or similar), the bot sets the temporary session language to Persian.

-   Bot checks the local database for an existing session/platform mapping.

-   If user exists & is active: Bot sends a welcome back message (in their preferred language) and displays the Main Menu. Flow ends.

-   If user is new: Proceed to step 3.

1.  Contact Request: Bot sends a localized welcome message (Persian or English) and displays a Reply Keyboard with a single button: [📱 Share Phone Number] / [📱 ارسال شماره تماس].

-   Constraint: Bot ignores typed phone numbers to prevent spoofing.

1.  Validation: User clicks the button and shares their contact.

-   Bot strictly verifies: contact.user_id == event.sender_id.

-   If mismatch: Bot rejects the contact -> "Please share your own phone number using the button." -> Returns to step 3.

1.  USSO Sync: Bot sends the verified phone number, Telegram metadata, and detected language to the USSO service.

-   USSO creates or links the account and returns a universal user_id.

1.  Activation: Bot stores the mapping locally, including the preferred_language (Persian or English).

2.  Success: Bot sends the onboarding completion message in the correct language:\
    "You're all set! Send me a text, PDF, image, voice message, video, or a link to get started."\
    (Main Menu keyboard is now available).

2\. Text Chat & Context Flow
----------------------------

Goal: Provide a seamless, context-aware chat experience without blowing up token limits or storing massive cross-platform chat histories in the bot's memory.

### 2.1 Private Chat (Standalone)

1.  Trigger: User sends a plain text message.

2.  Context: Bot treats this as a single-turn request or the start of a new thread.

3.  Execution: Bot calls POST /api/ai/v1/chat/sessions/{session}/threads/{thread}/messages with generate_reply=true.

4.  Response: AI Toolkit generates the response. Bot renders it to the user.

### 2.2 Private Chat (Reply Chain)

1.  Trigger: User replies to a previous message (either their own or the bot's).

2.  Context Reconstruction: Bot walks backward up the Telegram reply chain (reply_to_message_id) to compile the specific thread of conversation.

3.  Execution: Bot passes the context/reply-chain root to the AI Toolkit.

4.  Response: Bot receives the response and replies directly to the user's latest message, naturally continuing the chain.

### 2.3 Group Chat

Privacy Rule: The bot must not read unrelated group chatter.

1.  Trigger: User mentions the bot (@BotName hello) OR replies directly to a bot's message in a group.

2.  Context: Bot isolates the context strictly to the mentioned message or the specific reply chain.

3.  Response: Bot replies in the group, ensuring it does not hallucinate using unrelated group messages.

### 2.4 Inline Query Mode (Stateless)

1.  Trigger: User types @BotName translate this to English in any chat.

2.  Execution: Bot sends the prompt directly to the AI Toolkit Completion API (no session created).

3.  Response: User sees the generated result floating above the keyboard and taps to send it to their current chat.

3\. Media Processing Flow (OCR & Transcribe)
--------------------------------------------

Goal: Handle heavy files (up to 2GB via Telethon) asynchronously, keeping the user informed of progress.

### 3.1 Upload & Ingestion

1.  Trigger: User sends a PDF, Image, Voice, Audio, or Video file.

2.  Handoff to Media: Bot downloads the file (or streams it) and uploads it to the Media Service, obtaining a universal file_url.

### 3.2 Task Dispatch & Progress

1.  Dispatch: Bot calls the relevant AI Toolkit endpoint:

-   Image/PDF -> POST /api/ai/v1/ocrs

-   Audio/Video/Voice -> POST /api/ai/v1/transcribes

-   Payload includes blocking=false and a specific webhook_url.

1.  Progress Indicator: Bot sends a temporary localized message: "Processing your file..." / "در حال پردازش فایل..." and triggers a Telegram chat action (e.g., upload_document or is_typing).

### 3.3 Webhook Callback & Delivery

1.  Callback: AI Toolkit completes the background job and POSTs the result to the bot's webhook endpoint.

2.  Rendering:

-   If result length < 4096 chars: Bot edits the "Processing..." message with the final text.

-   If result length > 4096 chars: Bot generates a .md file, uploads it, and sends it as a document.

1.  Post-Action: Bot attaches inline Promptic Buttons beneath the result (localized to the user's language).

4\. URL & YouTube Flow
----------------------

1.  Trigger: User sends a message containing a URL.

2.  Routing: Bot parses the URL:

-   If youtube.com or youtu.be: Routes to POST /api/ai/v1/youtube.

-   If standard URL/Drive: Routes to POST /api/ai/v1/import/url.

1.  Execution: Dispatched as an async task with a webhook_url (similar to Media Flow).

2.  Delivery: Webhook receives the extracted text/transcript, sends it to the user (text or .md), and attaches Promptic buttons.

5\. Action Buttons (Promptic) Flow
----------------------------------

Goal: Guide the user to complete "Jobs-to-be-Done" (e.g., studying, summarizing) without making them write complex prompts.

1.  Trigger: User clicks an inline button attached to a previous output (e.g., [Make Study Notes], [Summarize], [Translate]).

2.  Resolution: Bot identifies the artifact_id or the text of the message the button was attached to. It also fetches the user's preferred_language.

3.  Execution: Bot calls POST /api/ai/v1/promptic passing:

-   prompt_name (e.g., "study_notes")

-   input_variables (the target text AND the target_language to ensure output is generated in Persian if requested).

-   webhook_url

-   blocking=false

1.  Delivery: via webhook callback, bot receives the structured output (in Persian/English), renders it (often as a Markdown file for study notes), and sends it to the user.

6\. Menu, Settings & Account Flows
----------------------------------

### 6.1 Main Menu

Accessible via persistent keyboard or /menu.

-   My Account / حساب کاربری: Bot fetches user profile and credit balance from USSO/Billing and displays it.

-   Buy Credits / خرید اعتبار: Bot fetches available packages from Shop/Billing. User selects a package, bot provides a payment link. Upon successful payment (via Shop webhook to Billing), the bot notifies the user of their new balance.

-   Help / راهنما: Bot sends a concise, localized help message detailing supported input formats.

-   Settings / تنظیمات: Opens the Settings submenu.

### 6.2 Settings & Localization Flow

Goal: Allow users to explicitly manage their experience, particularly their language preferences.

1.  Trigger: User selects Settings from the Main Menu.

2.  Options: Bot displays inline buttons for configurations:

-   [Language / زبان]

-   (Future: Default AI Model selection)

1.  Language Selection: User clicks Language. Bot asks to choose between:

-   [🇮🇷 فارسی]

-   [🇬🇧 English]

1.  Save Preference: User selects فارسی. Bot saves preferred_language="fa" in the local database and syncs with USSO if necessary.

2.  Confirmation: Bot replies with: "زبان شما با موفقیت به فارسی تغییر یافت." All future UI elements, menus, and Promptic outputs will now default to Persian.

### 6.3 Error Management

All error messages must respect the user's preferred_language.

-   File Too Large:  "This file is too large to process." / "حجم فایل برای پردازش بیش از حد مجاز است."

-   Insufficient Credits:  "You do not have enough credits." / "موجودی اعتبار شما کافی نیست. لطفاً حساب خود را شارژ کنید."

-   AI Service Timeout/Error:  "The AI service encountered an issue." / "سرویس هوش مصنوعی در حال حاضر با مشکل مواجه شده است."