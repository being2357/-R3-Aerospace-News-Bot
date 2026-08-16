"""Shared data models for the aerospace news bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Categories must match the digest grouping used across the project.
# Any source whose category is not in this list is defaulted to "aerospace".
ALLOWED_CATEGORIES = ("aerospace", "aeronautics", "competitions")


@dataclass
class Article:
    """A normalized news article scraped from a source."""

    title: str
    url: str
    source: str
    category: str = "aerospace"
    published: Optional[str] = None

    def __post_init__(self) -> None:
        self.title = (self.title or "").strip()
        self.url = (self.url or "").strip()
        self.source = (self.source or "").strip()
        self.category = (self.category or "aerospace").strip().lower()
