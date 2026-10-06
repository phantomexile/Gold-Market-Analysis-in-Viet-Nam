from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib import parse, request
from xml.etree import ElementTree

from .collectors import DojiCurrentHtmlCollector, PnjCurrentCollector, SjcOfficialCollector, ThirdPartyArchiveCollector
from .full_pipeline import DataLakeWriter
from .http import CachedHttpClient, CollectorHttpError, HttpResponse
from .models import GoldPriceRecord
from .parsing import extract_table_rows, normalize_date, normalize_webgia_date, parse_number


AUDIT_DATES = [
    "2011-07-06",
    "2013-11-18",
    "2016-06-24",
    "2020-03-16",
    "2022-03-08",
    "2024-04-12",
    "2026-07-06",
]

STATUS_HISTORICAL_VALID = "historical_valid"
STATUS_CURRENT_ONLY = "current_only"
STATUS_UNSTABLE = "unstable"
STATUS_MANUAL_OR_ARCHIVE = "manual_or_archive"


@dataclass(frozen=True)
class AuditRecord:
    source: str
    requested_date: str
    business_date: str | None
    status: str
    records: int
    sample_buy: float | None = None
    sample_sell: float | None = None
    raw_hash: str | None = None
    note: str = ""


@dataclass(frozen=True)
class RegistryRecord:
    source: str
    role: str
    status: str
    coverage: str
    supports_historical: bool
    requires_playwright: bool
    parser_status: str
    reliability_score: float
    notes: str


def to_yaml(records: list[RegistryRecord]) -> str:
    lines = ["sources:"]
    for item in records:
        lines.extend(
            [
                f"  - source: {item.source}",
                f"    role: {item.role}",
                f"    status: {item.status}",
                f"    coverage: {json.dumps(item.coverage, ensure_ascii=False)}",
                f"    supports_historical: {str(item.supports_historical).lower()}",
                f"    requires_playwright: {str(item.requires_playwright).lower()}",
                f"    parser_status: {item.parser_status}",
                f"    reliability_score: {item.reliability_score:.2f}",
                f"    notes: {json.dumps(item.notes, ensure_ascii=False)}",
            ]
        )
    return "\n".join(lines) + "\n"


def read_registry(path: str | Path) -> list[RegistryRecord]:
    text = Path(path).read_text(encoding="utf-8")
    blocks = [block for block in text.split("\n  - source: ") if block.strip()]
    records: list[RegistryRecord] = []
    for block in blocks:
        if block.startswith("sources:"):
            continue
        lines = block.splitlines()
        source = lines[0].strip()
        values: dict[str, str] = {"source": source}
        for line in lines[1:]:
            if ":" not in line:
                continue
            key, value = line.strip().split(":", 1)
            values[key] = value.strip()
        records.append(
            RegistryRecord(
                source=values["source"],
                role=values.get("role", ""),
                status=values.get("status", STATUS_UNSTABLE),
                coverage=json.loads(values.get("coverage", "\"\"")),
                supports_historical=values.get("supports_historical", "false") == "true",
                requires_playwright=values.get("requires_playwright", "false") == "true",
                parser_status=values.get("parser_status", "unknown"),
                reliability_score=float(values.get("reliability_score", "0")),
                notes=json.loads(values.get("notes", "\"\"")),
            )
        )
    return records


def date_range(start: str, end: str) -> list[str]:
    _, start_iso = normalize_date(start)
    _, end_iso = normalize_date(end)
    current = datetime.strptime(start_iso, "%Y-%m-%d").date()
    last = datetime.strptime(end_iso, "%Y-%m-%d").date()
    dates = []
    while current <= last:
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def business_date_from_record(record: GoldPriceRecord) -> str | None:
    if record.observed_at:
        try:
            parsed = datetime.fromisoformat(record.observed_at)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone(timedelta(hours=7))).date().isoformat()
        except ValueError:
            pass
    return record.reference_date


def gold_record_to_target_row(record: GoldPriceRecord, requested_date: str, source: str) -> dict[str, Any] | None:
    business_date = business_date_from_record(record)
    if business_date != requested_date:
        return None
    buy = record.buy_value
    sell = record.sell_value
    if buy is None or sell is None:
        return None
    return {
        "date": requested_date,
        "business_date": business_date,
        "timestamp": record.observed_at,
        "source": source,
        "provider": record.provider,
        "branch": clean_text(record.branch),
        "gold_type": clean_text(record.gold_type),
        "buy": buy,
        "sell": sell,
        "spread": sell - buy,
        "unit": clean_text(fix_unit(record.unit)),
        "currency": record.currency,
        "raw_hash": record.raw_payload_hash,
    }


