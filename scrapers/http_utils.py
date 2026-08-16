"""Shared HTTP fetching with timeouts, retries, and a polite User-Agent."""

from __future__ import annotations

import logging
import time
from typing import Final

import httpx

logger = logging.getLogger(__name__)

USER_AGENT: Final[str] = (
    "Mozilla/5.0 (compatible; AerospaceNewsBot/1.0; +https://github.com/)"
)

DEFAULT_TIMEOUT: Final[float] = 20.0
DEFAULT_RETRIES: Final[int] = 3
BACKOFF_BASE_SECONDS: Final[float] = 2.0


def fetch_url(
    url: str,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> httpx.Response:
    """GET *url* and return the response, retrying transient failures.

    Raises ``httpx.HTTPError`` if every attempt fails.
    """
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            logger.warning(
                "Request to %s failed (attempt %d/%d): %s",
                url, attempt, retries, exc,
            )
            if attempt < retries:
                time.sleep(BACKOFF_BASE_SECONDS ** attempt)

    if last_error is None:
        raise httpx.ConnectError(f"Failed to fetch {url}")
    raise last_error
