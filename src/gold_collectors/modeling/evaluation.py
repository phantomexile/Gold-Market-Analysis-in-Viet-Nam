"""Chia tập thời gian, tính sai số và đánh giá quy tắc mua từ kết quả dự báo."""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

from .config import (
    ModelingConfig,
)


# Chia các cửa sổ kiểm tra nối tiếp; tập huấn luyện chỉ chứa thời gian trước kỳ kiểm tra.
def make_walk_forward_splits(
    dates: pd.Series,
    *,
    initial_train_end: str = "2022-12-31",
    final_test_end: str = "2026-12-31",
) -> list[dict[str, pd.Timestamp]]:
    """Create chronological expanding-window folds with yearly test windows."""

    min_date = pd.to_datetime(dates.min()).normalize()
    max_date = pd.to_datetime(dates.max()).normalize()
    initial_end = min(pd.Timestamp(initial_train_end), max_date)
    final_end = min(pd.Timestamp(final_test_end), max_date)
    splits: list[dict[str, pd.Timestamp]] = []
    train_end = initial_end
    while train_end < final_end:
        test_start = train_end + pd.Timedelta(days=1)
        test_end = min(pd.Timestamp(year=test_start.year, month=12, day=31), final_end)
        if test_start > max_date:
            break
        splits.append(
            {
                "train_start": min_date,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        train_end = test_end
    return splits



# Gắn trạng thái train/validation/test theo các khoảng ngày trong cấu hình.
def _phase_for_dates(dates: pd.Series, config: ModelingConfig) -> pd.Series:
    values = pd.Series("train", index=dates.index, dtype="object")
    values[(dates >= pd.Timestamp(config.validation_start)) & (dates <= pd.Timestamp(config.validation_end))] = "validation"
    values[(dates >= pd.Timestamp(config.test_start)) & (dates <= pd.Timestamp(config.test_end))] = "test"
    return values



# Tính sai số và tỷ lệ đúng chiều trên các cặp thực tế/dự báo hữu hạn.
def _metrics(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    mask = np.isfinite(actual) & np.isfinite(pred)
    if mask.sum() == 0:
        return {"mae": np.nan, "rmse": np.nan, "directional_accuracy": np.nan}
    y = actual[mask]
    p = pred[mask]
    return {
        "mae": float(np.mean(np.abs(y - p))),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "directional_accuracy": float(np.mean(np.sign(y) == np.sign(p))),
    }



# Đánh giá dự báo phân vị; bỏ qua cặp thiếu để kết quả không bị nhiễu NaN.
def _pinball(actual: np.ndarray, pred: np.ndarray, q: float) -> float:
    mask = np.isfinite(actual) & np.isfinite(pred)
    if mask.sum() == 0:
        return np.nan
    diff = actual[mask] - pred[mask]
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))



# Chọn mô hình và áp dụng ngưỡng xác suất/lợi suất phân vị để tạo tín hiệu theo logic hiện tại.
def evaluate_decision_rules(
    predictions: pd.DataFrame,
    config: ModelingConfig | None = None,
) -> pd.DataFrame:
    config = config or ModelingConfig()
    if predictions.empty:
        return pd.DataFrame()

    mean_preds = predictions[predictions["prediction_type"].eq("mean")].copy()
    validation = mean_preds[mean_preds["phase"].eq("validation")]
    # Pre-compute MAE and directional accuracy per model per horizon.
    # For decision signals we need a model whose predictions VARY across
    # time — "historical_mean_return" returns a constant value, which makes
    # prob_return_positive identical for every date, so the threshold either
    # fires on every day or none.  Score = 0.5 * normalized_MAE + 0.5 * (1 - DA)
    # to pick a balanced model; then keep lowest-MAE among candidates whose
    # predicted_net_return spans > 1% of its own std (i.e. non-constant).
    _skip = {"naive_zero_return", "historical_mean_return", "historical_median_return"}

    def _model_score(g: pd.DataFrame) -> float:
        mae = np.mean(np.abs(g["actual_net_return"] - g["predicted_net_return"]))
        da = np.mean(np.sign(g["actual_net_return"]) == np.sign(g["predicted_net_return"]))
        return 0.5 * (mae / 0.05) + 0.5 * (1.0 - da)  # normalize MAE by ~5% max

    best_models: dict[int, str] = {}
    for horizon in config.horizons:
        subset = validation[validation["horizon_months"].eq(horizon)]
        if subset.empty:
            subset = mean_preds[mean_preds["horizon_months"].eq(horizon)]
        if subset.empty:
            continue
        scored: dict[str, float] = {}
        for model_name, grp in subset.groupby("model"):
            if model_name in _skip:
                continue
            if grp["predicted_net_return"].std(skipna=True) < 1e-6:
                continue  # constant output — useless for threshold signal
            scored[model_name] = _model_score(grp)
        if not scored:
            # fall back to lowest-MAE, but warn is handled upstream
            fallback = subset.groupby("model").apply(
                lambda g: np.mean(np.abs(g["actual_net_return"] - g["predicted_net_return"])),
                include_groups=False,
            )
            if not fallback.empty:
                best_models[horizon] = str(fallback.sort_values().index[0])
            continue
        best_models[horizon] = min(scored, key=scored.get)

    rows: list[pd.DataFrame] = []
    for horizon, model_name in best_models.items():
        selected = mean_preds[(mean_preds["horizon_months"].eq(horizon)) & (mean_preds["model"].eq(model_name))].copy()
        if selected.empty:
            continue
        residual_std = float((selected["actual_net_return"] - selected["predicted_net_return"]).std(skipna=True))
        residual_std = residual_std if np.isfinite(residual_std) and residual_std > 0 else 0.05
        selected["prob_return_positive"] = 1.0 - selected["predicted_net_return"].apply(lambda x: 0.5 * (1.0 + math.erf((0.0 - x) / (residual_std * math.sqrt(2)))))

        q10 = predictions[
            predictions["horizon_months"].eq(horizon)
            & predictions["prediction_type"].eq("q10")
            & predictions["model"].astype(str).str.contains("q10")
        ].copy()
        if not q10.empty:
            q10 = q10.sort_values(["date", "model"]).drop_duplicates(["date", "horizon_months"], keep="first")
            selected = selected.merge(
                q10[["date", "horizon_months", "predicted_net_return"]].rename(columns={"predicted_net_return": "q10_predicted_net_return"}),
                on=["date", "horizon_months"],
                how="left",
            )
        else:
            selected["q10_predicted_net_return"] = selected["predicted_net_return"] - 1.2816 * residual_std

        selected["selected_model"] = model_name
        for prob_threshold in (0.55, config.decision_prob_threshold, 0.65):
            for q10_floor in (-0.03, config.decision_q10_floor, -0.07):
                out = selected.copy()
                out["prob_threshold"] = prob_threshold
                out["q10_floor"] = q10_floor
                out["buy_signal"] = (out["prob_return_positive"] >= prob_threshold) & (out["q10_predicted_net_return"] >= q10_floor)
                rows.append(out)

    if not rows:
        return pd.DataFrame()
    signals = pd.concat(rows, ignore_index=True)
    signals["strategy_return"] = np.where(signals["buy_signal"], signals["actual_net_return"], 0.0)
    return signals