def fix_unit(value: str) -> str:
    return {
        "VND/lÆ°á»£ng": "VND/lượng",
        "1,000 VND/chá»‰": "1,000 VND/chỉ",
    }.get(value, value)


def clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    replacements = {
        "VND/lÆ°á»£ng": "VND/lượng",
        "1,000 VND/chá»‰": "1,000 VND/chỉ",
    }
    if value in replacements:
        return replacements[value]
    repaired_by_parts = value
    for bad, good in {
        "Há»“ ChÃ­ Minh": "Hồ Chí Minh",
        "HÃ  Ná»™i": "Hà Nội",
        "Miá»n Báº¯c": "Miền Bắc",
        "Nha Trang": "Nha Trang",
        "VÃ ng": "Vàng",
        "lÆ°á»£ng": "lượng",
        "chá»‰": "chỉ",
    }.items():
        repaired_by_parts = repaired_by_parts.replace(bad, good)
    if repaired_by_parts != value:
        return repaired_by_parts
    for encoding in ("cp1252", "latin1"):
        try:
            repaired = value.encode(encoding).decode("utf-8")
            if not any(token in repaired for token in ("Ã", "Æ", "á»", "Â")):
                return repaired
        except Exception:
            pass
    return value


class SourceAuditor:
    def __init__(self, http: CachedHttpClient):
        self.http = http

    def audit(self, dates: Iterable[str]) -> list[AuditRecord]:
        rows: list[AuditRecord] = []
        audit_dates = list(dates)
        for source, fn in (
            ("sjc_official_history", self._audit_sjc_history),
            ("webgia_sjc_archive", self._audit_webgia_sjc),
            ("giavang_sjc_archive", lambda value: self._audit_giavang(value, "sjc")),
            ("giavang_pnj_archive", lambda value: self._audit_giavang(value, "pnj")),
            ("vnstock_gold_sjc", self._audit_vnstock_gold),
            ("btmc_by_day", self._audit_btmc_by_day),
            ("pnj_current", self._audit_pnj_current),
            ("doji_current", self._audit_doji_current),
            ("phu_quy_current", lambda value: self._audit_not_implemented_current(value, "phu_quy_current")),
            ("vietabank_current", lambda value: self._audit_not_implemented_current(value, "vietabank_current")),
            ("btmc_current", lambda value: self._audit_not_implemented_current(value, "btmc_current")),
            ("goldvn_24h_current", lambda value: self._audit_not_implemented_current(value, "goldvn_24h_current")),
        ):
            for requested_date in audit_dates:
                try:
                    rows.append(fn(requested_date))
                except Exception as exc:  # noqa: BLE001
                    rows.append(AuditRecord(source, requested_date, None, "error", 0, note=f"{type(exc).__name__}: {exc}"))
        return rows

    def _audit_sjc_history(self, requested_date: str) -> AuditRecord:
        records = SjcOfficialCollector(self.http).get_history(1, requested_date, requested_date)
        matched = [record for record in records if business_date_from_record(record) == requested_date]
        first = records[0] if records else None
        return AuditRecord(
            "sjc_official_history",
            requested_date,
            business_date_from_record(first) if first else None,
            "matched" if matched else "empty",
            len(records),
            first.buy_value if first else None,
            first.sell_value if first else None,
            first.raw_payload_hash if first else None,
        )

    def _audit_webgia_sjc(self, requested_date: str) -> AuditRecord:
        webgia_date, _ = normalize_webgia_date(requested_date)
        records = ThirdPartyArchiveCollector(self.http).get_webgia_sjc_history(webgia_date)
        first = records[0] if records else None
        business_date = business_date_from_record(first) if first else None
        return AuditRecord(
            "webgia_sjc_archive",
            requested_date,
            business_date,
            "matched" if business_date == requested_date and records else "empty",
            len(records),
            first.buy_value if first else None,
            first.sell_value if first else None,
            first.raw_payload_hash if first else None,
        )

    def _audit_giavang(self, requested_date: str, provider: str) -> AuditRecord:
        url = f"https://giavang.org/trong-nuoc/{provider}/lich-su/{requested_date}.html"
        response = self.http.get(url)
        if "Không tìm thấy" in response.text or "KhÃ´ng tÃ¬m tháº¥y" in response.text:
            return AuditRecord(f"giavang_{provider}_archive", requested_date, None, "empty", 0, raw_hash=response.raw_payload_hash)
        rows = extract_table_rows(response.text)
        parsed = []
        for row in rows:
            if len(row) < 4:
                continue
            buy = parse_number(row[2])
            sell = parse_number(row[3])
            if buy is None and sell is None:
                continue
            business_date = requested_date
            if len(row) > 4:
                parsed_date = parse_vietnamese_datetime_date(row[4])
                business_date = parsed_date or requested_date
            parsed.append((business_date, buy, sell))
        first = parsed[0] if parsed else None
        return AuditRecord(
            f"giavang_{provider}_archive",
            requested_date,
            first[0] if first else None,
            "matched" if first and first[0] == requested_date else "empty",
            len(parsed),
            first[1] if first else None,
            first[2] if first else None,
            response.raw_payload_hash,
        )

    def _audit_vnstock_gold(self, requested_date: str) -> AuditRecord:
        try:
            import vnstock  # type: ignore  # noqa: F401
        except Exception:
            return AuditRecord("vnstock_gold_sjc", requested_date, None, "skipped", 0, note="vnstock is not installed.")
        return AuditRecord("vnstock_gold_sjc", requested_date, None, "skipped", 0, note="vnstock installed, gold API not wired in this audit adapter.")

    def _audit_btmc_by_day(self, requested_date: str) -> AuditRecord:
        return AuditRecord("btmc_by_day", requested_date, None, "skipped", 0, note="BTMC by-day endpoint requires verification before use.")

    def _audit_pnj_current(self, requested_date: str) -> AuditRecord:
        records = PnjCurrentCollector(self.http).get_current()
        business_date = current_business_date(records[0].observed_at if records else None)
        first = records[0] if records else None
        return AuditRecord("pnj_current", requested_date, business_date, "current_leak" if records and business_date != requested_date else "matched", len(records), first.buy_value if first else None, first.sell_value if first else None, first.raw_payload_hash if first else None)

    def _audit_doji_current(self, requested_date: str) -> AuditRecord:
        records = DojiCurrentHtmlCollector(self.http).get_current()
        first = records[0] if records else None
        business_date = date.today().isoformat() if records else None
        return AuditRecord("doji_current", requested_date, business_date, "current_leak" if records and business_date != requested_date else "matched", len(records), first.buy_value if first else None, first.sell_value if first else None, first.raw_payload_hash if first else None)

    def _audit_not_implemented_current(self, requested_date: str, source: str) -> AuditRecord:
        return AuditRecord(source, requested_date, None, "skipped", 0, note="Current-only candidate listed in registry; parser not implemented yet.")


