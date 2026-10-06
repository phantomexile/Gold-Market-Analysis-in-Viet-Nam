#!/usr/bin/env python3
"""Geopolitical Risk (GPR) daily index via GDELT 2.0 Events API.

Falls back to yfinance VIX as proxy if GDELT is unreachable.
Output: data/lake/gpr_daily.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

GDELT_EVENTS_URL = (
    "https://api.gdeltproject.org/api/v2/events.json"
)

# Query includes Vietnam + broader SEA for Vietnam-relevant geopolitics
GDELT_QUERY = (
    "searchevent_location_region:SEA "
    "actionGeo_countryCode:VN "
    "isverbal:0 "
    "eventroottype:07"  # fight/attack or related categories — keep broad
)

OUT_DIR = Path("data/lake")
NORMALIZED = OUT_DIR / "normalized"
NORMALIZED.mkdir(parents=True, exist_ok=True)


def fetch_gdelt_day(target_date: date, max_retries: int = 3) -> list[dict]:
    """Fetch events from GDELT for a single day, return event list."""
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    params = {
        "query": GDELT_QUERY,
        "format": "json",
        "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end_dt.strftime("%Y%m%d%H%M%S"),
        "maxrecords": "250",
        "transparency": "0",
    }
    url = GDELT_EVENTS_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "vn-gold-pipeline/2025 GPR collector",
            "Accept": "application/json",
        },
    )
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(data, list):
                    return data
                return data.get("events", [])
        except Exception as exc:
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"  WARN GDELT {target_date}: {type(exc).__name__}: {exc}", file=sys.stderr)
                return []
    return []


def _month_chunks(start: str, end: str) -> list[tuple[date, date]]:
    """Split date range into month-level chunks."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    chunks = []
    cur = date(s.year, s.month, 1)
    while cur <= e:
        nxt = (cur.replace(day=28) + timedelta(days=5)).replace(day=1)
        chunk_end = min(nxt - timedelta(days=1), e)
        chunks.append((max(cur, s), chunk_end))
        cur = nxt
    return chunks


def collect_gpr_daily(start: str, end: str, pause: float = 0.5) -> list[dict]:
    """Collect daily GPR via GDELT, batched by month to reduce API calls."""
    rows: list[dict] = []
    daily_counts: dict[date, int] = defaultdict(int)
    chunks = _month_chunks(start, end)
    print(f"  GDELT: {len(chunks)} month chunks...")
    for chunk_start, chunk_end in chunks:
        events = fetch_gdelt_day(chunk_start)
        if events:
            for ev in events:
                sd = (
                    ev.get(DATEADDED, )
                    or ev.get(SqlDateTime, )
                    or ev.get(EventDateTime, )
                )
                if not sd:
                    continue
                try:
                    sd_str = str(sd)[:10]
                    d = date.fromisoformat(sd_str)
                except (ValueError, TypeError):
                    continue
                if chunk_start <= d <= chunk_end:
                    daily_counts[d] += 1
        time.sleep(pause)
        # Progress indicator
        total_so_far = sum(1 for c in daily_counts.values() if c > 0)
        print(f"    chunk {chunk_start} -> {chunk_end}: {len(events)} events (so far {total_so_far} active days)")

    for d in sorted(daily_counts):
        rows.append({
            "date": d.isoformat(),
            "series_id": "GPR_SEA_VN",
            "asset": "geopolitical_risk",
            "value": float(daily_counts[d]),
            "unit": "event_count_per_day",
            "source": "gdelt_v2_events",
            "available_from": d.isoformat(),
            "note": "GDELT 2.0 SEA+VN events daily count; no imputation",
        })
    return rows


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_and_write(existing: list[dict], new_rows: list[dict], out_path: Path) -> None:
    by_key: dict[tuple[str, str], dict] = {}
    for r in existing:
        key = (r.get("date", ""), r.get("series_id", ""))
        by_key[key] = r
    for r in new_rows:
        key = (r.get("date", ""), r.get("series_id", ""))
        by_key[key] = r
    merged = sorted(by_key.values(), key=lambda x: (x.get("date", ""), x.get("series_id", "")))
    if not merged:
        return
    fieldnames = sorted(merged[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(merged)


def write_manifest(records: int, start: str, end: str, out_dir: Path = OUT_DIR) -> None:
    import json
    (out_dir / "manifests").mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": date.today().isoformat(),
        "source": "gdelt_v2_events",
        "from": start,
        "to": end,
        "records": records,
        "note": "SEA+VN event count; incremental append supported; no imputation",
    }
    (out_dir / "manifests" / "gpr_daily_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect GPR daily via VIX proxy.")
    ap.add_argument("--from", dest="start", default="2010-01-01")
    ap.add_argument("--to", dest="end", default="2026-07-07")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--symbol", default="^VIX", help="yfinance symbol for GPR proxy")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    norm_dir = out_dir / "normalized"
    norm_dir.mkdir(parents=True, exist_ok=True)

    print(f"Collecting GPR proxy via yfinance {args.symbol}...")
    try:
        import yfinance as yf
        ticker = yf.Ticker(args.symbol)
        frame = ticker.history(start=args.start, end=args.end, auto_adjust=False)
    except Exception as exc:
        print(f"  yfinance error: {type(exc).__name__}: {exc}", file=sys.stderr)
        frame = None

    gpr_rows: list[dict] = []
    if frame is not None and not frame.empty:
        for idx, row in frame.iterrows():
            d = idx.date().isoformat()
            gpr_rows.append({
                "date": d,
                "series_id": "GPR_VIX_PROXY",
                "asset": "geopolitical_risk_proxy_vix",
                "value": round(float(row["Close"]), 4),
                "unit": "index",
                "source": "yfinance_vix_proxy",
                "available_from": d,
                "note": "VIX as GPR proxy; GDELT blocked from VN network; no imputation",
            })
        print(f"  VIX proxy: {len(gpr_rows)} days")

    # VIX fallback if GPR empty
    if not gpr_rows and args.fallback_vix:
        print("  Using yfinance VIX as GPR proxy...")
        try:
            import yfinance as yf
            import pandas as pd
            ticker = yf.Ticker("^VIX")
            vix = ticker.history(start=args.start, end=args.end, auto_adjust=False)
            if not vix.empty:
                for idx, row in vix.iterrows():
                    d = idx.date().isoformat()
                    gpr_rows.append({
                        "date": d,
                        "series_id": "GPR_VIX_PROXY",
                        "asset": "geopolitical_risk_proxy",
                        "value": round(float(row["Close"]), 4),
                        "unit": "index",
                        "source": "yfinance_vix_proxy",
                        "available_from": d,
                        "note": "VIX used as proxy for geopolitical risk (GDELT unreachable)",
                    })
                print(f"  VIX: {len(gpr_rows)} rows")
            else:
                print("  WARN: VIX also empty")
        except Exception as exc:
            print(f"  VIX fallback error: {type(exc).__name__}: {exc}")

    out_path = norm_dir / "gpr_daily.csv"
    existing = load_existing(out_path)
    merge_and_write(existing, gpr_rows, out_path)
    write_manifest(len(gpr_rows), args.start, args.end, out_dir)
    print(f"  Written {len(gpr_rows)} rows → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
