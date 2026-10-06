#!/usr/bin/env python3
"""
Trading signal export for VN Gold Decision Support.

Reads per-fold decision signals with threshold grid and collapses to a
one-row-per-date export suitable for paper-trading simulation.

Outputs:
    data/lake/modeling/trading_signals.csv          — daily master signal table
    data/lake/modeling/trading_signals_105d.csv     — 105d-only signal table
    data/lake/modeling/trading_signals_summary.json — phase-level aggregates

Signal rule (configurable):
    - Buy when P(return > 0) >= prob_threshold AND q10 >= q10_floor
      (match pods in decision_signals.csv by prob_threshold / q10_floor columns)
    - Default thresholds: prob=0.50, q10_floor=-0.10 (matching ModelingConfig)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

# Force UTF-8 on Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

try:
    from rich.console import Console
    from rich.table import Table

    _RICH = True
except ImportError:
    _RICH = False

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SIGNALS = ROOT / "data" / "lake" / "modeling" / "decision_signals.csv"
DEFAULT_OUT = ROOT / "data" / "lake" / "modeling"
DEFAULT_HORIZON = 105
DEFAULT_PROB = 0.50
DEFAULT_Q10FLOOR = -0.10


def _load_signals(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {
        "date", "horizon_days", "phase", "fold", "model", "prediction_type",
        "actual_net_return", "predicted_net_return",
        "prob_return_positive", "q10_predicted_net_return",
        "selected_model", "prob_threshold", "q10_floor",
        "buy_signal", "strategy_return",
    }
    missing = required - set(df.columns)
    if missing:
        sys.exit(f"decision_signals.csv missing columns: {sorted(missing)}")
    df["date"] = pd.to_datetime(df["date"])
    return df


def _filter_threshold(
    df: pd.DataFrame,
    prob: float,
    q10_floor: float,
    horizon: int | None = None,
) -> pd.DataFrame:
    """Keep rows matching the threshold grid passed AND the preferred horizon."""
    mask = (
        df["prob_threshold"].astype(float).eq(prob)
        & df["q10_floor"].astype(float).eq(q10_floor)
    )
    if horizon is not None:
        mask &= df["horizon_days"].astype(int).eq(horizon)
    out = df[mask].copy()
    if out.empty:
        phase_subsets = df.groupby("phase")["horizon_days"].unique().to_dict()
        sys.exit(
            f"No rows match prob>={prob}, q10>={q10_floor}, horizon={horizon}. "
            f"Available horizons: {phase_subsets}. Check config or use --horizon-only."
        )
    return out


def _collapse_days(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse per-fold rows into one representative row per date/horizon/fold.

    Logic: buy_signal is broadcast from selected_model per fold. Since all
    rows in a date/horizon/fold pod share the same threshold and selected model,
    keep one representative row for each pod. Then add per-date/horizon
    aggregates so downstream paper-trading exports keep the three horizons
    distinct.
    """
    # Keep one representative row per (date, horizon, fold) and drop model-level
    # duplicates within that pod.
    rep = (
        df.sort_values(["date", "horizon_days", "fold", "model"])
          .drop_duplicates(subset=["date", "horizon_days", "fold"], keep="first")
          .copy()
    )

    rep = rep.rename(columns={
        "predicted_net_return": "ensemble_return_forecast",
        "prob_return_positive": "prob_positive",
        "q10_predicted_net_return": "q10_floor_return",
    })

    group_keys = ["date", "horizon_days"]
    any_signal = df.groupby(group_keys)["buy_signal"].max().rename("buy_signal_any")
    sig_counts = df.groupby(group_keys)["buy_signal"].sum().rename("signal_count_per_fold")
    fold_counts = df.groupby(group_keys)["fold"].nunique().rename("fold_count")
    # actual_net_return is identical across models for the same date/horizon pod.
    avg_actual = df.groupby(group_keys)["actual_net_return"].first().rename("avg_actual_return")

    aux = pd.concat([any_signal, sig_counts, fold_counts, avg_actual], axis=1).reset_index()
    merged = rep.merge(aux, on=group_keys, how="left")

    out_cols = [
        "date", "phase", "horizon_days", "fold", "selected_model",
        "ensemble_return_forecast", "prob_positive", "q10_floor_return",
        "buy_signal", "buy_signal_any",
        "signal_count_per_fold", "fold_count", "avg_actual_return",
        "strategy_return", "actual_net_return",
        "prob_threshold", "q10_floor",
    ]
    missing = [c for c in out_cols if c not in merged.columns]
    if missing:
        sys.exit(f"Missing columns after collapse: {missing}")
    return merged[out_cols].copy()


