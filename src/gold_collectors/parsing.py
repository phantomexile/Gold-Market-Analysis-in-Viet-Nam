from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from typing import Any


def normalize_date(value: str | date | datetime) -> tuple[str, str]:
    """Return (dd/mm/yyyy, iso-date)."""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y"), value.date().isoformat()
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y"), value.isoformat()

    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            return parsed.strftime("%d/%m/%Y"), parsed.isoformat()
        except ValueError:
            pass
    raise ValueError(f"Unsupported date format: {value!r}")


def normalize_webgia_date(value: str | date | datetime) -> tuple[str, str]:
    _, iso_date = normalize_date(value)
    parsed = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return parsed.strftime("%d-%m-%Y"), iso_date


def parse_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    match = re.search(r"-?[\d,.]+", text)
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." in token:
        token = token.replace(",", "")
    elif "," in token and "." not in token:
        token = token.replace(",", "")
    return float(token)


def parse_dotnet_date(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"/Date\((-?\d+)\)/", value)
    if not match:
        return None
    millis = int(match.group(1))
    if millis < 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()


class TableParser(HTMLParser):
    """Minimal table parser that returns rows as stripped cell text."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._in_cell = False
        self._current_cell: list[str] = []
        self._current_row: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._in_cell = True
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell and self._current_row is not None:
            text = " ".join("".join(self._current_cell).split())
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._current_row is not None:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = None


def extract_table_rows(html: str) -> list[list[str]]:
    parser = TableParser()
    parser.feed(html)
    return parser.rows
