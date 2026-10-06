#!/usr/bin/env python3
"""
Incremental update script for VN Gold Market Analysis.
Automatically identifies the latest date in the local data lake and fetches missing
quotes and global market series up to today (or specified --to date).

Usage:
    python scripts/pipeline/update_incremental.py
    python scripts/pipeline/update_incremental.py --to 2026-10-06
    python scripts/pipeline/update_incremental.py --from 2026-07-12 --to 2026-10-06
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.collectors import SjcOfficialCollector
from gold_collectors.http import CachedHttpClient
from gold_collectors.reliability import business_date_from_record, collect_yfinance_prices, date_range

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Incrementally update gold data from latest recorded date to today.")
    parser.add_argument("--lake-dir", default="data/lake", help="Path to data/lake directory.")
    parser.add_argument("--from", dest="from_date", default=None, help="YYYY-MM-DD. If omitted, auto-detected from latest date + 1 day.")
    parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD. Default is today.")
    parser.add_argument("--recompute-premium", action="store_true", default=True, help="Recompute premium decomposition after crawl.")
    return parser.parse_args()


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    # Ensure all keys in any row are included
    all_keys = set()
    for r in rows:
        all_keys.update(r.keys())
    for k in sorted(all_keys):
        if k not in fieldnames:
            fieldnames.append(k)

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_latest_gold_date(lake_dir: Path) -> str | None:
    candidates = [
        lake_dir / "domestic_gold_quotes.csv",
        lake_dir / "domestic_target" / "normalized" / "domestic_gold_quotes.csv",
        lake_dir / "domestic_target" / "domestic_gold_quotes.csv",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            rows = load_csv(p)
            dates = [r["date"] for r in rows if r.get("date")]
            if dates:
                return max(dates)
    return None


def update_domestic_gold(lake_dir: Path, from_date: str, to_date: str, http: CachedHttpClient) -> int:
    print(f"\n[1/3] Fetching SJC domestic gold quotes: {from_date} -> {to_date}...")
    collector = SjcOfficialCollector(http)

    records = collector.get_history(1, from_date, to_date)
    print(f"  -> Raw records received from SJC: {len(records)}")

    # Group records by business_date
    valid_quotes_by_date: dict[str, list[Any]] = {}
    intra_day_rows: list[dict[str, Any]] = []

    for rec in records:
        bdate = business_date_from_record(rec)
        if not bdate or bdate < from_date or bdate > to_date:
            continue
        buy = rec.buy_value
        sell = rec.sell_value
        if buy is None or sell is None or sell < buy or buy < 10_000_000:
            continue

        valid_quotes_by_date.setdefault(bdate, []).append(rec)
        intra_day_rows.append({
            "branch": rec.branch or "Hồ Chí Minh",
            "business_date": bdate,
            "buy": buy,
            "currency": "VND",
            "date": bdate,
            "gold_type": rec.gold_type or "Vàng SJC 1L, 10L, 1KG",
            "provider": "SJC",
            "raw_hash": rec.raw_payload_hash,
            "sell": sell,
            "source": "sjc_official_history",
            "spread": sell - buy,
            "timestamp": rec.observed_at or f"{bdate}T00:00:00+07:00",
            "unit": "VND/lượng",
        })

    new_daily_quotes = []
    for bdate in sorted(valid_quotes_by_date.keys()):
        recs = valid_quotes_by_date[bdate]
        # Choose the latest quote for that day
        chosen = recs[-1]
        buy = chosen.buy_value
        sell = chosen.sell_value
        new_daily_quotes.append({
            "date": bdate,
            "source": "sjc_official_history",
            "provider": "sjc",
            "gold_type": "sjc_gold_bar",
            "buy": buy,
            "sell": sell,
            "spread": sell - buy,
            "currency": "VND",
            "unit": "VND/luong",
            "business_date": bdate,
            "quote_time": "",
            "data_lineage": '{"sources": ["domestic_gold_quotes"], "transform": "audited_reliable"}',
        })

    print(f"  -> Valid daily quotes created: {len(new_daily_quotes)} days")

    # Update domestic_gold_quotes.csv
    target_files = [
        lake_dir / "domestic_gold_quotes.csv",
        lake_dir / "domestic_target" / "normalized" / "domestic_gold_quotes.csv",
        lake_dir / "domestic_target" / "domestic_gold_quotes.csv",
    ]
    for p in target_files:
        existing = load_csv(p) if p.exists() else []
        lookup = {r["date"]: r for r in existing if r.get("date")}
        for r in new_daily_quotes:
            lookup[r["date"]] = r
        merged = [lookup[d] for d in sorted(lookup.keys())]
        save_csv(p, merged)
        print(f"  -> Updated {p} (Total rows: {len(merged)})")

    # Update historical intra-day rows
    hist_file = lake_dir / "gold_quotes_sjc_historical.csv"
    if hist_file.exists() and intra_day_rows:
        existing_hist = load_csv(hist_file)
        seen_keys = {
            (r.get("date"), r.get("timestamp"), r.get("buy"), r.get("sell"))
            for r in existing_hist
        }
        added = 0
        for r in intra_day_rows:
            key = (r.get("date"), r.get("timestamp"), str(r.get("buy")), str(r.get("sell")))
            if key not in seen_keys:
                existing_hist.append(r)
                seen_keys.add(key)
                added += 1
        existing_hist.sort(key=lambda x: (str(x.get("date", "")), str(x.get("timestamp", ""))))
        save_csv(hist_file, existing_hist)
        print(f"  -> Updated {hist_file} (Added {added} intra-day quotes)")

    return len(new_daily_quotes)


def update_global_market(lake_dir: Path, from_date: str, to_date: str) -> int:
    print(f"\n[2/3] Fetching global market series via yfinance: {from_date} -> {to_date}...")
    try:
        new_rows = collect_yfinance_prices(from_date, to_date)
    except Exception as exc:
        print(f"  [ERROR] yfinance collection error: {exc}")
        return 0

    print(f"  -> Fetched {len(new_rows)} global series rows from yfinance")
    if not new_rows:
        return 0

    # Update global_market_series_yfinance_fred.csv
    target_files = [
        lake_dir / "global_market_series_yfinance_fred.csv",
        lake_dir / "market_data" / "v1" / "normalized" / "global_market_series.csv",
    ]
    for p in target_files:
        if p.exists():
            existing = load_csv(p)
            seen = {(r.get("date"), r.get("series_id")) for r in existing}
            added = 0
            for r in new_rows:
                key = (r.get("date"), r.get("series_id"))
                if key not in seen:
                    existing.append(r)
                    seen.add(key)
                    added += 1
            existing.sort(key=lambda x: (str(x.get("date", "")), str(x.get("series_id", ""))))
            save_csv(p, existing)
            print(f"  -> Updated {p} (+{added} rows, total: {len(existing)})")

    # Update futures_basis_gc_f.csv
    gc_rows = [r for r in new_rows if r.get("series_id") == "GC=F"]
    futures_targets = [
        lake_dir / "futures_basis_gc_f.csv",
        lake_dir / "market_data" / "v2" / "normalized" / "futures_basis.csv",
    ]
    for p in futures_targets:
        if p.exists():
            existing = load_csv(p)
            seen = {r.get("date") for r in existing}
            added = 0
            for r in gc_rows:
                d = r.get("date")
                if d and d not in seen:
                    existing.append({
                        "asset": "gold_futures_front_continuous",
                        "available_from": (datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=1)).isoformat(),
                        "date": d,
                        "high": r.get("value"),
                        "low": r.get("value"),
                        "note": "no_shares_outstanding",
                        "open": r.get("value"),
                        "series_id": "GC=F",
                        "source": "yfinance_ticker_v2",
                        "unit": "usd_per_share",
                        "value": r.get("value"),
                        "volume": 0.0,
                    })
                    seen.add(d)
                    added += 1
            existing.sort(key=lambda x: str(x.get("date", "")))
            save_csv(p, existing)
            print(f"  -> Updated {p} (+{added} GC=F rows)")

    return len(new_rows)


def run_premium_decomposition(lake_dir: Path) -> None:
    print("\n[3/3] Recomputing Premium Decomposition...")
    from subprocess import run
    cmd = [
        sys.executable,
        "scripts/pipeline/build_premium_decomposition.py",
        "--audited-dir", str(lake_dir / "domestic_target"),
        "--external-dir", str(lake_dir),
        "--out-dir", str(lake_dir / "gold_prices"),
    ]
    res = run(cmd, capture_output=True, text=True, encoding="utf-8")
    if res.returncode == 0:
        print("  -> Premium decomposition recomputed successfully!")
        if res.stdout:
            for line in res.stdout.strip().splitlines()[-3:]:
                print(f"     {line}")
    else:
        print(f"  -> Premium decomposition notice:\n{res.stderr or res.stdout}")


def main() -> int:
    args = parse_args()
    lake_dir = Path(args.lake_dir)

    to_date = args.to_date or date.today().isoformat()
    from_date = args.from_date

    if not from_date:
        latest = find_latest_gold_date(lake_dir)
        if latest:
            next_day = (datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
            from_date = next_day
            print(f"Latest gold date in lake: {latest}. Updating forward from {from_date} to {to_date}...")
        else:
            from_date = "2026-07-12"
            print(f"No existing gold data found. Defaulting start date to {from_date}...")

    if from_date > to_date:
        print(f"Data is already up to date! (From: {from_date} > To: {to_date})")
        return 0

    http = CachedHttpClient(
        cache_dir=str(lake_dir / "raw" / "http_cache"),
        timeout_seconds=15,
        min_interval_seconds=0.35,
    )

    gold_count = update_domestic_gold(lake_dir, from_date, to_date, http)
    global_count = update_global_market(lake_dir, from_date, to_date)

    if args.recompute_premium:
        run_premium_decomposition(lake_dir)

    print("\n" + "=" * 60)
    print("INCREMENTAL UPDATE COMPLETE!")
    print(f"Range: {from_date} -> {to_date}")
    print(f"New domestic daily quotes: {gold_count}")
    print(f"New global market points: {global_count}")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
