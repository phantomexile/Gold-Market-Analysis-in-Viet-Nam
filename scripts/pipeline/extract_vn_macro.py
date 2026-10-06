#!/usr/bin/env python3
"""
VN Macro Extractor — high-signal subset for gold forecasting.

Reads existing macro_series.csv (which already has GSO data) and extracts
only the most predictive indicators:
  - CPI headline YoY% (monthly)
  - Industrial Production index (monthly)
  - Labour force / employment (quarterly)
  - Unemployment rate (quarterly)
  - Imports CIF (monthly — proxy for gold demand via customs)
  - VN stock index end-of-period (monthly — sentiment proxy)

Output: data/lake/vn_macro_forecasting.csv

All rows use `available_from` = observation date.
CRITICAL: join by `available_from` (NOT `observation_date`) to prevent
lookahead leakage in backtests.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from datetime import date

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap
bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter

# ---------------------------------------------------------------------------
# High-signal indicator map: series_id -> (friendly_name, unit, freq)
# ---------------------------------------------------------------------------
HIGH_SIGNAL_INDICATORS: dict[str, tuple[str, str, str]] = {
    # CPI
    "PCPI_IX": ("cpi_headline_yoy_pct", "pct", "M"),
    # Industrial Production (ISIC4 rev 4)
    "AIP_ISIC4_IX": ("ip_total_index", "index_2015=100", "M"),
    "AIP_ISIC4_B_IX": ("ip_mining_quarrying_index", "index_2015=100", "M"),
    "AIP_ISIC4_C_IX": ("ip_manufacturing_index", "index_2015=100", "M"),
    "AIP_ISIC4_D_IX": ("ip_electricity_index", "index_2015=100", "M"),
    "AIP_ISIC4_E_IX": ("ip_water_waste_index", "index_2015=100", "M"),
    # Labour market
    "LE_PE_NUM": ("labour_employed_10k", "10k_persons", "Q"),
    "LLF_PE_NUM": ("labour_force_10k", "10k_persons", "Q"),
    "LEU_PT": ("unemployment_rate_pct", "pct", "Q"),
    # Trade / imports (proxy for gold demand via customs)
    "TMG_CIF_USD": ("total_imports_cif_m_usd", "M_USD", "M"),
    "TMGIOT_CIF_USD": ("imports_all_cif_m_usd", "M_USD", "M"),
    "TMGISO_CIF_USD": ("imports_direct_m_usd", "M_USD", "M"),
    # Stock market sentiment proxies
    "VNM_HNX_EOP_IX": ("hnx_index_eop", "index", "M"),
    "VNM_VN_EOP_IX": ("vnindex_eop", "index", "M"),
    # Population
    "LP_PE_NUM": ("population_10k", "10k_persons", "A"),
}
_SERIES_LOOKUP: dict[str, tuple[str, str, str]] = dict(HIGH_SIGNAL_INDICATORS)


@dataclass(frozen=True)
class MacroExtractStatus:
    source: str
    dataset: str
    status: str
    records: int
    warning: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract high-signal VN macro indicators.")
    p.add_argument("--input", default="macro_series_wb_gso.csv",
                    help="Full macro_series.csv from v1 collector")
    p.add_argument("--out-dir", default="data/lake")
    p.add_argument("--from", dest="from_date", default="2010-01-01")
    p.add_argument("--to", dest="to_date", default=date.today().isoformat())
    return p.parse_args()


def extract_vn_macro(input_csv: str, from_date: str, to_date: str) -> tuple[list[dict], dict]:
    """Filter source macro_series.csv to high-signal indicators only."""
    from_dt = date.fromisoformat(from_date)
    to_dt = date.fromisoformat(to_date)

    merged: dict[str, list[dict]] = {sid: [] for sid in HIGH_SIGNAL_INDICATORS}
    with open(input_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sid = row.get("series_id", "")
            if sid not in _SERIES_LOOKUP:
                continue
            d_str = row.get("date", "")[:10]
            if not d_str:
                continue
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d < from_dt or d > to_dt:
                continue
            val_raw = row.get("value", "")
            if not val_raw or val_raw == "":
                continue
            try:
                val = float(val_raw)
            except (ValueError, TypeError):
                continue
            friendly_name, unit, _ = _SERIES_LOOKUP[sid]
            merged[sid].append({
                "date": d.isoformat(),
                "series_id": sid,
                "series_name": friendly_name,
                "frequency": row.get("frequency", ""),
                "value": val,
                "unit": unit,
                "source": "gso_macro_monitor_curated",
                "domain": row.get("domain", ""),
                "available_from": d.isoformat(),
                "release_date": row.get("release_date", ""),
            })

    out = []
    for sid, rows in merged.items():
        if not rows:
            continue
        for r in rows:
            out.append(r)
    out.sort(key=lambda x: (x["date"], x["series_id"]))

    manifest = {
        "generated_at": date.today().isoformat(),
        "from": from_date,
        "to": to_date,
        "source": "gso_macro_monitor",
        "indicators_extracted": len(HIGH_SIGNAL_INDICATORS),
        "indicators_with_data": sum(1 for rows in merged.values() if rows),
        "indicators_missing": [sid for sid, rows in merged.items() if not rows],
        "total_rows": len(out),
        "record_counts": {sid: len(rows) for sid, rows in merged.items() if rows},
        "available_from_note": (
            "All rows use available_from = observation date. "
            "Join by available_from (NOT observation_date) to prevent leakage in backtests."
        ),
    }
    return out, manifest


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    norm = out_dir / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)

    statuses: list[MacroExtractStatus] = []
    try:
        rows, manifest = extract_vn_macro(args.input, args.from_date, args.to_date)
        writer.write_dataset("vn_macro_forecasting", rows)
        statuses.append(MacroExtractStatus(
            "extract_vn_macro", "vn_macro_forecasting",
            "ok" if rows else "empty", len(rows)
        ))
        print(f"\nRecords: {len(rows)}")
        print(f"Indicators: {manifest.get('indicators_with_data', 0)}/{manifest.get('indicators_extracted', 0)}")
        for sid, cnt in sorted(manifest.get("record_counts", {}).items()):
            friendly = HIGH_SIGNAL_INDICATORS.get(sid, (sid,))[0]
            print(f"  {sid} ({friendly}): {cnt} rows")
        if manifest.get("indicators_missing"):
            print(f"Missing data: {manifest['indicators_missing']}")
    except Exception as exc:
        statuses.append(MacroExtractStatus(
            "extract_vn_macro", "vn_macro_forecasting",
            "error", 0, str(exc)
        ))
        print(f"ERROR: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
