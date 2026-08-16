# R3 Aerospace News Bot

A production-ready Python bot that aggregates aerospace, aeronautics, and
competitions/events news from RSS feeds and HTML pages, logs every article to
Google Sheets, summarizes new items with the DeepSeek API, and posts a
categorized daily digest to Telegram — all run automatically on GitHub Actions.

## Features

- **Multi-source ingestion** — RSS/Atom via `feedparser`, plus an HTML fallback
  via `httpx` + `BeautifulSoup` with configurable CSS selectors.
- **Deduplication** — existing URLs are read from Column D of the Google Sheet;
  only unseen articles move forward.
- **AI summaries** — DeepSeek (OpenAI-compatible SDK) writes two-sentence
  summaries per article, grouped into three fixed categories.
- **Retry safety** — if a send fails, logged articles stay "unsent" and are
  retried on the next run.
- **Telegram delivery** — HTML-formatted digest, auto-split past Telegram's
  4096-character limit.

## Architecture

```
config/sources.json ──► scrapers/feed_parser.py   ─┐
                       scrapers/web_scraper.py     ├─► main.py ─► summarizer/ai_engine.py
                       scrapers/http_utils.py      │                    │
                                                  │                    ▼
                       storage/sheets_client.py ◄──┴────────── notifier/telegram_bot.py
```

| Path | Purpose |
|---|---|
| `config/sources.json` | Source registry (RSS + web targets) |
| `scrapers/feed_parser.py` | RSS/Atom ingestion |
| `scrapers/web_scraper.py` | HTML fallback scraper |
| `scrapers/http_utils.py` | Shared fetch with timeout/retry/User-Agent |
| `storage/sheets_client.py` | Google Sheets auth + dedup + logging |
| `summarizer/ai_engine.py` | DeepSeek summarization |
| `notifier/telegram_bot.py` | Telegram HTML delivery + message splitting |
| `main.py` | Orchestrator |
| `.github/workflows/daily_digest.yml` | Daily CRON job (18:00 UTC) |
| `models.py` | Shared `Article` dataclass + category constants |

## Prerequisites

- Python 3.10+
- A [Google Cloud](https://console.cloud.google.com/) project with a service account
- A Google Sheet
- A [Telegram bot](https://core.telegram.org/bots#how-do-i-create-a-bot)
- A [DeepSeek API key](https://platform.deepseek.com/)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in the values:

```bash
cp .env.example .env
```

For local runs, `python-dotenv` loads `.env` automatically.

### 3. Google Sheets + Service Account

1. In Google Cloud Console, create (or open) a project and
   **enable the Google Sheets API and Google Drive API**.
2. Create a **Service Account** (IAM & Admin → Service Accounts), then create a
   JSON key and download it.
3. Create a Google Sheet and **share it (Editor) with the service-account
   email** (the `client_email` field inside the JSON key).
4. Copy the **Sheet ID** from the URL into `GOOGLE_SHEET_ID`:
   `https://docs.google.com/spreadsheets/d/<THIS_PART>/edit`.
5. Base64-encode the JSON key and put it in `GCP_SERVICE_ACCOUNT_KEY`:

   **Linux/macOS:**
   ```bash
   base64 -w 0 service-account.json
   ```

   **Windows (PowerShell):**
   ```powershell
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("service-account.json"))
   ```

The bot reads/writes the **first sheet** of the workbook with these columns:

```
A: Timestamp   B: Source   C: Title   D: URL   E: Category   F: Sent Flag
```

The header row is created automatically on first run.

### 4. Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token
   into `TELEGRAM_BOT_TOKEN`.
2. Put the numeric chat/channel ID into `TELEGRAM_CHAT_ID`. For a private chat,
   message your bot and read the ID from the `getUpdates` endpoint, or add the
   bot to a channel and use the channel ID (e.g. `@mychannel`).

### 5. DeepSeek

Set `DEEPSEEK_API_KEY`. Optionally set `DEEPSEEK_MODEL` to override the default
(`deepseek-chat`), e.g. `deepseek-v4-flash`.

### 6. Configure sources

Edit `config/sources.json`. Each entry supports:

```json
{
  "id": "spacenews",
  "name": "SpaceNews",
  "type": "rss",
  "url": "https://spacenews.com/feed/",
  "category": "aerospace"
}
```

- `type` — `"rss"` or `"web"`.
- `category` — `"aerospace"`, `"aeronautics"`, or `"competitions"`.
- `css_selectors` — for `"web"` sources only. `link` (required) matches `<a>`
  elements; `title` (optional) selects the title within the anchor.

> **Note:** web selectors are site-specific and can break if a site redesigns.
> If a `web` source yields nothing, inspect the page and update its
> `css_selectors`.

## Running locally

```bash
python main.py
# or with a custom config:
python main.py --config path/to/sources.json
```

If there are no new articles, the bot exits silently (no Telegram message).
Set `LOG_LEVEL=DEBUG` for verbose output.

## GitHub Actions

1. Push this repository to GitHub.
2. In **Settings → Secrets and variables → Actions**, add these repository
   secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `DEEPSEEK_API_KEY`,
   `GCP_SERVICE_ACCOUNT_KEY`, `GOOGLE_SHEET_ID`.
3. The workflow runs daily at **18:00 UTC** (`0 18 * * *`) and can also be
   triggered manually via **Actions → Run workflow**.

> Note: GitHub Actions schedules are approximate and can be delayed by minutes;
> the cron time is always interpreted in UTC.

## Error handling

- **Network failures** — every outbound request uses timeouts and retries with
  backoff; one failing source never crashes the whole run.
- **Empty/invalid feeds** — logged and skipped.
- **DeepSeek failure** — the bot falls back to a titles-and-links-only digest
  so the day's news is still delivered.
- **Telegram failure** — the run exits non-zero (visible in Actions) and the
  articles remain "unsent" so they are retried on the next run.
- **Auth failures** — raised with a clear message (e.g. "share the sheet with
  the service-account email").

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `Could not open the Google Sheet` | Sheet not shared with the service-account email, or wrong `GOOGLE_SHEET_ID`. |
| `Failed to decode GCP_SERVICE_ACCOUNT_KEY` | The value isn't valid Base64 of a service-account JSON. |
| `DEEPSEEK_API_KEY is not set` | Missing secret / `.env` entry. |
| `Telegram API returned an error` | Wrong `TELEGRAM_CHAT_ID` or token. |
| No message, no error | No new articles — this is the expected silent exit. |