def current_business_date(value: str | None) -> str | None:
    if not value:
        return date.today().isoformat()
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month}-{day}"
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if match:
        return match.group(0)
    return date.today().isoformat()


def parse_vietnamese_datetime_date(value: str) -> str | None:
    match = re.search(r"(\d{2})/(\d{2})/(\d{4})", value)
    if not match:
        return None
    day, month, year = match.groups()
    return f"{year}-{month}-{day}"


def build_registry_from_audit(records: list[AuditRecord]) -> list[RegistryRecord]:
    grouped: dict[str, list[AuditRecord]] = {}
    for record in records:
        grouped.setdefault(record.source, []).append(record)
    registry = []
    for source, rows in grouped.items():
        matched = sum(row.status == "matched" and row.business_date == row.requested_date for row in rows)
        leaks = sum(row.status == "current_leak" for row in rows)
        errors = sum(row.status == "error" for row in rows)
        non_empty = sum(row.records > 0 for row in rows)
        total = len(rows)
        reliability = matched / total if total else 0.0
        supports_historical = matched > 0 and leaks == 0 and errors == 0
        status = STATUS_UNSTABLE
        role = "candidate"
        parser_status = "ok" if errors == 0 else "error"
        notes = ""
        if source in {"webgia_sjc_archive", "giavang_sjc_archive", "giavang_pnj_archive"}:
            status = STATUS_MANUAL_OR_ARCHIVE if matched else STATUS_UNSTABLE
            role = "archive_cross_check"
        if source == "sjc_official_history" and supports_historical:
            status = STATUS_HISTORICAL_VALID
            role = "primary_historical_label"
        elif supports_historical and source != "sjc_official_history":
            status = STATUS_HISTORICAL_VALID if source in {"vnstock_gold_sjc", "btmc_by_day"} else status
        if leaks > 0:
            status = STATUS_CURRENT_ONLY
            role = "current_cross_check"
            supports_historical = False
            reliability = 0.0
        if non_empty == 0 and errors == 0 and status != STATUS_CURRENT_ONLY:
            status = STATUS_UNSTABLE
            parser_status = "not_available"
        if source in {"phu_quy_current", "vietabank_current", "btmc_current", "goldvn_24h_current"}:
            status = STATUS_CURRENT_ONLY
            role = "current_cross_check"
            supports_historical = False
            parser_status = "not_implemented"
        if source == "btmc_by_day":
            notes = "Use only if audit verifies requested_date == business_date."
        elif source == "vnstock_gold_sjc":
            notes = "Optional; depends on vnstock module availability and function discovery."
        elif status == STATUS_CURRENT_ONLY:
            notes = "Returns current business date for old requested dates or parser is current-only."
        coverage = f"{matched}/{total} matched; {non_empty}/{total} non_empty; {leaks} current_leak; {errors} error"
        registry.append(
            RegistryRecord(
                source,
                role,
                status,
                coverage,
                supports_historical,
                False,
                parser_status,
                reliability,
                notes,
            )
        )
    return sorted(registry, key=lambda item: (item.status != STATUS_HISTORICAL_VALID, item.source))


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_parquet_or_csv(writer: DataLakeWriter, dataset: str, rows: list[dict[str, Any]]) -> None:
    writer.write_dataset(dataset, rows)


