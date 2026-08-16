"""Daily aerospace news digest orchestrator.

Flow:
    load config -> authenticate Sheets -> scrape sources -> dedupe ->
    retry unsent -> summarize (DeepSeek) -> log to Sheets -> post to Telegram.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import List

from dotenv import load_dotenv

from models import ALLOWED_CATEGORIES, Article
from notifier import telegram_bot
from scrapers import feed_parser, web_scraper
from storage.sheets_client import SheetsClient
from summarizer.ai_engine import AIEngine

logger = logging.getLogger("main")


def setup_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate, summarize, and post aerospace news."
    )
    parser.add_argument(
        "--config",
        default="config/sources.json",
        help="Path to the sources JSON config (default: config/sources.json)",
    )
    return parser.parse_args()


def load_sources(path: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    sources = data.get("sources", [])
    if not sources:
        logger.error("No sources defined in %s", path)
    return sources


def normalize_source(source: dict) -> dict:
    source = dict(source)
    category = source.get("category", "aerospace")
    if category not in ALLOWED_CATEGORIES:
        logger.warning(
            "Source '%s' has unknown category '%s'; defaulting to 'aerospace'.",
            source.get("name"), category,
        )
        category = "aerospace"
    source["category"] = category
    return source


def scrape_source(source: dict) -> List[Article]:
    if source.get("type") == "rss":
        return feed_parser.fetch_articles(source)
    if source.get("type") == "web":
        return web_scraper.fetch_articles(source)
    logger.warning("Unknown source type '%s'; skipping.", source.get("type"))
    return []


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        logger.error("Required environment variable %s is not set.", name)
        sys.exit(1)
    return value


def main() -> None:
    load_dotenv()
    setup_logging()
    args = parse_args()

    sources = [normalize_source(s) for s in load_sources(args.config)]
    if not sources:
        sys.exit(1)

    sheet_id = require_env("GOOGLE_SHEET_ID")
    service_account_key = require_env("GCP_SERVICE_ACCOUNT_KEY")
    telegram_token = require_env("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = require_env("TELEGRAM_CHAT_ID")
    deepseek_key = os.getenv("DEEPSEEK_API_KEY")

    # 1. Google Sheets: authenticate and load existing URLs for dedup.
    sheets = SheetsClient(service_account_key, sheet_id)
    sheets.ensure_header()
    existing_urls = sheets.get_existing_urls()
    logger.info("Loaded %d existing URL(s) from the sheet.", len(existing_urls))

    # 2. Scrape every configured source, isolating failures per source.
    scraped: List[Article] = []
    for source in sources:
        try:
            articles = scrape_source(source)
            logger.info(
                "Source '%s': %d article(s) fetched.",
                source.get("name"), len(articles),
            )
            scraped.extend(articles)
        except Exception as exc:
            logger.exception("Failed to scrape '%s': %s", source.get("name"), exc)

    # 3. Deduplicate fresh articles against the sheet and within this run.
    fresh: List[Article] = []
    seen: set = set()
    for article in scraped:
        if article.url in existing_urls or article.url in seen:
            continue
        seen.add(article.url)
        fresh.append(article)

    # 4. Retry articles previously logged but never successfully sent.
    unsent = sheets.get_unsent_articles()
    to_process = list(fresh)
    for article in unsent:
        if article.url not in seen:
            seen.add(article.url)
            to_process.append(article)

    logger.info(
        "Fresh articles: %d, retry queue: %d.", len(fresh), len(unsent)
    )
    if not to_process:
        logger.info("No new articles to send. Exiting silently.")
        return

    # 5. Summarize via DeepSeek (falls back to titles-only on failure).
    engine = AIEngine(deepseek_key)
    digest = engine.build_digest(to_process)

    # 6. Log fresh articles to the sheet (Sent Flag = 'No' until posted).
    sheets.append_articles(fresh, sent=False)

    # 7. Post to Telegram, then mark everything as sent.
    try:
        sent_count = telegram_bot.send_digest(
            digest, telegram_token, telegram_chat_id
        )
        logger.info("Sent %d Telegram message(s).", sent_count)
        sheets.mark_sent(to_process)
        logger.info("Marked %d article(s) as sent.", len(to_process))
    except Exception as exc:
        logger.exception("Failed to post digest to Telegram: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
        sys.exit(1)
