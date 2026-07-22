# Mirza Bot — Multi-Messenger AI Gateway

یک gateway هوش مصنوعی چندپیام‌رسانه که به عنوان **Thin Client** برای سرویس‌های پشتیبان (عمدتاً ai-toolkit) عمل می‌کند. هوش مصنوعی مستقیماً در این پروژه اجرا نمی‌شود.

---

## معماری

```
Telegram (Telethon/MTProto) ─┐
                              ├──→ Mirza Bot (Thin Client) ──→ AI Toolkit
Bale (telebot polling)  ─────┘         │                           │
                                        ├── USSO (احراز هویت)       ├── OCR / Document Intelligence
                                        ├── Media Service (آپلود)   ├── Transcribe (Soniox)
                                        ├── Shop (کیف پول)          ├── Chat / Promptic
                                        └── Redis (pending tasks)   ├── YouTube / Webpage
                                                                    └── Translate
```

سه لایه اصلی:

| لایه | فناوری | وظیفه |
|------|--------|-------|
| **Transport** | Telethon (Telegram) / telebot (Bale) | دریافت رویدادهای پیام‌رسان، دانلود فایل |
| **Common** | Handler → Orchestrator → Delivery | تشخیص نوع محتوا، مسیریابی، تحویل نتیجه |
| **Domain** | Clients → ai-toolkit API | OCR، Transcribe، Chat، Promptic |

---

## قابلیت‌های کنونی

### پیام‌رسان‌ها
- **Telegram** — Telethon/MTProto (پشتیبانی از فایل تا ۲GB)
- **Bale** — telebot/AsyncTeleBot با long-polling

### پردازش محتوا
- **OCR** — تشخیص layout با PP-DocLayoutV2+V3، استخراج متن با VLM، خروجی Markdown + DOCX
- **Transcribe** — Soniox API (خودکار تشخیص زبان، chunking برای فایل‌های طولانی)
- **Chat** — stateless با reply-chain context
- **Promptic Actions** — خلاصه‌سازی، ترجمه، ساختاردهی، کوئیز، صورت‌جلسه
- **YouTube** — استخراج زیرنویس
- **Webpage** — Jina Reader

### Document Intelligence Pipeline (در حال توسعه)
جایگزینی OCR ساده با یک pipeline کامل:

```
Document Loader → Layout Detection (V2+V3 ensemble) → Element Processing
→ Reading Order → Document AST → Markdown/DOCX Renderers
```

- تشخیص layout با **دو مدل هم‌زمان** (PP-DocLayoutV2 + V3) و ادغام با IOU dedup
- استخراج **متن، جدول، فرمول، تصویر، نمودار** هرکدام با VLM مجزا
- خروجی **Markdown استاندارد** و **DOCX واقعی** با OMML (Office Math) برای فرمول‌ها
- **Font Detection** از PDF → B Nazanin (فارسی) / Calibri (انگلیسی)
- **Asset Manager** — ذخیره تصاویر مجزا

---

## شروع سریع

```bash
# پیش‌نیاز: MongoDB + Redis + Traefik
cp sample.env .env   # ویرایش توکن‌ها و کلیدها
docker compose up -d --build
```

### متغیرهای محیطی کلیدی

| متغیر | توضیح |
|-------|-------|
| `TELEGRAM_TOKEN` | توکن ربات تلگرام |
| `BALE_BOT_TOKEN` | توکن ربات بله |
| `AI_API_KEY` | API Key برای ai-toolkit |
| `USSO_BASE_URL` | آدرس سرویس USSO |
| `AI_TOOLKIT_BASE_URL` | آدرس ai-toolkit |

---

## پروژه‌های وابسته

| پروژه | نقش |
|-------|-----|
| [ai-toolkit](https://toolkit.uln.me) | سرویس مرکزی AI (OCR، Transcribe، Chat، Promptic) |
| USSO (usso.uln.me) | احراز هویت یکپارچه |
| Media Service (media.uln.me) | آپلود و مدیریت فایل |
| Shop/Finance | کیف پول و صورت‌حساب |

---

## توسعه

```bash
# نصب وابستگی‌ها
cd app && uv sync

# اجرای محلی
uv run python main.py

# تست
uv run pytest
```

هر کامیت پس از build شدن روی `mirza.uln.me` (و `toolkit.uln.me` برای ai-toolkit) مستقر می‌شود.