def accepted_historical_sources(registry: list[RegistryRecord]) -> set[str]:
    return {item.source for item in registry if item.supports_historical and item.status == STATUS_HISTORICAL_VALID}


def collect_historical_rows(source: str, requested_date: str, http: CachedHttpClient) -> list[dict[str, Any]]:
    if source == "sjc_official_history":
        records = SjcOfficialCollector(http).get_history(1, requested_date, requested_date)
        return [row for record in records if (row := gold_record_to_target_row(record, requested_date, source))]
    if source == "webgia_sjc_archive":
        webgia_date, _ = normalize_webgia_date(requested_date)
        records = ThirdPartyArchiveCollector(http).get_webgia_sjc_history(webgia_date)
        return [row for record in records if (row := gold_record_to_target_row(record, requested_date, source))]
    if source == "giavang_sjc_archive":
        return collect_giavang_rows("sjc", requested_date, http)
    return []


def collect_giavang_rows(provider: str, requested_date: str, http: CachedHttpClient) -> list[dict[str, Any]]:
    url = f"https://giavang.org/trong-nuoc/{provider}/lich-su/{requested_date}.html"
    response = http.get(url)
    rows = []
    if "Không tìm thấy" in response.text or "KhÃ´ng tÃ¬m tháº¥y" in response.text:
        return rows
    for table_row in extract_table_rows(response.text):
        if len(table_row) < 4:
            continue
        raw_buy = parse_number(table_row[2])
        raw_sell = parse_number(table_row[3])
        if raw_buy is None or raw_sell is None:
            continue
        # PNJ history pages sometimes have swapped column order (Sell at [2], Buy at [3]).
        # If raw_buy >> raw_sell by more than 1M, swap them.
        if raw_buy > raw_sell:
            raw_buy, raw_sell = raw_sell, raw_buy
        buy = raw_buy
        sell = raw_sell
        if buy is None or sell is None:
            continue
        business_date = requested_date
        if len(table_row) > 4:
            business_date = parse_vietnamese_datetime_date(table_row[4]) or requested_date
        if business_date != requested_date:
            continue
        rows.append(
            {
                "date": requested_date,
                "business_date": business_date,
                "timestamp": table_row[4] if len(table_row) > 4 else None,
                "source": f"giavang_{provider}_archive",
                "provider": provider.upper(),
                "branch": clean_text(table_row[0]),
                "gold_type": clean_text(table_row[1]) if len(table_row) > 1 else "",
                "buy": buy * 1_000_000 if buy < 1_000 else buy,
                "sell": sell * 1_000_000 if sell < 1_000 else sell,
                "spread": sell - buy,
                "unit": "VND/lượng",
                "currency": "VND",
                "raw_hash": response.raw_payload_hash,
            }
        )
    return rows