def _phase_summary_flat(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for phase in ["validation", "test"]:
        for horizon in sorted(df["horizon_days"].unique()):
            sub = df[(df["phase"] == phase) & (df["horizon_days"] == horizon)].copy()
            if sub.empty:
                continue
            unique_dates = sub.groupby("date")["buy_signal"].max()
            signal_days = int(unique_dates.sum())
            total_days = len(unique_dates)
            signal_rows = int(sub["buy_signal"].sum())
            strat_ret = sub.loc[sub["buy_signal"], "strategy_return"].mean() if signal_rows else 0.0
            day_ret = sub.loc[sub["buy_signal"], "actual_net_return"].mean() if signal_rows else 0.0
            rows.append({
                "phase": phase,
                "horizon_d": int(horizon),
                "total_days": total_days,
                "signal_days": signal_days,
                "signal_rate_%": round(100.0 * signal_days / max(total_days, 1), 2),
                "signal_rows": signal_rows,
                "fold_count": int(sub["fold_count"].iloc[0]) if "fold_count" in sub.columns else "?",
                "avg_strategy_ret_%": round(100.0 * strat_ret, 4),
                "avg_signal_day_ret_%": round(100.0 * day_ret, 4),
                "selected_model": sub["selected_model"].iloc[0],
            })
    return pd.DataFrame(rows)


def _print_rich_table(df: pd.DataFrame, title: str) -> None:
    if not _RICH:
        return
    console = Console()
    table = Table(title=title, show_header=True, header_style="bold cyan")
    for col in df.columns:
        table.add_column(col, justify="right")
    for _, row in df.iterrows():
        vals = []
        for c in df.columns:
            v = row[c]
            if pd.isna(v):
                vals.append("—")
            elif isinstance(v, float):
                vals.append(f"{v:.4f}")
            else:
                vals.append(str(v))
        table.add_row(*vals)
    console.print(table)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export VN gold trading signals for paper-trading simulation",
    )
    parser.add_argument(
        "--signals",
        default=str(DEFAULT_SIGNALS),
        help="Path to decision_signals.csv",
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument(
        "--prob",
        type=float,
        default=DEFAULT_PROB,
        help=f"P(return>0) threshold (default {DEFAULT_PROB})",
    )
    parser.add_argument(
        "--q10-floor",
        type=float,
        default=DEFAULT_Q10FLOOR,
        help=f"Q10 floor (default {DEFAULT_Q10FLOOR}, e.g. -0.10)",
    )
    parser.add_argument(
        "--horizon",
        type=int,
        default=None,
        help=f"Preferred signal horizon (default: all; use 105 for single horizon)",
    )
    parser.add_argument("--quiet", action="store_true", help="Skip rich console output")
    args = parser.parse_args()

    signals_path = Path(args.signals)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    df = _load_signals(signals_path)
    avail_horizons = sorted(df["horizon_days"].unique())
    if not args.quiet:
        print(f"Loaded {len(df):,} rows from {signals_path}")
        print(f"  Horizons available: {avail_horizons}")
        print(f"  Matching threshold: P>={args.prob}, Q10>={args.q10_floor}")
        print(f"  Target horizon: {args.horizon or 'all'}")

    # Filter rows matching the configured threshold
    filtered = _filter_threshold(df, prob=args.prob, q10_floor=args.q10_floor, horizon=args.horizon)

    horizons_in_filtered = sorted(filtered["horizon_days"].unique())
    if not args.quiet:
        print(f"  Filtered to {len(filtered):,} rows, horizons {horizons_in_filtered}")

    # Collapse to one row per date
    collapsed = _collapse_days(filtered)

    # ─── Write master output ──────────────────────────────────────────────────
    master_fp = out_dir / "trading_signals.csv"
    collapsed.to_csv(master_fp, index=False)
    if not args.quiet:
        print(f"\n[✓] Wrote master → {master_fp}  ({len(collapsed):,} rows)")

    # ─── Write per-horizon outputs ─────────────────────────────────────────────
    horizon_files: dict[int, Path] = {}
    for h in sorted(collapsed["horizon_days"].unique()):
        hdf = collapsed[collapsed["horizon_days"] == h].copy()
        fp = out_dir / f"trading_signals_{int(h)}d.csv"
        hdf.to_csv(fp, index=False)
        horizon_files[int(h)] = fp
        if not args.quiet:
            print(f"[✓] Wrote {int(h)}d  → {fp}  ({len(hdf):,} rows)")

    # ─── Phase summary ─────────────────────────────────────────────────────────
    summary_df = _phase_summary_flat(collapsed)
    summary_json = out_dir / "trading_signals_summary.json"
    payload = {
        "generated_at": str(pd.Timestamp.now()),
        "config": {
            "prob_threshold": args.prob,
            "q10_floor": args.q10_floor,
            "preferred_horizon": args.horizon,
        },
        "phase_summary": summary_df.to_dict(orient="records"),
        "output_files": {
            "master": str(master_fp),
            "by_horizon": {str(h): str(fp) for h, fp in horizon_files.items()},
        },
    }
    with open(summary_json, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    if not args.quiet:
        print(f"[✓] Wrote summary → {summary_json}")

    # ─── Console summary ───────────────────────────────────────────────────────
    if not args.quiet:
        print()
        if _RICH:
            console = Console()
            console.print("[bold green]═══ Phase Summary═══[/bold green]")
            _print_rich_table(summary_df, "Phase / Horizon Results")
            console.print()

        # Print totals compactly
        if "buy_signal_any" in collapsed.columns:
            total_sig = int(collapsed["buy_signal_any"].sum())
        else:
            total_sig = int(collapsed["buy_signal"].sum())
        total_rows = len(collapsed)
        print(f"Total signal days: {total_sig} / {total_rows} ({100 * total_sig / max(total_rows, 1):.1f}%)")

        # Highlight best horizon in test
        test_df = summary_df[summary_df["phase"] == "test"]
        if not test_df.empty:
            best = test_df.loc[test_df["avg_strategy_ret_%"].idxmax()]
            print(f"Best test horizon: {int(best['horizon_d'])}d "
                  f"(signal_rate={best['signal_rate_%']}%, "
                  f"avg_return={best['avg_strategy_ret_%']}%)")

    print("\nDone.")


if __name__ == "__main__":
    main()
