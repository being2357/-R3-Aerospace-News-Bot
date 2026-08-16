"""DeepSeek-powered article summarization via the OpenAI-compatible SDK.

DeepSeek exposes an OpenAI-compatible API, so we initialize the OpenAI client
with ``base_url="https://api.deepseek.com"``.
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
    "You are a professional aerospace industry news editor. "
    "Summarize each supplied article in exactly two concise, factual sentences "
    "suitable for a daily digest. Do not invent facts. Respond with STRICT JSON "
    "only (no markdown fences, no commentary) in this exact shape:\n"
    '{"articles": [{"id": 0, "summary": "Two sentences."}]}\n'
    "Include every article id exactly once."
)


class AIEngine:
    """Summarizes a batch of articles into per-category digests."""

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
        """Return ``{category: [{title, url, summary}]}`` grouped by category.

        Grouping is deterministic by each article's configured ``category``;
        DeepSeek only supplies the two-sentence summaries. If summarization
        fails, summaries are empty and the caller can fall back to titles-only.
        """
        digest: Dict[str, List[dict]] = {cat: [] for cat in ALLOWED_CATEGORIES}

        for start in range(0, len(articles), MAX_ARTICLES_PER_CALL):
            chunk = articles[start : start + MAX_ARTICLES_PER_CALL]
            summaries = self._summarize_chunk(chunk)
            for index, article in enumerate(chunk):
                category = (
                    article.category
                    if article.category in ALLOWED_CATEGORIES
                    else "aerospace"
                )
                digest[category].append(
                    {
                        "title": article.title,
                        "url": article.url,
                        "summary": summaries.get(index, "").strip(),
                    }
                )

        return digest

    def _summarize_chunk(self, articles: List[Article]) -> Dict[int, str]:
        """Summarize one chunk; returns ``{article_index: summary}``.

        Returns an empty mapping on any failure so the caller can fall back to
        a titles-only digest rather than crashing the whole run.
        """
        payload = [
            {"id": i, "title": a.title, "url": a.url, "category": a.category}
            for i, a in enumerate(articles)
        ]
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.3,
            )
            content = response.choices[0].message.content or ""
            data = _extract_json(content)
        except Exception as exc:
            logger.exception(
                "DeepSeek summarization failed; using empty summaries for this batch."
            )
            return {}

        return self._normalize(data, articles)

    @staticmethod
    def _normalize(data, articles: List[Article]) -> Dict[int, str]:
        """Map the model's ``{id: summary}`` response onto real article indices."""
        summaries: Dict[int, str] = {}
        raw_items = data.get("articles", []) if isinstance(data, dict) else []
        for item in raw_items:
            if isinstance(item, dict) and "id" in item:
                idx = item["id"]
                if isinstance(idx, int) and 0 <= idx < len(articles):
                    summaries[idx] = str(item.get("summary") or "").strip()
        return summaries


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