def collect_vietcombank_fx(http: CachedHttpClient) -> list[dict[str, Any]]:
    response = http.get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx?b=10")
    root = ElementTree.fromstring(response.text)
    rows = []
    for item in root.findall(".//Exrate"):
        transfer = parse_number(item.attrib.get("Transfer"))
        sell = parse_number(item.attrib.get("Sell"))
        rows.append(
            {
                "date": date.today().isoformat(),
                "source": "vietcombank_fx_xml",
                "pair": f"{item.attrib.get('CurrencyCode', '')}/VND",
                "buy": parse_number(item.attrib.get("Buy")) or transfer,
                "sell": sell,
                "mid": ((transfer + sell) / 2) if transfer is not None and sell is not None else None,
                "quote_type": "cash_transfer_sell",
                "raw_hash": response.raw_payload_hash,
            }
        )
    return rows


def collect_yfinance_prices(start: str, end: str) -> list[dict[str, Any]]:
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return []
    rows = []
    symbols = {
        "GC=F": ("gold_futures", "USD/toz"),
        "USDVND=X": ("usd_vnd_market", "VND/USD"),
        "^VIX": ("vix", "index"),
        "DX-Y.NYB": ("dxy", "index"),
        "^GSPC": ("sp500", "index"),
        "CL=F": ("wti_crude_futures", "USD/barrel"),
        "SI=F": ("silver_futures", "USD/toz"),
    }
    end_exclusive = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    for symbol, (asset, unit) in symbols.items():
        frame = yf.download(symbol, start=start, end=end_exclusive, progress=False, auto_adjust=False, threads=False)
        if frame.empty:
            continue
        for index, row in frame.iterrows():
            close = yfinance_row_value(row, "Close", symbol)
            if close is None:
                continue
            rows.append(
                {
                    "date": index.date().isoformat(),
                    "series_id": symbol,
                    "asset": asset,
                    "value": float(close),
                    "unit": unit,
                    "source": "yfinance",
                    "raw_hash": hashlib.sha256(f"{symbol}:{start}:{end}".encode("utf-8")).hexdigest(),
                }
            )
    return rows


def yfinance_row_value(row: Any, field: str, symbol: str) -> float | None:
    candidates = [field, (field, symbol), (field, "")]
    for key in candidates:
        try:
            value = row.get(key)
        except Exception:
            value = None
        if value is None:
            continue
        try:
            if hasattr(value, "item"):
                value = value.item()
            return float(value)
        except Exception:
            continue
    return None


def collect_worldbank_macro(http: CachedHttpClient) -> list[dict[str, Any]]:
    indicators = {
        "FP.CPI.TOTL.ZG": "Inflation, consumer prices",
        "FR.INR.LEND": "Lending interest rate",
        "PA.NUS.FCRF": "Official exchange rate",
        "NY.GDP.MKTP.KD.ZG": "GDP growth",
    }
    rows = []
    for indicator, name in indicators.items():
        response = http.get(f"https://api.worldbank.org/v2/country/VNM/indicator/{indicator}?format=json&per_page=20000")
        payload = json.loads(response.text)
        data = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        for item in data:
            rows.append(
                {
                    "date": item.get("date"),
                    "series_id": indicator,
                    "series_name": item.get("indicator", {}).get("value", name),
                    "frequency": "annual",
                    "value": item.get("value"),
                    "unit": "various",
                    "source": "worldbank_api",
                    "release_date": None,
                    "raw_hash": response.raw_payload_hash,
                }
            )
    return rows


