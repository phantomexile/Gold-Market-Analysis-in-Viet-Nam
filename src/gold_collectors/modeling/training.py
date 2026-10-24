"""Huấn luyện baseline, mô hình kinh tế lượng và học máy theo các cửa sổ thời gian."""

from __future__ import annotations

import warnings
from typing import Any
import numpy as np
import pandas as pd

from .config import (
    ModelingConfig,
)
from .evaluation import (
    _metrics,
    _phase_for_dates,
    _pinball,
    make_walk_forward_splits,
)


# Tách ma trận đặc trưng và nhãn; giá trị vô hạn được chuyển thành thiếu để xử lý thống nhất.
def _prepare_xy(frame: pd.DataFrame, feature_cols: list[str], target_col: str) -> tuple[pd.DataFrame, pd.Series]:
    cols = [c for c in feature_cols if c in frame.columns]
    x = frame[cols].replace([np.inf, -np.inf], np.nan)
    y = frame[target_col].replace([np.inf, -np.inf], np.nan)
    return x, y



# Lấy trung vị từ tập huấn luyện để điền cả hai tập, không học thông tin từ tập kiểm tra.
def _impute_train_test(x_train: pd.DataFrame, x_test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    med = x_train.median(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x_train.fillna(med), x_test.fillna(med)



# Ưu tiên nhóm đặc trưng lịch sử chính và giới hạn kích thước đầu vào kinh tế lượng.
def _bounded_feature_subset(feature_cols: list[str]) -> list[str]:
    preferred_tokens = (
        "_lag_1d",
        "_lag_21d",
        "_lag_63d",
        "_roll_mean_21d",
        "_roll_std_21d",
        "sell_return_roll_mean_21d",
        "event_count_past_30d",
        "severity_high_past_30d",
        "channel_",
        "days_until_next_",
    )
    selected = [c for c in feature_cols if any(token in c for token in preferred_tokens)]
    if len(selected) < 30:
        selected.extend([c for c in feature_cols if c not in selected])
    return selected[:80]



# Huấn luyện các mốc so sánh theo thời gian, chỉ dùng nhãn đã có kết quả thoát trước cuối fold.
def train_baselines(frame: pd.DataFrame, config: ModelingConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or ModelingConfig()
    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for horizon in config.horizons:
        target_col = f"net_return_{horizon}m"
        for fold_id, split in enumerate(splits, start=1):
            # Nhãn huấn luyện chỉ hợp lệ nếu ngày thoát đã xảy ra trước cuối fold.
            train_mask = (frame["date"] >= split["train_start"]) & (frame[f"exit_date_{horizon}m"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if train.empty or test.empty:
                continue
            model_values = {
                "naive_zero_return": 0.0,
                "historical_mean_return": float(train[target_col].mean()),
                "historical_median_return": float(train[target_col].median()),
            }
            for model_name, value in model_values.items():
                pred = np.full(len(test), value)
                met = _metrics(test[target_col].to_numpy(), pred)
                results.append({"model": model_name, "horizon_months": horizon, "fold": fold_id, "phase": _phase_for_dates(test["date"], config).mode().iat[0], **met})
                for date_value, actual, pred_value, phase in zip(test["date"], test[target_col], pred, _phase_for_dates(test["date"], config)):
                    predictions.append(
                        {
                            "date": date_value,
                            "horizon_months": horizon,
                            "fold": fold_id,
                            "phase": phase,
                            "model": model_name,
                            "prediction_type": "mean",
                            "actual_net_return": actual,
                            "predicted_net_return": pred_value,
                        }
                    )
    return pd.DataFrame(results), pd.DataFrame(predictions)



# Huấn luyện mô hình kinh tế lượng; trả kết quả, dự báo và lý do bị chặn nếu thiếu điều kiện.
def train_econometric(
    frame: pd.DataFrame,
    feature_cols: list[str],
    config: ModelingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    config = config or ModelingConfig()
    blockers: list[str] = []
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
    except Exception as exc:  # pragma: no cover - depends on local env
        return pd.DataFrame(), pd.DataFrame(), [f"statsmodels unavailable: {exc}"]

    exog_candidates = [
        c
        for c in feature_cols
        if any(key in c for key in ("premium_pct_lag_21d", "usd_vnd_mid_lag_21d", "vix_lag_21d", "dxy_index_lag_21d", "treasury_10y_pct_lag_21d"))
    ][:5]
    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    bounded_splits = [s for s in splits if s["test_start"].year in (2023, 2025)]
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for horizon in config.horizons:
        target_col = f"net_return_{horizon}m"
        for fold_id, split in enumerate(bounded_splits, start=1):
            # Loại các dòng có giá thoát rơi vào năm kiểm tra để tránh rò rỉ nhãn.
            train_mask = (frame["date"] >= split["train_start"]) & (frame[f"exit_date_{horizon}m"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if len(train) < 200 or test.empty:
                continue
            try:
                x_train, x_test = _impute_train_test(train[exog_candidates], test[exog_candidates])
                y_train = train[target_col].astype(float)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = SARIMAX(y_train, exog=x_train, order=(1, 0, 0), trend="c", enforce_stationarity=False, enforce_invertibility=False)
                    fit = model.fit(disp=False, maxiter=35)
                    pred = np.asarray(fit.forecast(steps=len(test), exog=x_test))
                met = _metrics(test[target_col].to_numpy(), pred)
                results.append({"model": "sarimax_exog", "horizon_months": horizon, "fold": fold_id, "phase": _phase_for_dates(test["date"], config).mode().iat[0], **met})
                for date_value, actual, pred_value, phase in zip(test["date"], test[target_col], pred, _phase_for_dates(test["date"], config)):
                    predictions.append(
                        {
                            "date": date_value,
                            "horizon_months": horizon,
                            "fold": fold_id,
                            "phase": phase,
                            "model": "sarimax_exog",
                            "prediction_type": "mean",
                            "actual_net_return": actual,
                            "predicted_net_return": pred_value,
                        }
                    )
            except Exception as exc:
                blockers.append(f"SARIMAX horizon {horizon} fold {fold_id} skipped: {exc}")

    vecm_cols = ["mid_price", "global_gold_vnd_per_luong", "usd_vnd"]
    vecm_data = frame[vecm_cols].dropna()
    if len(vecm_data) > 300:
        try:
            sample = np.log(vecm_data.tail(min(len(vecm_data), 2500)))
            sample = sample.replace([np.inf, -np.inf], np.nan).dropna()
            johansen = coint_johansen(sample, det_order=0, k_ar_diff=1)
            rank_pass = bool((johansen.lr1 > johansen.cvt[:, 1]).sum() >= 1)
            blockers.append(f"VECM cointegration screen {'passed' if rank_pass else 'did_not_pass'}; VECM forecast not promoted in v1 notebook.")
        except Exception as exc:
            blockers.append(f"VECM cointegration screen skipped: {exc}")
    else:
        blockers.append("VECM skipped: insufficient complete mid/global_gold_vnd/usd_vnd rows.")

    return pd.DataFrame(results), pd.DataFrame(predictions), blockers



# Huấn luyện mô hình học máy theo fold; giữ tách biệt huấn luyện, kiểm định và kiểm tra.
def train_ml_models(
    frame: pd.DataFrame,
    feature_cols: list[str],
    config: ModelingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    config = config or ModelingConfig()
    blockers: list[str] = []
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import ElasticNet, Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:  # pragma: no cover - depends on local env
        return pd.DataFrame(), pd.DataFrame(), [f"scikit-learn unavailable: {exc}"]

    feature_cols = _bounded_feature_subset(feature_cols)
    optional_models: dict[str, Any] = {}
    try:
        from lightgbm import LGBMRegressor  # type: ignore

        optional_models["lightgbm_mean"] = LGBMRegressor(n_estimators=300, learning_rate=0.03, random_state=config.random_state, verbose=-1)
        optional_models["lightgbm_q10"] = LGBMRegressor(
            objective="quantile", alpha=0.10, n_estimators=300, learning_rate=0.03, random_state=config.random_state, verbose=-1
        )
    except Exception as exc:
        blockers.append(f"LightGBM unavailable; using sklearn quantile fallback: {exc}")
    try:
        from xgboost import XGBRegressor  # type: ignore

        optional_models["xgboost_mean"] = XGBRegressor(
            n_estimators=250, max_depth=3, learning_rate=0.03, subsample=0.9, colsample_bytree=0.9, random_state=config.random_state
        )
    except Exception as exc:
        blockers.append(f"XGBoost unavailable: {exc}")
    try:
        from catboost import CatBoostRegressor  # type: ignore

        optional_models["catboost_mean"] = CatBoostRegressor(
            iterations=300,
            depth=4,
            learning_rate=0.03,
            loss_function="RMSE",
            random_seed=config.random_state,
            verbose=False,
        )
        optional_models["catboost_q10"] = CatBoostRegressor(
            iterations=300,
            depth=4,
            learning_rate=0.03,
            loss_function="Quantile:alpha=0.10",
            random_seed=config.random_state,
            verbose=False,
        )
    except Exception as exc:
        blockers.append(f"CatBoost unavailable: {exc}")

    mean_models = {
        "ridge": make_pipeline(StandardScaler(with_mean=False), Ridge(alpha=1.0)),
        "elastic_net": make_pipeline(StandardScaler(with_mean=False), ElasticNet(alpha=0.0005, l1_ratio=0.2, random_state=config.random_state, max_iter=3000)),
        "random_forest": RandomForestRegressor(n_estimators=48, max_depth=8, min_samples_leaf=18, random_state=config.random_state, n_jobs=-1),
        **{k: v for k, v in optional_models.items() if k.endswith("_mean")},
    }
    quantile_models = {
        "sklearn_gbr_q05": GradientBoostingRegressor(loss="quantile", alpha=0.05, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q10": GradientBoostingRegressor(loss="quantile", alpha=0.10, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q50": GradientBoostingRegressor(loss="quantile", alpha=0.50, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q90": GradientBoostingRegressor(loss="quantile", alpha=0.90, n_estimators=60, max_depth=2, random_state=config.random_state),
        **{k: v for k, v in optional_models.items() if "_q10" in k},
    }

    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for horizon in config.horizons:
        target_col = f"net_return_{horizon}m"
        for fold_id, split in enumerate(splits, start=1):
            # Cùng quy tắc as-of như baseline: chỉ dùng kết quả đã biết tại cuối fold.
            train_mask = (frame["date"] >= split["train_start"]) & (frame[f"exit_date_{horizon}m"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if len(train) < 300 or test.empty:
                continue
            x_train, y_train = _prepare_xy(train, feature_cols, target_col)
            x_test, y_test = _prepare_xy(test, feature_cols, target_col)
            x_train, x_test = _impute_train_test(x_train, x_test)
            phase_values = _phase_for_dates(test["date"], config)

            for model_name, model in mean_models.items():
                try:
                    model.fit(x_train, y_train)
                    pred = np.asarray(model.predict(x_test), dtype=float)
                    met = _metrics(y_test.to_numpy(), pred)
                    results.append({"model": model_name, "horizon_months": horizon, "fold": fold_id, "phase": phase_values.mode().iat[0], **met})
                    for date_value, actual, pred_value, phase in zip(test["date"], y_test, pred, phase_values):
                        predictions.append(
                            {
                                "date": date_value,
                                "horizon_months": horizon,
                                "fold": fold_id,
                                "phase": phase,
                                "model": model_name,
                                "prediction_type": "mean",
                                "actual_net_return": actual,
                                "predicted_net_return": pred_value,
                            }
                        )
                except Exception as exc:
                    blockers.append(f"{model_name} horizon {horizon} fold {fold_id} skipped: {exc}")

            for model_name, model in quantile_models.items():
                try:
                    model.fit(x_train, y_train)
                    pred = np.asarray(model.predict(x_test), dtype=float)
                    quantile = 0.10
                    if "_q05" in model_name:
                        quantile = 0.05
                    elif "_q50" in model_name:
                        quantile = 0.50
                    elif "_q90" in model_name:
                        quantile = 0.90
                    results.append(
                        {
                            "model": model_name,
                            "horizon_months": horizon,
                            "fold": fold_id,
                            "phase": phase_values.mode().iat[0],
                            "mae": np.nan,
                            "rmse": np.nan,
                            "directional_accuracy": np.nan,
                            "pinball_loss": _pinball(y_test.to_numpy(), pred, quantile),
                        }
                    )
                    for date_value, actual, pred_value, phase in zip(test["date"], y_test, pred, phase_values):
                        predictions.append(
                            {
                                "date": date_value,
                                "horizon_months": horizon,
                                "fold": fold_id,
                                "phase": phase,
                                "model": model_name,
                                "prediction_type": f"q{int(quantile * 100):02d}",
                                "actual_net_return": actual,
                                "predicted_net_return": pred_value,
                            }
                        )
                except Exception as exc:
                    blockers.append(f"{model_name} horizon {horizon} fold {fold_id} skipped: {exc}")

    deep_missing = []
    for module_name in ("torch", "pytorch_forecasting", "gluonts"):
        try:
            __import__(module_name)
        except Exception:
            deep_missing.append(module_name)
    if deep_missing:
        blockers.append("DeepAR/TFT skipped: missing optional dependencies " + ", ".join(deep_missing))

    return pd.DataFrame(results), pd.DataFrame(predictions), blockers
