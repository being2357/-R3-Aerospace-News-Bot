"""Telegram delivery of the daily digest using HTML formatting."""

from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Dict, List

import httpx

from models import ALLOWED_CATEGORIES

logger = logging.getLogger(__name__)

TELEGRAM_API_URL = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_LENGTH = 4096

SECTION_HEADERS = {
    "aerospace": "🚀 Aerospace & Spaceflight",
    "aeronautics": "✈️ Aeronautics & Aviation",
    "competitions": "🏆 Competitions & Events",
}


def format_digest(digest: Dict[str, List[dict]]) -> str:
    """Render a categorized digest into a single Telegram-HTML string."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    blocks = [f"<b>🛰️ Aerospace Daily Digest — {date_str}</b>"]

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