def collect_fred_series(start: str, end: str, http: CachedHttpClient) -> list[dict[str, Any]]:
    series = ["DGS10", "DCOILWTICO", "VIXCLS", "DTWEXBGS"]
    rows = []
    for series_id in series:
        for window_start, window_end in date_range_windows(start, end, days=120):
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?{parse.urlencode({'id': series_id, 'cosd': window_start, 'coed': window_end})}"
            text, raw_hash = fetch_text_with_user_agent(url, timeout=75)
            reader = csv.DictReader(io.StringIO(text))
            for item in reader:
                value = item.get(series_id)
                if value in {"", ".", None}:
                    continue
                rows.append(
                    {
                        "date": item.get("observation_date") or item.get("DATE") or item.get("date"),
                        "series_id": series_id,
                        "asset": series_id,
                        "value": parse_number(value),
                        "unit": "various",
                        "source": "fred_csv_windowed",
                        "raw_hash": raw_hash,
                    }
                )
    return rows


def fetch_text_with_user_agent(url: str, timeout: int = 75) -> tuple[str, str]:
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0 Safari/537.36",
            "Accept": "text/csv,*/*",
            "Accept-Language": "en,vi;q=0.9",
        },
    )
    with request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        charset = resp.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace"), hashlib.sha256(raw).hexdigest()


def fetch_bytes_with_user_agent(url: str, timeout: int = 120, retries: int = 2) -> bytes:
    last_exc: Exception | None = None
    for _ in range(retries + 1):
        try:
            req = request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/149.0 Safari/537.36",
                    "Accept": "*/*",
                    "Accept-Language": "en,vi;q=0.9",
                },
            )
            with request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    if last_exc:
        raise last_exc
    raise RuntimeError("download failed without exception")


def date_range_windows(start: str, end: str, days: int = 120) -> list[tuple[str, str]]:
    current = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    windows = []
    while current <= last:
        window_end = min(last, current + timedelta(days=days - 1))
        windows.append((current.isoformat(), window_end.isoformat()))
        current = window_end + timedelta(days=1)
    return windows


def collect_optional_vnstock_features(start: str, end: str) -> list[dict[str, Any]]:
    try:
        from vnstock import Quote  # type: ignore
    except Exception:
        return []
    _INDEX_SYMBOLS: list[tuple[str, str]] = [
        ("VNINDEX",  "vnindex"),
        ("VN30",     "vn30"),
        ("HNXINDEX", "hnxindex"),
    ]
    rows: list[dict[str, Any]] = []
    for symbol, asset_name in _INDEX_SYMBOLS:
        try:
            frame = Quote(symbol=symbol, source="VCI").history(start=start, end=end)
        except Exception as exc:
            print(f"  WARN vnstock {symbol}: {type(exc).__name__}: {exc}")
            continue
        if frame is None or frame.empty:
            continue
        for _, row in frame.iterrows():
            row_date = str(row.get("time") or row.get("date") or "")[:10]
            close = row.get("close")
            if not row_date or close is None:
                continue
            rows.append(
                {
                    "date": row_date,
                    "series_id": symbol,
                    "asset": asset_name,
                    "value": float(close),
                    "unit": "index",
                    "source": "vnstock_vci",
                    "raw_hash": hashlib.sha256(
                        f"{symbol}:VCI:{start}:{end}".encode("utf-8")
                    ).hexdigest(),
                }
            )
    return rows


def collect_gso_macro_monitor_features() -> list[dict[str, Any]]:
    url = "https://github.com/thanhqtran/gso-macro-monitor/releases/download/v1.2.0/all_data_gso_20250606.json.zip"
    raw = fetch_bytes_with_user_agent(url, timeout=120, retries=2)
    raw_hash = hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        json_name = next(name for name in archive.namelist() if name.endswith(".json"))
        payload = json.loads(archive.read(json_name).decode("utf-8"))
    rows = []
    seen = set()
    for series in iter_gso_series(payload):
        series_id = series.get("@INDICATOR", "")
        domain = series.get("@DATA_DOMAIN", "")
        frequency = series.get("@FREQ", "")
        unit_mult = series.get("@UNIT_MULT", "")
        for obs in series.get("Obs", []):
            if not isinstance(obs, dict):
                continue
            period = obs.get("@TIME_PERIOD")
            value = parse_gso_number(obs.get("@OBS_VALUE"))
            if not period or value is None:
                continue
            key = (period, series_id, domain, frequency)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "date": period_to_date(period),
                    "series_id": series_id,
                    "series_name": series_id,
                    "frequency": frequency,
                    "value": value,
                    "unit": f"unit_mult_{unit_mult}" if unit_mult != "" else "",
                    "source": "gso_macro_monitor",
                    "release_date": "2025-06-06",
                    "domain": domain,
                    "period": period,
                    "raw_hash": raw_hash,
                }
            )
    return rows


