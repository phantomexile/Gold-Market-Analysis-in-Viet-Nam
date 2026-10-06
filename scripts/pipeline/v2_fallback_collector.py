#!/usr/bin/env python3
"""
Fallback collector for external_features_v2.
Bypasses build_enhanced_features.py (blocked on FRED CSV endpoint)
and collects directly via yfinance Ticker API for:
 - GLD ETF (close + volume)
 - Gold futures continuous (GC=F)
Uses the existing DataLakeWriter pipeline.
"""
from __future__ import annotations

import csv, hashlib, io, json, sys
from datetime import datetime, timedelta
from pathlib import Path

try:
    from _bootstrap import bootstrap
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from _bootstrap import bootstrap

bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter


def collect_yfinance_series(symbol: str, asset_name: str, start: str, end: str) -> list[dict]:
    import yfinance as yf
    rows: list[dict] = []
    ticker = yf.Ticker(symbol)
    end_excl = (datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    frame = ticker.history(start=start, end=end_excl, auto_adjust=False, repair=False)
    if frame.empty:
        return rows
    for idx, row in frame.iterrows():
        d = idx.date().isoformat()
        rows.append({
            "date": d,
            "series_id": symbol,
            "asset": asset_name,
            "value": round(float(row["Close"]), 4) if row["Close"] is not None else None,
            "open": round(float(row["Open"]), 4) if row["Open"] is not None else None,
            "high": round(float(row["High"]), 4) if row["High"] is not None else None,
            "low": round(float(row["Low"]), 4) if row["Low"] is not None else None,
            "volume": round(float(row["Volume"]), 0) if row["Volume"] is not None else None,
            "unit": "usd_per_share" if "ETF" in asset_name else ("usd_per_oz" if "gold" in asset_name.lower() else "usd"),
            "source": "yfinance_ticker_v2",
        })
    return rows


def collect_gld_etf(start: str, end: str) -> list[dict]:
    return collect_yfinance_series("GLD", "gld_spdr_gold_etf_proxy", start, end)


def collect_gc_front(start: str, end: str) -> list[dict]:
    return collect_yfinance_series("GC=F", "gold_futures_front_continuous", start, end)


def load_existing(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_and_write(existing: list[dict], new_rows: list[dict], out_path: Path):
    by_key: dict[str, dict] = {}
    for r in existing:
        by_key[(r.get("date", ""), r.get("series_id", ""))] = r
    for r in new_rows:
        by_key[(r.get("date", ""), r.get("series_id", ""))] = r
    merged = sorted(by_key.values(), key=lambda x: (x.get("date", ""), x.get("series_id", "")))
    if merged:
        fieldnames = sorted(merged[0].keys())
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(merged)


def main():
    start, end = "2010-01-01", "2026-07-07"
    out_dir = Path("data/lake")
    norm = out_dir / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)

    etf_path = norm / "etf_proxy.csv"
    fut_path = norm / "futures_basis.csv"

    print("Collecting GLD ETF proxy...")
    gld = collect_gld_etf(start, end)
    print(f"  GLD: {len(gld)} new rows")
    existing_gld = load_existing(etf_path)
    merge_and_write(existing_gld, gld, etf_path)

    print("Collecting GC=F futures...")
    gc = collect_gc_front(start, end)
    print(f"  GC=F: {len(gc)} new rows")
    # futures_basis has different schema (open/second/basis columns)
    # Write directly with appropriate fields
    if gc:
        fieldnames = ["date", "series_id", "asset", "value", "open", "high", "low", "volume",
                       "unit", "source", "futures_basis_abs", "futures_basis_pct"]
        with fut_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            for r in gc:
                w.writerow({k: r.get(k) for k in fieldnames})

    manifest = {
        "generated_at": datetime.today().isoformat(),
        "from": start,
        "to": end,
        "sources": ["yfinance_gld_ticker", "yfinance_gc_ticker"],
        "records": {"etf_proxy": len(gld), "futures_basis": len(gc)},
        "note": "FRED expanded series blocked by network rate limit; using yfinance fallback for GLD + GC=F",
    }
    (out_dir / "manifests" / "v2_fallback_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDone. etf_proxy={len(gld)}, futures_basis={len(gc)}")
    print(f"Output: {norm}/")


if __name__ == "__main__":
    raise SystemExit(main())
