#!/usr/bin/env python3
"""
Build a rolling paper-trading ledger from real forecast and price artifacts.

The ledger is append-friendly and leakage-aware: every row records the signal
date, feature date, model/version artifact used, entry price observed as of the
signal date, and exit status. Returns are only calculated when the exit price is
already present in the data lake.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
MODELING = LAKE / "modeling"
DEFAULT_SNAPSHOT = MODELING / "snapshot_forecasts.csv"
DEFAULT_PRICES = LAKE / "domestic_gold_quotes.csv"
DEFAULT_OUT = MODELING / "paper_trading_ledger.csv"
DEFAULT_SUMMARY = MODELING / "paper_trading_summary.json"
DEFAULT_AFTER = "2026-07-11"


def load_forecasts(path: Path, after: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing forecast artifact: {path}")
    df = pd.read_csv(path)
    required = {
        "snapshot_date",
        "horizon_days",
        "predicted_net_return",
        "q10_predicted_net_return",
        "prob_return_positive",
        "buy_signal",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing required columns: {sorted(missing)}")
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce").dt.normalize()
    after_dt = pd.Timestamp(after)
    # Include the snapshot day itself; it is the first paper signal origin after
    # the model has been frozen on the official snapshot.
    df = df[df["snapshot_date"].ge(after_dt)].copy()
    return df


def load_price_curve(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing domestic price artifact: {path}")
    df = pd.read_csv(path, low_memory=False)
    date_col = "business_date" if "business_date" in df.columns else "date"
    required = {date_col, "buy", "sell"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path.name} missing required columns: {sorted(missing)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df[date_col], errors="coerce").dt.normalize()
    df["buy"] = pd.to_numeric(df["buy"], errors="coerce")
    df["sell"] = pd.to_numeric(df["sell"], errors="coerce")
    if "provider" in df.columns:
        provider_rank = df["provider"].astype(str).str.lower().map(lambda x: 0 if x == "sjc" else 1)
    else:
        provider_rank = 0
    df["_provider_rank"] = provider_rank
    df = df.dropna(subset=["date", "buy", "sell"])
    df = (
        df.sort_values(["date", "_provider_rank", "sell"])
          .drop_duplicates(subset=["date"], keep="first")
          [["date", "buy", "sell"]]
          .sort_values("date")
          .reset_index(drop=True)
    )
    return df


def price_on_or_after(prices: pd.DataFrame, target_date: pd.Timestamp) -> pd.Series | None:
    sub = prices[prices["date"].ge(target_date)]
    if sub.empty:
        return None
    return sub.iloc[0]


def price_on_or_before(prices: pd.DataFrame, target_date: pd.Timestamp) -> pd.Series | None:
    sub = prices[prices["date"].le(target_date)]
    if sub.empty:
        return None
    return sub.iloc[-1]


def make_trade_id(signal_date: pd.Timestamp, horizon: int, model_version: str) -> str:
    compact = signal_date.strftime("%Y%m%d")
    return f"vn_gold_{compact}_{horizon}d_{model_version}"


def build_ledger(forecasts: pd.DataFrame, prices: pd.DataFrame, model_version: str) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, forecast in forecasts.sort_values(["snapshot_date", "horizon_days"]).iterrows():
        signal_date = forecast["snapshot_date"]
        horizon = int(forecast["horizon_days"])
        entry_row = price_on_or_before(prices, signal_date)
        buy_signal = bool(forecast.get("buy_signal"))
        decision = "buy" if buy_signal else "no_buy"
        exit_target = signal_date + timedelta(days=horizon)
        exit_row = price_on_or_after(prices, exit_target)

        entry_sell = float(entry_row["sell"]) if entry_row is not None else None
        entry_buy = float(entry_row["buy"]) if entry_row is not None else None
        entry_date = entry_row["date"].date().isoformat() if entry_row is not None else ""
        exit_buy = None
        exit_date = ""
        realized = None
        status = "no_position"
        if decision == "buy":
            if entry_sell is None:
                status = "blocked_missing_entry_price"
            elif exit_row is None:
                status = "open"
            else:
                exit_buy = float(exit_row["buy"])
                exit_date = exit_row["date"].date().isoformat()
                realized = exit_buy / entry_sell - 1.0
                status = "closed"

        rows.append(
            {
                "trade_id": make_trade_id(signal_date, horizon, model_version),
                "model_version": model_version,
                "feature_date": signal_date.date().isoformat(),
                "signal_date": signal_date.date().isoformat(),
                "horizon_days": horizon,
                "target_exit_date": exit_target.date().isoformat(),
                "entry_date": entry_date,
                "entry_sell_price": entry_sell,
                "entry_buy_price": entry_buy,
                "exit_date": exit_date,
                "exit_buy_price": exit_buy,
                "expected_return": float(forecast["predicted_net_return"]),
                "q10_downside": float(forecast["q10_predicted_net_return"]),
                "prob_positive": float(forecast["prob_return_positive"]),
                "decision": decision,
                "exit_status": status,
                "realized_net_return": realized,
                "spread_at_entry": (entry_sell - entry_buy) if entry_sell is not None and entry_buy is not None else None,
                "source_forecast": str(DEFAULT_SNAPSHOT),
                "source_prices": str(DEFAULT_PRICES),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return pd.DataFrame(rows)


def merge_existing(new_ledger: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    if not out_path.exists() or out_path.stat().st_size == 0:
        return new_ledger
    existing = pd.read_csv(out_path)
    combined = pd.concat([existing, new_ledger], ignore_index=True)
    combined = (
        combined.sort_values(["signal_date", "horizon_days", "generated_at"])
                .drop_duplicates(subset=["trade_id"], keep="last")
                .reset_index(drop=True)
    )
    return combined


def summarize(ledger: pd.DataFrame) -> dict[str, Any]:
    closed = ledger[ledger["exit_status"].eq("closed")].copy()
    buy_rows = ledger[ledger["decision"].eq("buy")].copy()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": int(len(ledger)),
        "buy_rows": int(len(buy_rows)),
        "open_rows": int(ledger["exit_status"].eq("open").sum()) if "exit_status" in ledger else 0,
        "closed_rows": int(len(closed)),
        "no_position_rows": int(ledger["exit_status"].eq("no_position").sum()) if "exit_status" in ledger else 0,
        "date_min": str(ledger["signal_date"].min()) if not ledger.empty else "",
        "date_max": str(ledger["signal_date"].max()) if not ledger.empty else "",
        "by_horizon": [],
        "blockers": [],
    }
    for horizon in sorted(ledger["horizon_days"].dropna().unique()) if not ledger.empty else []:
        sub = ledger[ledger["horizon_days"].eq(horizon)]
        sub_closed = sub[sub["exit_status"].eq("closed")]
        summary["by_horizon"].append(
            {
                "horizon_days": int(horizon),
                "rows": int(len(sub)),
                "buy_rows": int(sub["decision"].eq("buy").sum()),
                "open_rows": int(sub["exit_status"].eq("open").sum()),
                "closed_rows": int(len(sub_closed)),
                "avg_realized_net_return": float(sub_closed["realized_net_return"].mean()) if not sub_closed.empty else None,
                "hit_rate": float((sub_closed["realized_net_return"] > 0).mean()) if not sub_closed.empty else None,
            }
        )
    if summary["closed_rows"] == 0:
        summary["blockers"].append(
            "No paper-trading trade has matured yet; realized performance is intentionally not calculated."
        )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run rolling paper-trading ledger for VN gold signals.")
    parser.add_argument("--forecasts", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--prices", default=str(DEFAULT_PRICES))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--summary", default=str(DEFAULT_SUMMARY))
    parser.add_argument("--after", default=DEFAULT_AFTER)
    parser.add_argument("--model-version", default="snapshot_forecast_v1")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    forecasts = load_forecasts(Path(args.forecasts), args.after)
    prices = load_price_curve(Path(args.prices))
    ledger = build_ledger(forecasts, prices, args.model_version)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = merge_existing(ledger, out_path)
    ledger.to_csv(out_path, index=False, quoting=csv.QUOTE_MINIMAL)
    summary = summarize(ledger)
    Path(args.summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ledger_rows": len(ledger), "out": str(out_path)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
