#!/usr/bin/env python3
"""
Integrate PNJ and other archive sources into gold_quotes_sjc_historical.csv.

Expands the audited dataset from 28K rows (SJC only) to ~95K+ rows by including:
- webgia_sjc_archive (24,994 rows)
- giavang_sjc_archive (9,492 rows)
- giavang_pnj_archive (61,778 rows)

Filter: requested_date == business_date AND buy > 0 AND sell > 0
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter


# Sources eligible for historical training data
# Must have: requested_date == business_date, valid buy/sell
ELIGIBLE_SOURCES = {
    "sjc_official": {"provider": "SJC", "gold_type_map": {"Vàng SJC 1L, 10L, 1KG": "SJC"}},
    "webgia_sjc_archive": {"provider": "WebGia_SJC", "gold_type_map": {"SJC 1 lượng": "SJC"}},
    "giavang_sjc_archive": {"provider": "GiaVang_SJC", "gold_type_map": {
        "Vàng SJC 1L, 10L, 1KG": "SJC",
    }},
    "giavang_pnj_archive": {"provider": "GiaVang_PNJ", "gold_type_map": {
        "PNJ": "PNJ",
        "Nhẫn PNJ (24K)": "PNJ_RING",
    }},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Integrate archive sources into audited domestic gold quotes.")
    p.add_argument("--raw-dir", default="data/lake")
    p.add_argument("--audited-dir", default="data/lake")
    p.add_argument("--out-dir", default="data/lake")
    return p.parse_args()


def integrate(args: argparse.Namespace) -> int:
    raw_csv = Path(args.raw_dir) / "raw_gold_history.csv"
    if not raw_csv.exists():
        print(f"ERROR: {raw_csv} not found")
        return 1

    rows_added = 0
    rows_skipped = 0
    source_counts = Counter()
    type_counts = Counter()

    with open(raw_csv, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames

        # Collect filtered rows
        new_rows = []
        for row in reader:
            src = row.get("source", "")
            if src not in ELIGIBLE_SOURCES:
                rows_skipped += 1
                continue

            # Check date match (requested_date == business_date)
            req_date = row.get("date", "")
            biz_date = row.get("business_date", "")
            if req_date and biz_date and req_date != biz_date:
                rows_skipped += 1
                continue

            # Check valid prices
            try:
                buy = float(row.get("buy", "") or 0)
                sell = float(row.get("sell", "") or 0)
            except (ValueError, TypeError):
                rows_skipped += 1
                continue
            if buy <= 0 or sell <= 0:
                rows_skipped += 1
                continue

            # Map gold_type to standard category
            src_config = ELIGIBLE_SOURCES[src]
            raw_type = row.get("gold_type", "").strip()
            std_type = src_config["gold_type_map"].get(raw_type)
            if std_type is None:
                # Skip unclassified types
                rows_skipped += 1
                continue

            # Update row with standard fields
            new_row = dict(row)
            new_row["provider"] = src_config["provider"]
            new_row["gold_type"] = std_type
            new_rows.append(new_row)
            source_counts[src] += 1
            type_counts[std_type] += 1

    # Write output
    out_dir = Path(args.out_dir)
    out_norm = out_dir / "normalized"
    out_norm.mkdir(parents=True, exist_ok=True)
    out_csv = out_norm / "gold_quotes_sjc_historical.csv"

    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(new_rows)

    rows_added = len(new_rows)
    print(f"Integrated {rows_added} rows into {out_csv}")
    print(f"Skipped {rows_skipped} rows")
    print(f"By source: {dict(source_counts)}")
    print(f"By type: {dict(type_counts)}")
    print(f"Date range: {min(r['date'] for r in new_rows)} to {max(r['date'] for r in new_rows)}")

    # Write manifest
    manifest = {
        "generated_at": date.today().isoformat(),
        "source": "integrated_multi_source",
        "rows": rows_added,
        "by_source": dict(source_counts),
        "by_type": dict(type_counts),
        "date_range": [min(r['date'] for r in new_rows), max(r['date'] for r in new_rows)],
        "eligible_sources": list(ELIGIBLE_SOURCES.keys()),
    }
    (out_dir / "manifests" / "integrate_pnj_manifest.json").write_text(
        __import__("json").dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(integrate(parse_args()))
