"""DeepSeek classification + summarization via the OpenAI-compatible SDK.

DeepSeek exposes an OpenAI-compatible API, so we initialize the OpenAI client
with ``base_url="https://api.deepseek.com"``. The model is instructed to assign
each article to exactly one of three strict sections and discard anything that
does not fit; the engine returns a per-section digest keyed by the categories
in ``models.ALLOWED_CATEGORIES``.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Dict, List, Optional

from openai import OpenAI

from models import ALLOWED_CATEGORIES, Article

logger = logging.getLogger(__name__)

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
MAX_ARTICLES_PER_CALL = 40  # keep each request well within context limits

_SYSTEM_PROMPT = (
    "You are a strict editor compiling a daily digest of aerospace-adjacent "
    "opportunities for students and young professionals. Classify each supplied "
    "article into EXACTLY ONE of three sections:\n"
    "  - 🎓 Internships & Student Opportunities\n"
    "  - 🏆 Competitions & Hackathons\n"
    "  - 📅 Conferences & Upcoming Events\n"
    "Rules:\n"
    "  1. If an article does not clearly fit one of these three categories, "
    "DISCARD it completely — do not include it anywhere in the output.\n"
    "  2. For every kept article, write exactly two concise, factual sentences. "
    "Do not invent facts.\n"
    "  3. Ignore navigation links, photo-of-the-day items, general space news, "
    "exoplanet discoveries, and historical anniversaries.\n"
    "Respond with STRICT JSON only (no markdown fences, no commentary) in this "
    "exact shape:\n"
    '{"internships":[{"id":0,"summary":"Two sentences."}],'
    '"competitions":[{"id":1,"summary":"Two sentences."}],'
    '"conferences":[{"id":2,"summary":"Two sentences."}]}\n'
    "Each kept article id appears in exactly one section; discarded ids are "
    "simply omitted. The three top-level keys must always be present, even if "
    "their arrays are empty."
    "DISCARD all general news for example rocket launches, exoplanet discoveries, comet photos, historical anniversaries, company profiles, website legal pages)."
    " If no items match these criteria, respond with: No new opportunities, competitions, or events found today."
)


class AIEngine:
    """Classifies and summarizes a batch of articles into per-section digests."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ) -> None:
        api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        self._client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
        self._model = model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL

    def build_digest(self, articles: List[Article]) -> Dict[str, List[dict]]:
        """Return ``{section: [{title, url, summary}]}`` for kept articles only."""
        digest: Dict[str, List[dict]] = {cat: [] for cat in ALLOWED_CATEGORIES}

        for start in range(0, len(articles), MAX_ARTICLES_PER_CALL):
            chunk = articles[start : start + MAX_ARTICLES_PER_CALL]
            classified = self._classify_chunk(chunk)
            if classified is None:
                # API failure -> deterministic titles-only fallback by hint.
                self._apply_fallback(digest, chunk)
                continue
            for section, items in classified.items():
                for item in items:
                    idx = item.get("id")
                    if isinstance(idx, int) and 0 <= idx < len(chunk):
                        article = chunk[idx]
                        digest[section].append(
                            {
                                "title": article.title,
                                "url": article.url,
                                "summary": str(item.get("summary") or "").strip(),
                            }
                        )
        return digest

    def _apply_fallback(
        self, digest: Dict[str, List[dict]], articles: List[Article]
    ) -> None:
        """Route each article to its configured category with an empty summary."""
        for article in articles:
            category = (
                article.category
                if article.category in ALLOWED_CATEGORIES
                else "internships"
            )
            digest[category].append(
                {"title": article.title, "url": article.url, "summary": ""}
            )

    def _classify_chunk(
        self, articles: List[Article]
    ) -> Optional[Dict[str, List[dict]]]:
        """Return ``{section: [{id, summary}]}``, or ``None`` on any failure."""
        payload = [
            {"id": i, "title": a.title, "description": a.description or a.title}
            for i, a in enumerate(articles)
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
            )
            content = response.choices[0].message.content or ""
            data = _extract_json(content)
        except Exception:
            logger.exception(
                "DeepSeek classification failed; using titles-only fallback."
            )
            return None
        return self._normalize(data, len(articles))

    @staticmethod
    def _normalize(data, count: int) -> Dict[str, List[dict]]:
        """Keep only well-formed items whose ``id`` maps to a real article."""
        result: Dict[str, List[dict]] = {cat: [] for cat in ALLOWED_CATEGORIES}
        if not isinstance(data, dict):
            return result
        for section in ALLOWED_CATEGORIES:
            items = data.get(section)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                idx = item.get("id")
                if isinstance(idx, int) and 0 <= idx < count:
                    result[section].append(
                        {"id": idx, "summary": item.get("summary") or ""}
                    )
        return result


def _extract_json(text: str) -> dict:
    """Parse a JSON object out of a model response, tolerating markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return json.loads(text[start : end + 1])
