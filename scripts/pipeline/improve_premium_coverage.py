#!/usr/bin/env python3
"""
Improve domestic premium coverage with source-tagged reference fallbacks.

The original premium table only covered days with same-day global/FX data.
Vietnamese domestic quotes are daily, while global gold and FX series often miss
weekends and holidays. This script uses a bounded as-of fallback hierarchy:

Gold reference: official LBMA today append -> existing LBMA/GC=F proxy ->
gold futures close proxy.
FX reference: Vietcombank/yfinance market rate -> SBV/merged mid rate.

Every generated premium row carries source metadata and staleness fields so the
model can use the improved coverage without pretending all references are equal.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
QUALITY = LAKE / "quality"
OUT_PREMIUM = LAKE / "pipeline_output_premium_enriched.csv"
AUDIT_CSV = QUALITY / "premium_coverage_audit.csv"
SUMMARY_JSON = QUALITY / "premium_coverage_summary.json"

CHI_PER_OZ = 31.1034768 / 1.205
LUONG_PER_OZ = CHI_PER_OZ / 37.5


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def load_domestic(path: Path) -> pd.DataFrame:
    df = read_csv(path)
    if df.empty:
        raise FileNotFoundError(path)
    date_col = "business_date" if "business_date" in df.columns else "date"
    df = df.copy()
    df["date"] = date_series(df[date_col])
    df["buy"] = numeric(df["buy"])
    df["sell"] = numeric(df["sell"])
    df = df.dropna(subset=["date", "buy", "sell"])
    df = df[(df["buy"] > 0) & (df["sell"] >= df["buy"])]
    grouped = df.groupby("date", as_index=False).agg(
        buy_consensus=("buy", "median"),
        sell_consensus=("sell", "median"),
        source_count=("source", "nunique"),
        sources_active=("source", lambda s: ",".join(sorted({str(x) for x in s.dropna()}))),
        primary_source=("source", lambda s: "sjc_official_history" if "sjc_official_history" in set(s) else str(s.dropna().iloc[0] if len(s.dropna()) else "")),
    )
    grouped["mid_consensus"] = (grouped["buy_consensus"] + grouped["sell_consensus"]) / 2
    grouped["spread_abs"] = grouped["sell_consensus"] - grouped["buy_consensus"]
    grouped["spread_pct"] = grouped["spread_abs"] / grouped["sell_consensus"]
    grouped["source_dispersion"] = 0.0
    return grouped.sort_values("date")


def load_gold_reference() -> pd.DataFrame:
    rows: list[pd.DataFrame] = []

    lbma_today = read_csv(LAKE / "normalized" / "lbma_gold_spot_am_pm.csv")
    if not lbma_today.empty:
        lbma_today = lbma_today.copy()
        lbma_today["date"] = date_series(lbma_today["date"])
        lbma_today["value"] = numeric(lbma_today["value"])
        gold = lbma_today[lbma_today["series_id"].astype(str).str.contains("LBMA_GOLD", na=False)].copy()
        am = gold[gold["series_id"].astype(str).str.contains("_AM_", na=False)]
        if am.empty:
            am = gold
        if not am.empty:
            official = am.groupby("date", as_index=False)["value"].mean()
            official["gold_reference_source"] = "lbma_today_json"
            official["gold_reference_quality"] = "official_benchmark_daily_append"
            official["gold_priority"] = 1
            rows.append(official.rename(columns={"value": "global_gold_usd_oz"}))

    proxy = read_csv(LAKE / "lbma_gold_proxy_gc_f.csv")
    if not proxy.empty:
        proxy = proxy.copy()
        proxy["date"] = date_series(proxy["date"])
        proxy["global_gold_usd_oz"] = numeric(proxy["value"])
        proxy["gold_reference_source"] = proxy.get("source", "yfinance_gc_futures").fillna("yfinance_gc_futures")
        proxy["gold_reference_quality"] = proxy.get("source_quality", "proxy_futures_based").fillna("proxy_futures_based")
        proxy["gold_priority"] = 2
        rows.append(proxy[["date", "global_gold_usd_oz", "gold_reference_source", "gold_reference_quality", "gold_priority"]])

    global_ref = read_csv(LAKE / "global_reference_daily.csv")
    if not global_ref.empty:
        global_ref = global_ref.copy()
        global_ref["date"] = date_series(global_ref["date"])
        for col, source, quality, priority in [
            ("lbma_price_usd_oz", "global_reference_lbma_or_proxy", "proxy_or_existing_reference", 3),
            ("gold_futures_close_usd_oz", "global_reference_gold_futures_close", "proxy_futures_close", 4),
        ]:
            if col in global_ref.columns:
                sub = global_ref[["date", col]].copy()
                sub["global_gold_usd_oz"] = numeric(sub[col])
                sub = sub.dropna(subset=["date", "global_gold_usd_oz"])
                sub["gold_reference_source"] = source
                sub["gold_reference_quality"] = quality
                sub["gold_priority"] = priority
                rows.append(sub[["date", "global_gold_usd_oz", "gold_reference_source", "gold_reference_quality", "gold_priority"]])

    if not rows:
        return pd.DataFrame(columns=["date", "global_gold_usd_oz", "gold_reference_source", "gold_reference_quality"])
    out = pd.concat(rows, ignore_index=True).dropna(subset=["date", "global_gold_usd_oz"])
    out = out[(out["global_gold_usd_oz"] > 200) & (out["global_gold_usd_oz"] < 100_000)]
    out = out.sort_values(["date", "gold_priority"]).drop_duplicates("date", keep="first")
    return out[["date", "global_gold_usd_oz", "gold_reference_source", "gold_reference_quality"]].sort_values("date")


def load_fx_reference() -> pd.DataFrame:
    global_ref = read_csv(LAKE / "global_reference_daily.csv")
    if global_ref.empty:
        return pd.DataFrame(columns=["date", "usd_vnd", "fx_source", "fx_quality"])
    global_ref = global_ref.copy()
    global_ref["date"] = date_series(global_ref["date"])
    rows: list[pd.DataFrame] = []
    for col, source, quality, priority in [
        ("usd_vnd_market_rate", "vietcombank_or_yfinance_market_rate", "market_rate", 1),
        ("usd_vnd_mid", "sbv_or_merged_mid_rate", "official_or_merged_mid", 2),
    ]:
        if col in global_ref.columns:
            sub = global_ref[["date", col]].copy()
            sub["usd_vnd"] = numeric(sub[col])
            sub = sub.dropna(subset=["date", "usd_vnd"])
            sub = sub[(sub["usd_vnd"] > 10_000) & (sub["usd_vnd"] < 100_000)]
            sub["fx_source"] = source
            sub["fx_quality"] = quality
            sub["fx_priority"] = priority
            rows.append(sub[["date", "usd_vnd", "fx_source", "fx_quality", "fx_priority"]])
    if not rows:
        return pd.DataFrame(columns=["date", "usd_vnd", "fx_source", "fx_quality"])
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values(["date", "fx_priority"]).drop_duplicates("date", keep="first")
    return out[["date", "usd_vnd", "fx_source", "fx_quality"]].sort_values("date")


def asof_attach(domestic: pd.DataFrame, ref: pd.DataFrame, prefix: str, tolerance_days: int) -> pd.DataFrame:
    if ref.empty:
        return domestic
    ref = ref.rename(columns={"date": f"{prefix}_date"}).sort_values(f"{prefix}_date")
    out = pd.merge_asof(
        domestic.sort_values("date"),
        ref,
        left_on="date",
        right_on=f"{prefix}_date",
        direction="backward",
        tolerance=pd.Timedelta(days=tolerance_days),
    )
    out[f"{prefix}_staleness_days"] = (out["date"] - out[f"{prefix}_date"]).dt.days
    return out


def quality_label(row: pd.Series) -> str:
    if pd.isna(row.get("global_gold_usd_oz")) or pd.isna(row.get("usd_vnd")):
        return "missing_reference"
    stale = max(float(row.get("gold_staleness_days", 999)), float(row.get("fx_staleness_days", 999)))
    gold_quality = str(row.get("gold_reference_quality", ""))
    if stale == 0 and gold_quality.startswith("official"):
        return "official_exact"
    if stale == 0:
        return "proxy_exact"
    return "proxy_forward_filled"


def build_improved(args: argparse.Namespace) -> tuple[pd.DataFrame, dict[str, Any]]:
    domestic = load_domestic(LAKE / "domestic_gold_quotes.csv")
    old = read_csv(OUT_PREMIUM)
    old_missing_rate = None
    old_rows = 0
    if not old.empty and "premium" in old.columns:
        old_rows = len(old)
        old_missing_rate = float(numeric(old["premium"]).isna().mean())

    gold_ref = load_gold_reference()
    fx_ref = load_fx_reference()
    out = asof_attach(domestic, gold_ref, "gold", args.gold_tolerance_days)
    out = asof_attach(out, fx_ref, "fx", args.fx_tolerance_days)

    out["global_gold_vnd_per_luong"] = out["global_gold_usd_oz"] * out["usd_vnd"] / LUONG_PER_OZ
    missing = out["global_gold_vnd_per_luong"].isna()
    out.loc[missing, "premium"] = np.nan
    out.loc[~missing, "premium"] = out.loc[~missing, "sell_consensus"] - out.loc[~missing, "global_gold_vnd_per_luong"]
    out["premium_pct"] = out["premium"] / out["global_gold_vnd_per_luong"]
    out["source_quality"] = out.apply(quality_label, axis=1)
    out["is_proxy"] = ~out["source_quality"].eq("official_exact")
    out["availability_from"] = out[["gold_date", "fx_date"]].max(axis=1).dt.strftime("%Y-%m-%d")
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")

    column_order = [
        "date",
        "buy_consensus",
        "sell_consensus",
        "mid_consensus",
        "spread_abs",
        "spread_pct",
        "global_gold_usd_oz",
        "usd_vnd",
        "global_gold_vnd_per_luong",
        "premium",
        "premium_pct",
        "source_count",
        "source_dispersion",
        "primary_source",
        "sources_active",
        "gold_reference_source",
        "fx_source",
        "source_quality",
        "availability_from",
        "is_proxy",
        "gold_staleness_days",
        "fx_staleness_days",
        "gold_reference_quality",
        "fx_quality",
    ]
    for col in column_order:
        if col not in out.columns:
            out[col] = np.nan
    out = out[column_order]
    for col in [
        "buy_consensus",
        "sell_consensus",
        "mid_consensus",
        "spread_abs",
        "global_gold_usd_oz",
        "usd_vnd",
        "global_gold_vnd_per_luong",
        "premium",
    ]:
        out[col] = pd.to_numeric(out[col], errors="coerce").round(2)
    out["spread_pct"] = pd.to_numeric(out["spread_pct"], errors="coerce").round(6)
    out["premium_pct"] = pd.to_numeric(out["premium_pct"], errors="coerce").round(6)

    new_missing_rate = float(out["premium"].isna().mean())
    by_year = out.assign(year=pd.to_datetime(out["date"]).dt.year).groupby("year", as_index=False).agg(
        rows=("date", "size"),
        premium_missing=("premium", lambda s: int(pd.to_numeric(s, errors="coerce").isna().sum())),
        premium_missing_rate=("premium", lambda s: float(pd.to_numeric(s, errors="coerce").isna().mean())),
        proxy_share=("is_proxy", lambda s: float(pd.Series(s).astype(bool).mean())),
    )
    by_quality = out.groupby("source_quality", as_index=False).agg(rows=("date", "size"))
    audit = pd.concat(
        [
            by_year.assign(section="by_year").rename(columns={"year": "segment"}),
            by_quality.assign(section="by_source_quality").rename(columns={"source_quality": "segment"}),
        ],
        ignore_index=True,
        sort=False,
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(out)),
        "old_rows": int(old_rows),
        "old_premium_missing_rate": old_missing_rate,
        "new_premium_missing_rate": new_missing_rate,
        "target_missing_rate": args.target_missing_rate,
        "target_met": bool(new_missing_rate <= args.target_missing_rate),
        "gold_tolerance_days": args.gold_tolerance_days,
        "fx_tolerance_days": args.fx_tolerance_days,
        "source_quality_counts": out["source_quality"].value_counts(dropna=False).to_dict(),
        "blockers": [] if new_missing_rate <= args.target_missing_rate else [
            "Premium missing remains above target after bounded as-of fallback; inspect source gaps by year."
        ],
    }
    return out, {"audit": audit, "summary": summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Improve premium coverage with tagged reference fallbacks.")
    parser.add_argument("--gold-tolerance-days", type=int, default=4)
    parser.add_argument("--fx-tolerance-days", type=int, default=4)
    parser.add_argument("--target-missing-rate", type=float, default=0.10)
    parser.add_argument("--out", default=str(OUT_PREMIUM))
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    QUALITY.mkdir(parents=True, exist_ok=True)
    out, meta = build_improved(args)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    meta["audit"].to_csv(AUDIT_CSV, index=False)
    SUMMARY_JSON.write_text(json.dumps(meta["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(meta["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
