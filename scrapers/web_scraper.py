"""HTML scraping fallback for sources without an RSS/Atom feed."""

from __future__ import annotations

import logging
from typing import List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from models import Article
from scrapers.http_utils import fetch_url

logger = logging.getLogger(__name__)


def fetch_articles(source: dict) -> List[Article]:
    """Scrape article links from an HTML page using configured CSS selectors.

    Expected ``css_selectors`` config:
        * ``link``  (required): CSS selector matching ``<a>`` elements.
        * ``title`` (optional): selector *within* the anchor for the title
          text; when omitted, the anchor's own text is used.
    """
    url = source["url"]
    name = source.get("name") or source.get("id") or url
    category = source.get("category", "aerospace")
    selectors = source.get("css_selectors") or {}

    link_selector = selectors.get("link")
    if not link_selector:
        logger.warning("Source '%s' has no 'link' css_selector; skipping.", name)
        return []

    title_selector = selectors.get("title")

    response = fetch_url(url)
    soup = BeautifulSoup(response.text, "html.parser")

    articles: List[Article] = []
    seen_urls: Set[str] = set()

    for anchor in soup.select(link_selector):
        href = anchor.get("href")
        if not href:
            continue
        absolute_url = urljoin(url, href)

        title = _extract_title(anchor, title_selector)
        if not title or absolute_url in seen_urls:
            continue

        seen_urls.add(absolute_url)
        articles.append(
            Article(title=title, url=absolute_url, source=name, category=category)
        )

    logger.debug("Scraped %d article(s) from %s", len(articles), url)
    return articles


def _extract_title(anchor, title_selector: Optional[str]) -> str:
    """Pull a clean title from an anchor element."""
    if title_selector:
        node = anchor.select_one(title_selector)
        if node:
            text = node.get_text(" ", strip=True)
            if text:
                return text
    return anchor.get_text(" ", strip=True)