def iter_gso_series(obj: Any):
    if isinstance(obj, list):
        for item in obj:
            yield from iter_gso_series(item)
    elif isinstance(obj, dict):
        if "Obs" in obj:
            yield obj
        else:
            for value in obj.values():
                yield from iter_gso_series(value)


def parse_gso_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def period_to_date(period: str) -> str:
    if "-S" in period:
        year, semester = period.split("-S", 1)
        month = {"1": "06", "2": "12"}.get(semester[:1], "12")
        return f"{year}-{month}-01"
    if "-Q" in period:
        year, q = period.split("-Q", 1)
        month = {"1": "03", "2": "06", "3": "09", "4": "12"}.get(q[:1], "12")
        return f"{year}-{month}-01"
    if len(period) == 7 and period[4] == "-":
        return f"{period}-01"
    if len(period) == 4 and period.isdigit():
        return f"{period}-12-31"
    return period[:10]


def collect_sbv_central_fx_history(start: str, end: str) -> list[dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return []

    page_url = "https://sbv.gov.vn/vi/bieu-do-ty-gia-trung-tam"
    endpoint = "/o/headless-delivery/v1.0/content-structures/137473/structured-contents"
    requested_start = datetime.strptime(start, "%Y-%m-%d").date()
    requested_end = datetime.strptime(end, "%Y-%m-%d").date()
    fetch_start = (requested_start - timedelta(days=2)).isoformat()
    fetch_end = (requested_end + timedelta(days=2)).isoformat()
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(page_url, wait_until="networkidle", timeout=90000)
        for window_start, window_end in date_range_windows(fetch_start, fetch_end, days=60):
            result = page.evaluate(
                """
                async ({endpoint, start, end}) => {
                  const from = new Date(start + "T00:00:00Z").toISOString();
                  const to = new Date(end + "T23:59:59Z").toISOString();
                  const url = `${endpoint}?pageSize=100&sort=datePublished:desc&filter=datePublished ge ${encodeURIComponent(from)} and datePublished le ${encodeURIComponent(to)}`;
                  const response = await fetch(url, { method: "GET" });
                  const text = await response.text();
                  return { status: response.status, text };
                }
                """,
                {"endpoint": endpoint, "start": window_start, "end": window_end},
            )
            raw_text = result["text"]
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            raw_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
            for item in payload.get("items", []):
                fields = sbv_content_fields(item)
                business_date = iso_date(fields.get("NgayBatDau") or item.get("datePublished"))
                value = parse_sbv_number(fields.get("TyGiaSo"))
                if not business_date or value is None:
                    continue
                parsed_date = datetime.strptime(business_date, "%Y-%m-%d").date()
                if parsed_date < requested_start or parsed_date > requested_end:
                    continue
                rows.append(
                    {
                        "date": business_date,
                        "source": "sbv_central_fx_history",
                        "pair": "USD/VND",
                        "buy": None,
                        "sell": None,
                        "mid": value,
                        "quote_type": "central_rate",
                        "document_number": fields.get("SoVanBan") or fields.get("SoVanBanThongBao"),
                        "published_at": item.get("datePublished"),
                        "raw_hash": raw_hash,
                    }
                )
        browser.close()
    return dedupe_dict_rows(rows, keys=["date", "source", "pair", "quote_type"])


def sbv_content_fields(item: dict[str, Any]) -> dict[str, Any]:
    fields = {}
    for field in item.get("contentFields", []):
        value = field.get("contentFieldValue") or {}
        fields[field.get("name", "")] = value.get("data")
    return fields


def iso_date(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    if len(text) >= 10 and text[4] == "-":
        return text[:10]
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:10], fmt).date().isoformat()
        except ValueError:
            pass
    return text[:10]


def parse_sbv_number(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def dedupe_dict_rows(rows: list[dict[str, Any]], keys: list[str]) -> list[dict[str, Any]]:
    seen = set()
    deduped = []
    for row in sorted(rows, key=lambda item: tuple(str(item.get(key, "")) for key in keys)):
        key = tuple(row.get(field) for field in keys)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def write_source_reliability(path: str | Path, registry: list[RegistryRecord]) -> None:
    write_csv(path, [asdict(item) for item in registry])
