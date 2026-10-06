#!/usr/bin/env python3
"""
Forward-only VN deposit/opportunity-cost monitor.

This script does not backfill historical deposit rates. It captures current
retail deposit rates from official bank pages when parseable and records SBV
policy-rate status separately. If SBV discovery has not identified an interest
rate structure, the SBV output is an empty, schema-valid file with a blocker.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from io import StringIO
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request as urllib_request

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
NORMALIZED = LAKE / "normalized"
DISCOVERY_STATUS = LAKE / "source_discovery" / "sbv_source_discovery_status.json"

RETAIL_OUT = NORMALIZED / "retail_deposit_rates.csv"
SBV_OUT = NORMALIZED / "sbv_policy_rates.csv"
SUMMARY_OUT = LAKE / "quality" / "deposit_rate_coverage_summary.json"

SOURCES = [
    {
        "bank": "vietcombank",
        "source_url": "https://www.vietcombank.com.vn/vi-VN/KHCN/Cong-cu-Tien-ich/KHCN---Lai-suat",
        "source_type": "official_bank_current",
    },
    {
        "bank": "vietinbank",
        "source_url": "https://vietinbank.vn/vi/lai-suat-khcn",
        "source_type": "official_bank_current",
    },
    {
        "bank": "bidv",
        "source_url": "https://bidv.com.vn/vn/tra-cuu-lai-suat/",
        "source_type": "official_bank_current",
    },
]


def fetch(url: str) -> tuple[str, str]:
    req = urllib_request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib_request.urlopen(req, timeout=25) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace"), hashlib.sha256(raw).hexdigest()


def parse_tenor_months(text: Any) -> int | None:
    raw = str(text or "").lower()
    s = "".join(
        ch for ch in unicodedata.normalize("NFD", raw)
        if unicodedata.category(ch) != "Mn"
    )
    if "khong" in s:
        return None
    if "duoi" in s and not ("tu" in s or "den" in s):
        return None
    match = re.search(r"(\d+)\s*(thang|month|months)", s)
    if match:
        return int(match.group(1))
    match = re.search(r"^(\d+)\s*$", s.strip())
    if match:
        value = int(match.group(1))
        if 1 <= value <= 60:
            return value
    return None


def parse_rate(value: Any) -> float | None:
    text = str(value or "").replace("%", "").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    rate = float(match.group(1))
    if 0 <= rate <= 20:
        return rate
    return None


def rows_from_tables(bank: str, source_url: str, html: str, raw_hash: str, as_of: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        tables = pd.read_html(StringIO(html))
    except Exception:
        tables = []
    for table in tables:
        if table.empty:
            continue
        table = table.copy()
        table.columns = [str(c).strip() for c in table.columns]
        for _, row in table.iterrows():
            row_values = [str(v) for v in row.to_list()]
            tenor = next((parse_tenor_months(v) for v in row_values if parse_tenor_months(v) is not None), None)
            if tenor is None:
                continue
            # Prefer a VND column if present, otherwise the first plausible rate
            rate_candidates: list[float] = []
            for col, val in row.items():
                col_l = str(col).lower()
                parsed = parse_rate(val)
                if parsed is None:
                    continue
                if "vnd" in col_l or "trả lãi cuối" in col_l or "cuối kỳ" in col_l or "rate" in col_l:
                    rate_candidates.insert(0, parsed)
                else:
                    rate_candidates.append(parsed)
            if not rate_candidates:
                continue
            rate = rate_candidates[0]
            rows.append(
                {
                    "date": as_of,
                    "bank": bank,
                    "tenor_months": tenor,
                    "currency": "VND",
                    "rate_pct_annual": rate,
                    "rate_type": "retail_deposit_current",
                    "source_type": "official_bank_current",
                    "source_url": source_url,
                    "published_at": as_of,
                    "available_from": as_of,
                    "history_status": "forward_monitoring_only",
                    "raw_hash": raw_hash,
                    "note": "Current posted rate parsed from official bank page; not historical backfill.",
                }
            )
    return rows


def collect_retail(as_of: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for source in SOURCES:
        status = {"bank": source["bank"], "source_url": source["source_url"], "status": "unknown", "rows": 0, "error": ""}
        try:
            html, raw_hash = fetch(source["source_url"])
            parsed = rows_from_tables(source["bank"], source["source_url"], html, raw_hash, as_of)
            status["status"] = "ok" if parsed else "empty"
            status["rows"] = len(parsed)
            rows.extend(parsed)
        except Exception as exc:  # noqa: BLE001
            status["status"] = "error"
            status["error"] = f"{type(exc).__name__}: {exc}"
        statuses.append(status)
    # Keep one row per bank/tenor/rate. Different banks may legitimately share rates.
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in sorted(rows, key=lambda r: (r["bank"], int(r["tenor_months"]), float(r["rate_pct_annual"]))):
        key = (row["date"], row["bank"], row["tenor_months"], row["currency"], row["rate_pct_annual"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped, statuses


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_sbv_policy(as_of: str) -> dict[str, Any]:
    fieldnames = [
        "date",
        "series_id",
        "rate_type",
        "rate_pct_annual",
        "tenor",
        "source_url",
        "published_at",
        "available_from",
        "source_type",
        "raw_hash",
        "note",
    ]
    write_csv(SBV_OUT, [], fieldnames)
    status = {
        "date": as_of,
        "rows": 0,
        "status": "blocked_no_verified_sbv_interest_rate_structure",
        "blockers": [],
    }
    if DISCOVERY_STATUS.exists():
        try:
            discovery = json.loads(DISCOVERY_STATUS.read_text(encoding="utf-8"))
        except Exception:
            discovery = {}
        if discovery.get("interest_rate_candidates", 0) == 0:
            status["blockers"].append(
                "SBV discovery found no verified interest-rate structure; structure 137473 is central USD/VND FX."
            )
    else:
        status["blockers"].append("Run scripts/pipeline/discover_sbv_sources.py before SBV policy-rate ingestion.")
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect forward-only VN deposit rate monitor.")
    parser.add_argument("--as-of", default=date.today().isoformat())
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    NORMALIZED.mkdir(parents=True, exist_ok=True)
    (LAKE / "quality").mkdir(parents=True, exist_ok=True)
    retail_rows, retail_statuses = collect_retail(args.as_of)
    retail_fields = [
        "date",
        "bank",
        "tenor_months",
        "currency",
        "rate_pct_annual",
        "rate_type",
        "source_type",
        "source_url",
        "published_at",
        "available_from",
        "history_status",
        "raw_hash",
        "note",
    ]
    write_csv(RETAIL_OUT, retail_rows, retail_fields)
    sbv_status = write_sbv_policy(args.as_of)
    valid = [
        r for r in retail_rows
        if r.get("currency") == "VND" and 0 <= float(r.get("rate_pct_annual", -1)) <= 20
    ]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": args.as_of,
        "retail_rows": len(retail_rows),
        "retail_valid_rows": len(valid),
        "retail_banks": sorted({r["bank"] for r in retail_rows}),
        "history_status": "forward_monitoring_only",
        "sbv_policy_rates": sbv_status,
        "source_statuses": retail_statuses,
        "blockers": [],
    }
    if not retail_rows:
        summary["blockers"].append("No retail deposit rates parsed from official bank pages in this run.")
    if sbv_status["rows"] == 0:
        summary["blockers"].extend(sbv_status["blockers"])
    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
