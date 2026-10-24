"""Điều phối phân tích và giữ API import cũ sau khi tách các trách nhiệm."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .config import (
    ModelingConfig,
    ROOT,
    LAKE,
    REPORTS,
    HORIZONS,
    LAGS,
    LUONG_PER_OZ,
)
from .evaluation import (
    make_walk_forward_splits,
    _phase_for_dates,
    _metrics,
    _pinball,
    evaluate_decision_rules,
)
from .features import (
    _read_csv,
    _path,
    _date_series,
    _safe_numeric,
    _last_quote_per_day,
    _merge_global_asof,
    _merge_gpr_asof,
    _merge_premium,
    _merge_macro_asof,
    _merge_deposit_asof,
    _event_path,
    _merge_events,
    _maybe_merge_news,
    _add_lagged_features,
    build_model_frame,
)
from .reporting import (
    summarize_outputs,
    write_report,
)
from .targets import (
    _add_calendar_month_targets,
)
from .training import (
    _prepare_xy,
    _impute_train_test,
    _bounded_feature_subset,
    train_baselines,
    train_econometric,
    train_ml_models,
)

# Các import phía trên giữ cả helper cũ để notebook và script hiện có tiếp tục
# hoạt động. Mã mới nên import trực tiếp module phụ trách thay vì thêm logic vào đây.


# Chạy lần lượt chuẩn bị dữ liệu, huấn luyện, đánh giá rồi lưu các bảng và báo cáo.
def run_full_analysis(config: ModelingConfig | None = None) -> dict[str, Any]:
    config = config or ModelingConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    frame = build_model_frame(config)
    feature_cols = list(frame.attrs.get("feature_columns", []))
    diagnostics = frame.attrs.get("diagnostics", {})
    frame.to_csv(config.output_dir / "model_frame_daily.csv", index=False)
    (config.output_dir / "feature_columns.json").write_text(json.dumps(feature_cols, indent=2), encoding="utf-8")

    baseline_results, baseline_preds = train_baselines(frame, config)
    econ_results, econ_preds, econ_blockers = train_econometric(frame, feature_cols, config)
    ml_results, ml_preds, ml_blockers = train_ml_models(frame, feature_cols, config)

    results = pd.concat([baseline_results, econ_results, ml_results], ignore_index=True)
    predictions = pd.concat([baseline_preds, econ_preds, ml_preds], ignore_index=True)
    signals = evaluate_decision_rules(predictions, config)

    blockers = list(econ_blockers) + list(ml_blockers)
    if diagnostics:
        blockers.append("Data diagnostics: " + json.dumps(diagnostics, ensure_ascii=False))

    results.to_csv(config.output_dir / "model_results.csv", index=False)
    predictions.to_csv(config.output_dir / "walk_forward_predictions.csv", index=False)
    signals.to_csv(config.output_dir / "decision_signals.csv", index=False)

    summary = summarize_outputs(frame, results, signals, blockers, config)
    (config.output_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    write_report(summary, config)
    return summary
