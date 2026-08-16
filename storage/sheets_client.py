"""Google Sheets persistence backed by a service account.

Authentication is driven by a Base64-encoded service-account JSON string held
in the ``GCP_SERVICE_ACCOUNT_KEY`` environment variable, which keeps multi-line
key material clean inside GitHub Actions secrets.

Sheet layout (columns):
    A: Timestamp   B: Source   C: Title   D: URL   E: Category   F: Sent Flag
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import List, Set

import gspread

from models import Article

logger = logging.getLogger(__name__)

HEADERS = ["Timestamp", "Source", "Title", "URL", "Category", "Sent Flag"]
URL_COLUMN = 4      # Column D
SENT_COLUMN = 6     # Column F
SENT_YES = "Yes"
SENT_NO = "No"


def _column_letter(col: int) -> str:
    """Convert a 1-indexed column number to A1 notation (e.g. 6 -> 'F')."""
    letters = ""
    while col > 0:
        col, remainder = divmod(col - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


class SheetsClient:
    """Wraps a single Google Sheet worksheet for the news log."""

    def __init__(self, service_account_b64: str, sheet_id: str) -> None:
        if not service_account_b64:
            raise ValueError("GCP_SERVICE_ACCOUNT_KEY is empty or missing.")
        if not sheet_id:
            raise ValueError("GOOGLE_SHEET_ID is empty or missing.")
        self._sheet_id = sheet_id
        self._client = self._authenticate(service_account_b64)
        self._worksheet = self._open_worksheet()

    # -- setup ------------------------------------------------------------

    def _authenticate(self, service_account_b64: str):
        try:
            raw = base64.b64decode(service_account_b64, validate=True)
            service_account = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise ValueError(
                f"Failed to decode GCP_SERVICE_ACCOUNT_KEY: {exc}"
            ) from exc
        return gspread.service_account_from_dict(service_account)

    def _open_worksheet(self):
        try:
            spreadsheet = self._client.open_by_key(self._sheet_id)
        except Exception as exc:
            raise RuntimeError(
                "Could not open the Google Sheet. Confirm GOOGLE_SHEET_ID is "
                "correct and that the service-account email has Editor access "
                "to the sheet."
            ) from exc
        return spreadsheet.sheet1

    def ensure_header(self) -> None:
        """Write the header row if the sheet is empty."""
        first_row = self._worksheet.row_values(1)
        if not any(cell.strip() for cell in first_row):
            self._worksheet.update(
                "A1:F1", [HEADERS], value_input_option="USER_ENTERED"
            )

    # -- reads ------------------------------------------------------------

    def get_existing_urls(self) -> Set[str]:
        """Return the set of URLs already logged in Column D (skips header)."""
        values = self._worksheet.col_values(URL_COLUMN)
        urls: Set[str] = set()
        for value in values[1:]:
            value = str(value or "").strip()
            if value:
                urls.add(value)
        return urls

    def get_unsent_articles(self) -> List[Article]:
        """Return logged articles whose Sent Flag is not 'Yes' (retry queue)."""
        records = self._worksheet.get_all_values()
        articles: List[Article] = []
        for row in records[1:]:  # skip header row
            if len(row) < SENT_COLUMN:
                continue
            sent = str(row[SENT_COLUMN - 1] or "").strip()
            url = str(row[URL_COLUMN - 1] or "").strip()
            title = str(row[2] or "").strip()
            if url and title and sent != SENT_YES:
                articles.append(
                    Article(
                        title=title,
                        url=url,
                        source=str(row[1] or ""),
                        category=str(row[4] or "aerospace"),
                    )
                )
        return articles

    # -- writes -----------------------------------------------------------

    def append_articles(self, articles: List[Article], sent: bool = False) -> None:
        """Append rows [Timestamp, Source, Title, URL, Category, Sent Flag]."""
        if not articles:
            return
        flag = SENT_YES if sent else SENT_NO
        rows = [
            [self._now(), a.source, a.title, a.url, a.category, flag]
            for a in articles
        ]
        self._worksheet.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info("Appended %d article(s) to sheet.", len(articles))

    def mark_sent(self, articles: List[Article]) -> None:
        """Set the Sent Flag (Column F) to 'Yes' for the given articles."""
        if not articles:
            return
        url_to_row = {}
        for index, value in enumerate(self._worksheet.col_values(URL_COLUMN)):
            value = str(value or "").strip()
            if value and value not in url_to_row:
                url_to_row[value] = index + 1  # 1-indexed row numbers

        # Build a single batch update instead of one API call per cell.
        updates = []
        for article in articles:
            row = url_to_row.get(article.url)
            if row:
                updates.append(
                    {
                        "range": f"{_column_letter(SENT_COLUMN)}{row}",
                        "values": [[SENT_YES]],
                    }
                )

        if updates:
            self._worksheet.batch_update(updates, value_input_option="USER_ENTERED")
            logger.info("Marked %d article(s) as sent.", len(updates))

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")
