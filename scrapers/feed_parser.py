"""RSS/Atom ingestion using ``feedparser``.

The feed is fetched with ``httpx`` (for timeouts and retries) and then handed
to ``feedparser`` for parsing, which tolerates both RSS and Atom formats.
"""

from __future__ import annotations

import logging
import re
from typing import List

import feedparser

from models import Article
from scrapers.http_utils import fetch_url

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags from a feed summary and collapse whitespace."""
    text = _HTML_TAG_RE.sub(" ", text or "")
    return " ".join(text.split())


def fetch_articles(source: dict) -> List[Article]:
    """Fetch and parse a single RSS/Atom source into normalized Articles."""
    url = source["url"]
    name = source.get("name") or source.get("id") or url
    category = source.get("category", "aerospace")

    response = fetch_url(url)
    feed = feedparser.parse(response.content)

    # feedparser reports malformed feeds via the "bozo" flag; log and continue.
    if getattr(feed, "bozo", False):
        logger.warning(
            "Feed %s may be malformed: %s",
            url, getattr(feed, "bozo_exception", "unknown"),
        )

    articles: List[Article] = []
    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        published = entry.get("published") or entry.get("updated") or None
        description = _strip_html(
            entry.get("summary") or entry.get("description") or ""
        )
        articles.append(
            Article(
                title=title,
                url=link,
                source=name,
                category=category,
                published=published,
                description=description or None,
            )
        )

    logger.debug("Parsed %d entry/entries from %s", len(articles), url)
    return articles
