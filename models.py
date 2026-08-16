"""Shared data models and constants for the aerospace opportunities bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# The three strict output sections. Each source carries a *hint* drawn from
# this list, but the DeepSeek classifier re-assigns every article and discards
# anything that fits none of these (see summarizer.ai_engine).
ALLOWED_CATEGORIES = ("internships", "competitions", "conferences")

# Rendered section headers, shared by the Telegram notifier.
SECTION_HEADERS = {
    "internships": "🎓 Internships & Student Opportunities",
    "competitions": "🏆 Competitions & Hackathons",
    "conferences": "📅 Conferences & Upcoming Events",
}


@dataclass
class Article:
    """A normalized news item scraped from a source."""

    title: str
    url: str
    source: str
    category: str = "internships"
    published: Optional[str] = None
    description: Optional[str] = None

    def __post_init__(self) -> None:
        self.title = (self.title or "").strip()
        self.url = (self.url or "").strip()
        self.source = (self.source or "").strip()
        self.category = (self.category or "internships").strip().lower()
        self.description = (self.description or "").strip() or None
