#!/usr/bin/env python3
"""
Trains the latest snapshot forecasts using all available gold and market data up to the latest date.
Outputs to data/lake/modeling/snapshot_forecasts.csv and updates paper trading ledger.
"""
from __future__ import annotations

import json
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
from scripts.pipeline.refresh_latest_forecast import report_progress
from scripts.analysis.snapshot_calibration import (
    PROBABILITY_METHOD, empirical_profit_probability, make_point_model, make_q10_model,
    select_snapshot_features, temporal_calibration,
)
from scripts.analysis.snapshot_historical import build_historical_report, run_historical_horizon
from scripts.analysis.snapshot_validation import (
    apply_validation_results, input_availability_blockers, model_source_fingerprint, run_validation,
)

HORIZON_LABELS = {1: "1 tháng", 3: "3 tháng", 5: "5 tháng"}


def main():
    """Huấn luyện, hiệu chỉnh và tự kiểm định trước khi xuất tín hiệu mua từng kỳ hạn."""
    source_id = model_source_fingerprint()
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
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    feature_cols = [c for c in feature_cols if c in data.columns]
    latest = data.sort_values("date").iloc[[-1]].copy()
    latest_date_str = str(latest["date"].iloc[0].date())
    print(f"  -> Target snapshot date: {latest_date_str}")

    rows: list[dict[str, Any]] = []
    calibration_results: list[pd.DataFrame] = []
    historical_results: list[pd.DataFrame] = []

    for horizon in [1, 3, 5]:
        # Báo mốc trước mỗi kỳ hạn vì huấn luyện chiếm phần lớn thời gian cập nhật.
        report_progress({1: 55, 3: 68, 5: 81}[horizon], f"Đang huấn luyện dự báo {horizon} tháng…")
        # Nhãn này dùng phiên SJC đầu tiên từ ngày tròn tháng, không dùng shift theo số dòng.
        target_col = f"net_return_{horizon}m"
        if target_col not in data.columns:
            print(f"  [WARN] Missing target {target_col}, skipping...")
            continue

        # Chỉ học nhãn có giá thoát đã được biết ở ngày snapshot, kể cả khi
        # tệp đầu vào vô tình chứa nhãn điền sẵn cho các ngày tương lai.
        train = data.loc[data[target_col].notna() &
                         (pd.to_datetime(data[f"exit_date_{horizon}m"]) <= latest["date"].iloc[0])].copy()
        print(f"\n  [Horizon {HORIZON_LABELS[horizon]}] Training rows: {len(train):,}")

        y = pd.to_numeric(train[target_col], errors="coerce")
        selected = select_snapshot_features(train, feature_cols, target_col)
        print(f"  -> Selected top {len(selected)} correlated features")

        x_train = train[selected].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        y_train = y.loc[x_train.index].astype(float)
        x_latest = latest[selected].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)

        point_model = make_point_model()
        q10_model = make_q10_model()

        point_model.fit(x_train, y_train)
        pred = float(point_model.predict(x_latest)[0])

        q10_model.fit(x_train, y_train)
        q10 = float(q10_model.predict(x_latest)[0])
        print("  -> Đang tách hiệu chỉnh và đánh giá lịch sử theo từng năm...", flush=True)
        all_folds, historical = run_historical_horizon(data, feature_cols, horizon)
        historical_results.append(historical)
        # Dùng lại dự báo ngoài mẫu đã tính, nhưng giữ đúng cửa sổ ba năm
        # của xác suất snapshot; không trộn các năm xa hơn để thay công thức.
        calibration = all_folds.loc[all_folds['date'] >= pd.Timestamp(latest['date'].iloc[0].year - 2, 1, 1)].copy()
        calibration_results.append(calibration)
        prob_positive = empirical_profit_probability(pred, calibration["residual"])
        # Chưa cấp trạng thái trước khi bước kiểm định độc lập chạy xong.
        # Sau vòng lặp, báo cáo sẽ tự quyết định validated/pending/failed.
        status = "validation_pending" if prob_positive is not None else "insufficient_calibration"
        buy_signal = False

        print(f"  -> Predicted Net Return: {pred * 100:+.2f}%")
        print(f"  -> Downside Quantile Q10: {q10 * 100:+.2f}%")
        print(f"  -> Win Probability P(>0): {prob_positive * 100:.1f}%" if prob_positive is not None
              else "  -> Win Probability P(>0): chưa đủ mẫu ngoài mẫu")
        print(f"  -> Buy Signal: {buy_signal}")

        rows.append(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_date": latest_date_str,
                "horizon_months": horizon,
                "horizon_label": HORIZON_LABELS[horizon],
                "target_date": (latest["date"].iloc[0] + pd.DateOffset(months=horizon)).date().isoformat(),
                "exit_rule": "first_valid_sjc_quote_on_or_after_target_date",
                "point_model": "random_forest_snapshot_top120_calendar_months",
                "q10_model": "gradient_boosting_quantile_q10_snapshot_top120_calendar_months",
                "train_rows": int(len(train)),
                "feature_count": int(len(selected)),
                "predicted_net_return": pred,
                "q10_predicted_net_return": q10,
                "prob_return_positive": prob_positive,
                "buy_signal": buy_signal,
                "status": status,
                "probability_method": PROBABILITY_METHOD,
                "calibration_rows": int(len(calibration)),
                "calibration_folds": int(calibration["fold_start"].nunique()),
                "calibration_start": str(calibration["date"].min().date()) if not calibration.empty else "",
                "calibration_end": str(calibration["date"].max().date()) if not calibration.empty else "",
                "calibration_mae": float(calibration["residual"].abs().mean()) if not calibration.empty else None,
                "calibration_zero_baseline_mae": float(calibration["actual"].abs().mean()) if not calibration.empty else None,
                "validation_reason": "Đang chờ bước kiểm định tự động.",
                # Baseline đóng băng tại lúc phát, không tính lại từ tập đánh giá sau này.
                "baseline_probability": float((y_train > 0).mean()),
                "baseline_q10": float(y_train.quantile(0.10)),
                "entry_sell_price": float(latest["sell_price"].iloc[0]),
            }
        )

    report_progress(90, "Đang kiểm định chất lượng và cập nhật trạng thái mô hình…")
    blockers = input_availability_blockers(frame, feature_cols, lake)
    if model_source_fingerprint() != source_id:
        blockers.append("Mã quy trình đã thay đổi trong lúc huấn luyện; cần chạy lại trước khi kiểm định.")
    validation_report = run_validation(
        modeling_dir, rows, frame, source_id=source_id, blockers=blockers,
    )
    apply_validation_results(rows, validation_report)
    history_predictions = pd.concat(historical_results, ignore_index=True)
    history_report = build_historical_report(
        history_predictions, snapshot_date=latest_date_str,
        protocol_id=validation_report['protocol_id'], blockers=blockers,
    )
    history_report['input_diagnostics'] = frame.attrs.get('diagnostics', {})
    history_report['generated_at'] = datetime.now(timezone.utc).isoformat()
    (modeling_dir / 'snapshot_historical_report.json').write_text(
        json.dumps(history_report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8',
    )
    history_predictions.to_csv(modeling_dir / 'snapshot_historical_predictions.csv', index=False, encoding='utf-8')
    # Trạng thái lịch sử là metadata riêng; không ghi đè status/cờ mua đã được
    # kiểm chứng tiến cứu quyết định, kể cả khi lịch sử vượt toàn bộ tiêu chí.
    history_status = {item['horizon_months']: item['status'] for item in history_report['horizons']}
    for row in rows:
        row['historical_status'] = history_status[row['horizon_months']]
    for row in rows:
        print(f"  -> Kiểm định {row['horizon_label']}: {row['status']} — {row['validation_reason']}", flush=True)
    out_df = pd.DataFrame(rows)
    snapshot_out = modeling_dir / "snapshot_forecasts.csv"
    out_df.to_csv(snapshot_out, index=False)
    # Lưu các dự báo ngoài mẫu để đối chiếu nguồn sai số, không chỉ lưu xác suất cuối.
    pd.concat(calibration_results, ignore_index=True).to_csv(modeling_dir / "snapshot_calibration_predictions.csv", index=False)
    print(f"\nStep 3: Saved updated snapshot forecasts to {snapshot_out}")

    # Step 4: Update paper trading ledger
    report_progress(93, "Đang cập nhật sổ giao dịch mô phỏng…")
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
    report_progress(95, "Đang tạo dữ liệu hiển thị trên web…")
    print("\nStep 5: Re-building Web dashboard dataset...")
    import subprocess
    # Không báo hoàn tất nếu JSON mới chưa dựng được; đồng thời truyền UTF-8
    # để thông báo tiếng Việt không làm script con lỗi khi stdout đi qua pipe.
    import os
    res = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "build_web_data.py")],
        capture_output=True, text=True, encoding="utf-8", check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    print("  -> " + res.stdout.strip())

    print("\n" + "=" * 65)
    print(f" LATEST SNAPSHOT FORECAST COMPLETE FOR: {latest_date_str}")
    print("=" * 65)


if __name__ == "__main__":
    main()
