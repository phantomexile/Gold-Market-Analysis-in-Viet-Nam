#!/usr/bin/env python3
"""
Annotate raw news with real-time availability fields and audit backfill risk.

Existing Google News/headline rows use event_date as publication date, but many
were backfilled in 2026. This script preserves the research mode while creating
strict real-time fields for paper trading and leakage checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
RAW_NEWS = LAKE / "news_raw_headlines_vietnam_gold.csv"
AUDIT_CSV = LAKE / "news_availability_audit.csv"
SUMMARY_JSON = LAKE / "quality" / "news_availability_summary.json"


def date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def provider_from_source(source: str, url: str) -> str:
    if source:
        if ":" in source:
            return source.split(":", 1)[0]
        return source
    host = urlparse(url or "").netloc.lower()
    return host or "unknown"


def url_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def build_audit(df: pd.DataFrame, near_realtime_days: int) -> tuple[pd.DataFrame, dict]:
    out = df.copy()
    out["published_at"] = date_series(out.get("event_date", pd.Series(index=out.index, dtype="object")))
    out["fetched_at"] = date_series(out.get("crawl_date", pd.Series(index=out.index, dtype="object")))
    # availability_from is the first date the row is proven available to this
    # project. For backfilled RSS rows, this is crawl_date, not event_date.
    out["availability_from"] = out["fetched_at"].where(out["fetched_at"].notna(), out["published_at"])
    out["query"] = out.get("query_used", pd.Series("", index=out.index)).fillna("")
    out["provider"] = [
        provider_from_source(str(s or ""), str(u or ""))
        for s, u in zip(out.get("source", pd.Series("", index=out.index)), out.get("url", pd.Series("", index=out.index)))
    ]
    out["url_hash"] = [url_hash(v) for v in out.get("url", pd.Series("", index=out.index))]
    out["backfill_lag_days"] = (out["fetched_at"] - out["published_at"]).dt.days
    out["feature_mode_research"] = "research_event_date_lagged"
    out["feature_mode_strict"] = out["backfill_lag_days"].between(0, near_realtime_days, inclusive="both").map(
        {True: "strict_realtime_verified", False: "backfilled_not_realtime"}
    )
    out.loc[out["published_at"].isna() | out["availability_from"].isna(), "feature_mode_strict"] = "invalid_date"

    audit_cols = [
        "event_date",
        "crawl_date",
        "published_at",
        "fetched_at",
        "availability_from",
        "backfill_lag_days",
        "feature_mode_research",
        "feature_mode_strict",
        "provider",
        "query",
        "category",
        "url_hash",
        "headline",
        "url",
    ]
    for col in audit_cols:
        if col not in out.columns:
            out[col] = ""

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(out)),
        "valid_published_at_rows": int(out["published_at"].notna().sum()),
        "valid_availability_rows": int(out["availability_from"].notna().sum()),
        "strict_realtime_verified_rows": int(out["feature_mode_strict"].eq("strict_realtime_verified").sum()),
        "strict_realtime_verified_share": float(out["feature_mode_strict"].eq("strict_realtime_verified").mean()) if len(out) else 0.0,
        "backfilled_not_realtime_rows": int(out["feature_mode_strict"].eq("backfilled_not_realtime").sum()),
        "provider_counts": out["provider"].value_counts(dropna=False).head(20).to_dict(),
        "date_min": str(out["published_at"].min().date()) if out["published_at"].notna().any() else "",
        "date_max": str(out["published_at"].max().date()) if out["published_at"].notna().any() else "",
        "blockers": [],
    }
    if summary["strict_realtime_verified_share"] < 0.5:
        summary["blockers"].append(
            "Most news rows are backfilled, so strict real-time paper trading should not use them for historical signals."
        )
    return out, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and annotate news real-time availability.")
    parser.add_argument("--raw-news", default=str(RAW_NEWS))
    parser.add_argument("--near-realtime-days", type=int, default=1)
    parser.add_argument("--rewrite-raw", action="store_true", default=True)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    path = Path(args.raw_news)
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_csv(path, low_memory=False)
    annotated, summary = build_audit(df, args.near_realtime_days)
    LAKE.mkdir(parents=True, exist_ok=True)
    (LAKE / "quality").mkdir(parents=True, exist_ok=True)
    # Write the compact audit with ISO-like date strings.
    audit = annotated.copy()
    for col in ["published_at", "fetched_at", "availability_from"]:
        audit[col] = pd.to_datetime(audit[col], errors="coerce").dt.strftime("%Y-%m-%d")
    audit.to_csv(AUDIT_CSV, index=False)
    if args.rewrite_raw:
        existing_cols = list(df.columns)
        new_cols = ["fetched_at", "published_at", "query", "provider", "url_hash", "availability_from", "feature_mode_strict", "backfill_lag_days"]
        raw_out = annotated.copy()
        for col in ["published_at", "fetched_at", "availability_from"]:
            raw_out[col] = pd.to_datetime(raw_out[col], errors="coerce").dt.strftime("%Y-%m-%d")
        ordered = existing_cols + [c for c in new_cols if c not in existing_cols]
        raw_out[ordered].to_csv(path, index=False)
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
