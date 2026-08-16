"""Telegram delivery of the daily digest using HTML formatting."""

from __future__ import annotations

import html
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from models import ALLOWED_CATEGORIES, SECTION_HEADERS

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LENGTH = 4096


def format_digest(digest: Dict[str, List[dict]]) -> str:
    """Render a categorized digest into a single Telegram-HTML string."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [f"<b>🛰️ Aerospace Opportunities Digest — {date_str}</b>"]

    for category in ALLOWED_CATEGORIES:
        items = digest.get(category, [])
        if not items:
            continue
        lines = [f"<b>{_escape(SECTION_HEADERS[category])}</b>"]
        for item in items:
            link = f'<a href="{_escape_attr(item["url"])}">{_escape(item["title"])}</a>'
            lines.append(f"• {link}")
            summary = (item.get("summary") or "").strip()
            if summary:
                lines.append(f"  <i>{_escape(summary)}</i>")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


def split_message(text: str, limit: int = MAX_MESSAGE_LENGTH) -> List[str]:
    """Split text into chunks no larger than *limit* on newline boundaries."""
    if len(text) <= limit:
        return [text]

    chunks: List[str] = []
    current = ""
    for line in text.split("\n"):
        # Hard-split any single line that is itself over the limit, whether or
        # not we have already accumulated content before it.
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]

        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate

    if current:
        chunks.append(current)
    return chunks


def send_message(token: str, chat_id: str, text: str) -> dict:
    """Send one message via the Telegram Bot API and return the API response."""
    url = TELEGRAM_API_URL.format(token=token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    response = httpx.post(url, json=payload, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API returned an error: {data}")
    return data


def send_digest(
    digest: Dict[str, List[dict]], token: str, chat_id: str
) -> int:
    """Format, split (if needed), and send the digest; returns message count."""
    text = format_digest(digest)
    chunks = split_message(text)
    for chunk in chunks:
        send_message(token, chat_id, chunk)
        logger.info("Sent Telegram message (%d chars).", len(chunk))
    return len(chunks)


def _escape(text: str) -> str:
    """Escape text content for Telegram HTML (does not escape quotes)."""
    return html.escape(text, quote=False)


def _escape_attr(text: str) -> str:
    """Escape an attribute value for Telegram HTML (also escapes quotes)."""
    return html.escape(text, quote=True)


# ---------------------------------------------------------------------------
# Command handling (basic /start, /latest, /help interface)
# ---------------------------------------------------------------------------
START_REPLY = "Welcome to R3 Aerospace Digest! Use /latest to view recent opportunities."
HELP_REPLY = "Available commands: /start, /latest, /help"


def _latest_digest() -> str:
    """Return the cached digest, importing main lazily to avoid an import cycle."""
    from main import get_latest_digest  # deferred: main.py imports this module

    return get_latest_digest()


def build_reply(text: str) -> str | None:
    """Map an incoming message to a reply, or None if it is not a command."""
    stripped = (text or "").strip()
    if not stripped:
        return None
    command = stripped.split()[0].split("@")[0].lower()
    if command == "/start":
        return f"{START_REPLY}\n\n{_latest_digest()}"
    if command == "/latest":
        return _latest_digest()
    if command == "/help":
        return HELP_REPLY
    return None


def handle_update(update: dict, token: str) -> bool:
    """Dispatch a single getUpdates update; send a reply if it is a command."""
    message = update.get("message") or {}
    text = message.get("text")
    chat_id = message.get("chat", {}).get("id")
    if not text or chat_id is None:
        return False
    reply = build_reply(text)
    if reply is None:
        return False
    for chunk in split_message(reply):
        send_message(token, str(chat_id), chunk)
    return True


def run_polling(token: str, timeout: int = 30) -> None:
    """Long-poll getUpdates and handle commands until interrupted."""
    offset = 0
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    while True:
        try:
            response = httpx.post(
                url,
                json={"offset": offset, "timeout": timeout},
                timeout=timeout + 10,
            )
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                logger.error("getUpdates returned an error: %s", data)
                time.sleep(5)
                continue
            for update in data.get("result", []):
                offset = max(offset, int(update.get("update_id", 0)) + 1)
                try:
                    handle_update(update, token)
                except Exception as exc:
                    logger.exception("Failed to handle an update: %s", exc)
        except httpx.HTTPError as exc:
            logger.warning("getUpdates request failed: %s", exc)
            time.sleep(5)


if __name__ == "__main__":
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set.")
    run_polling(bot_token)
