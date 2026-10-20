#!/usr/bin/env python3
"""
Trains the latest snapshot forecasts using all available gold and market data up to the latest date.
Outputs to data/lake/modeling/snapshot_forecasts.csv and updates paper trading ledger.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
# Khi chạy trực tiếp tệp này, Python chỉ thêm scripts/analysis vào sys.path.
# Thêm thư mục gốc để import được hàm ghi sổ từ gói scripts.analysis.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gold_collectors.modeling import ModelingConfig, build_model_frame

HORIZON_LABELS = {21: "1 tháng", 63: "3 tháng", 105: "5 tháng"}


def main():
    print("=" * 65)
    print(" [AI QUANT MODEL] TRAINING LATEST SNAPSHOT FORECASTS")
    print("=" * 65)

    lake = ROOT / "data" / "lake"
    modeling_dir = lake / "modeling"
    modeling_dir.mkdir(parents=True, exist_ok=True)

    print("Step 1: Building feature frame from latest Lake data...")
    config = ModelingConfig(data_lake=lake, output_dir=modeling_dir)
    frame = build_model_frame(config)
    print(f"  -> Model frame shape: {frame.shape}, Date range: {frame['date'].min()} to {frame['date'].max()}")

    # Save updated model frame
    frame.to_csv(modeling_dir / "model_frame_daily.csv", index=False)
    feature_cols = list(frame.attrs.get("feature_columns", []))
    if not feature_cols:
        cols_file = modeling_dir / "feature_columns.json"
        if cols_file.exists():
            feature_cols = json.loads(cols_file.read_text(encoding="utf-8"))
    print(f"  -> Total candidate features: {len(feature_cols)}")

    print("\nStep 2: Training Random Forest & Quantile Gradient Boosting models...")
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    feature_cols = [c for c in feature_cols if c in data.columns]
    latest = data.sort_values("date").iloc[[-1]].copy()
    latest_date_str = str(latest["date"].iloc[0].date())
    print(f"  -> Target snapshot date: {latest_date_str}")

    rows: list[dict[str, Any]] = []

    for horizon in [21, 63, 105]:
        target_col = f"net_return_{horizon}d"
        if target_col not in data.columns:
            print(f"  [WARN] Missing target {target_col}, skipping...")
            continue

        train = data.dropna(subset=[target_col]).copy()
        print(f"\n  [Horizon {horizon}d - {HORIZON_LABELS[horizon]}] Training rows: {len(train):,}")

        # Feature selection by correlation on training set
        scored: list[tuple[str, float]] = []
        y = pd.to_numeric(train[target_col], errors="coerce")
        for col in feature_cols:
            x = pd.to_numeric(train[col], errors="coerce")
            if x.notna().sum() < 200 or x.nunique(dropna=True) < 2:
                continue
            corr = abs(x.corr(y))
            if pd.notna(corr):
                scored.append((col, corr))

        selected = [col for col, _ in sorted(scored, key=lambda item: item[1], reverse=True)[:120]]
        print(f"  -> Selected top {len(selected)} correlated features")

        x_train = train[selected].apply(pd.to_numeric, errors="coerce")
        y_train = y.loc[x_train.index].astype(float)
        x_latest = latest[selected].apply(pd.to_numeric, errors="coerce")

        point_model = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=350,
                        max_depth=7,
                        min_samples_leaf=12,
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            ]
        )
        q10_model = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    GradientBoostingRegressor(
                        loss="quantile",
                        alpha=0.10,
                        n_estimators=250,
                        max_depth=3,
                        learning_rate=0.035,
                        random_state=42,
                    ),
                ),
            ]
        )

        point_model.fit(x_train, y_train)
        pred_train = point_model.predict(x_train)
        residual_std = float(np.nanstd(y_train.to_numpy() - pred_train))
        residual_std = residual_std if np.isfinite(residual_std) and residual_std > 0 else 0.05
        pred = float(point_model.predict(x_latest)[0])

        q10_model.fit(x_train, y_train)
        q10 = float(q10_model.predict(x_latest)[0])
        prob_positive = 1.0 - 0.5 * (1.0 + math.erf((0.0 - pred) / (residual_std * math.sqrt(2))))
        buy_signal = bool((prob_positive >= 0.50) and (q10 >= -0.10))

        print(f"  -> Predicted Net Return: {pred * 100:+.2f}%")
        print(f"  -> Downside Quantile Q10: {q10 * 100:+.2f}%")
        print(f"  -> Win Probability P(>0): {prob_positive * 100:.1f}%")
        print(f"  -> Buy Signal: {buy_signal}")

        rows.append(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_date": latest_date_str,
                "horizon_days": horizon,
                "horizon_label": HORIZON_LABELS[horizon],
                "point_model": "random_forest_snapshot_top120_features",
                "q10_model": "gradient_boosting_quantile_q10_snapshot_top120_features",
                "train_rows": int(len(train)),
                "feature_count": int(len(selected)),
                "predicted_net_return": pred,
                "q10_predicted_net_return": q10,
                "prob_return_positive": prob_positive,
                "buy_signal": buy_signal,
                "status": "ok",
            }
        )

    out_df = pd.DataFrame(rows)
    snapshot_out = modeling_dir / "snapshot_forecasts.csv"
    out_df.to_csv(snapshot_out, index=False)
    print(f"\nStep 3: Saved updated snapshot forecasts to {snapshot_out}")

    # Step 4: Update paper trading ledger
    print("\nStep 4: Updating paper trading ledger...")
    from scripts.analysis.run_rolling_paper_trading import build_ledger_and_summary
    ledger, summary = build_ledger_and_summary(
        snapshot_out,
        lake / "domestic_gold_quotes.csv",
        modeling_dir / "paper_trading_ledger.csv",
        modeling_dir / "paper_trading_summary.json",
        after=latest_date_str,
    )
    print(f"  -> Paper trading ledger updated: {len(ledger)} rows")

    # Step 5: Re-generate web dataset
    print("\nStep 5: Re-building Web dashboard dataset...")
    import subprocess
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_web_data.py")], capture_output=True, text=True, encoding="utf-8")
    print("  -> " + res.stdout.strip())

    print("\n" + "=" * 65)
    print(f" LATEST SNAPSHOT FORECAST COMPLETE FOR: {latest_date_str}")
    print("=" * 65)


if __name__ == "__main__":
    main()
