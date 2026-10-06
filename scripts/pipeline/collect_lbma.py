#!/usr/bin/env python3
"""
LBMA Gold Price collector.

Source: https://prices.lbma.org.uk/json/today.json
No auth required. Returns AM + PM fix prices in USD/GBP/EUR.

Limitation: only TODAY's data is available (not historical archive).
This collector should be run daily to build a time series.

Output: data/lake/lbma_gold_spot_am_pm.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter  # noqa: E402

LBMA_TODAY_URL = "https://prices.lbma.org.uk/json/today.json"
OUT_DIR = Path("data/lake")
NORMALIZED = OUT_DIR / "normalized"
NORMALIZED.mkdir(parents=True, exist_ok=True)


def fetch_today() -> dict[str, Any] | None:
    """Fetch LBMA today.json and return parsed dict."""
    import urllib.request
    req = urllib.request.Request(
        LBMA_TODAY_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; gold-collector/1.0)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        print(f"ERROR fetching LBMA: {type(exc).__name__}: {exc}")
        return None


def parse_lbma_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse LBMA JSON into rows. One row per fix (AM/PM) per metal."""
    rows: list[dict[str, Any]] = []
    today_str = date.today().isoformat()

    for metal, meta in data.items():
        if metal == "silver":
            # Silver: single daily usd value (no AM/PM)
            usd_raw = meta.get("usd", "")
            try:
                usd = float(usd_raw)
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": today_str,
                "series_id": f"LBMA_{metal.upper()}_USD_OZ",
                "value": round(usd, 4),
                "unit": "USD/oz",
                "source": "lbma_today_json",
                "available_from": today_str,
                "fix_type": "daily",
                "timestamp_raw": meta.get("timestamp", ""),
            })
            continue

        # Gold / Platinum / Palladium: AM + PM
        for fix in ("am", "pm"):
            fix_data = meta.get(fix, {})
            usd_raw = fix_data.get("usd", "")
            if not usd_raw:
                continue
            try:
                usd = float(usd_raw)
            except (ValueError, TypeError):
                continue
            rows.append({
                "date": today_str,
                "series_id": f"LBMA_{metal.upper()}_{fix.upper()}_USD_OZ",
                "value": round(usd, 4),
                "unit": "USD/oz",
                "source": "lbma_today_json",
                "available_from": today_str,
                "fix_type": fix.upper(),
                "timestamp_raw": fix_data.get("timestamp", ""),
                "gbp": fix_data.get("gbp"),
                "eur": fix_data.get("eur"),
            })
    return rows


def merge_with_existing(new_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge new rows with existing CSV, dedup on (date, series_id, fix_type)."""
    csv_path = NORMALIZED / "lbma_gold_spot_am_pm.csv"
    existing: list[dict[str, Any]] = []
    if csv_path.exists():
        with open(csv_path, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))

    # Build index of existing
    seen: set[tuple[str, str, str]] = set()
    merged: list[dict[str, Any]] = []
    for r in existing:
        key = (r.get("date", ""), r.get("series_id", ""), r.get("fix_type", ""))
        if key not in seen:
            seen.add(key)
            merged.append(r)

    for r in new_rows:
        key = (r.get("date", ""), r.get("series_id", ""), r.get("fix_type", ""))
        if key not in seen:
            seen.add(key)
            merged.append(r)

    merged.sort(key=lambda r: (r.get("date", ""), r.get("series_id", ""), r.get("fix_type", "")))
    return merged


def write_csv(rows: list[dict[str, Any]]) -> None:
    if not rows:
        print("No LBMA rows to write.")
        return
    fieldnames = [
        "date", "series_id", "value", "unit", "source", "available_from",
        "fix_type", "gbp", "eur", "timestamp_raw",
    ]
    with open(NORMALIZED / "lbma_gold_spot_am_pm.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows):,} rows to {NORMALIZED / 'lbma_gold_spot_am_pm.csv'}")
    # Also write manifest
    manifest = {
        "generated_at": date.today().isoformat(),
        "source": "lbma_today_json",
        "url": LBMA_TODAY_URL,
        "rows": len(rows),
        "by_series": {},
    }
    from collections import Counter
    for sid, cnt in Counter(r["series_id"] for r in rows).items():
        manifest["by_series"][sid] = cnt
    (OUT_DIR / "manifests" / "lbma_spot_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Collect LBMA gold/silver/platinum/palladium prices.")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    global NORMALIZED
    NORMALIZED = Path(args.out_dir) / "normalized"
    NORMALIZED.mkdir(parents=True, exist_ok=True)
    (Path(args.out_dir) / "manifests").mkdir(parents=True, exist_ok=True)

    print("Fetching LBMA today.json...")
    data = fetch_today()
    if not data:
        print("WARNING: No data fetched — keeping existing CSV if present.")
        return 1

    rows = parse_lbma_response(data)
    if not rows:
        print("WARNING: Parsed 0 rows.")
        return 1

    summary = {}
    for r in rows:
        summary[r["series_id"]] = r["value"]

    merged = merge_with_existing(rows)
    write_csv(merged)

    print("\nToday's LBMA prices:")
    for sid, val in summary.items():
        print(f"  {sid}: {val:,.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
