"""Ước lượng xác suất lãi bằng sai số dự báo ngoài mẫu theo thời gian."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

import numpy as np
import pandas as pd


PROBABILITY_METHOD = "temporal_oos_empirical_laplace"
MIN_CALIBRATION_ROWS = 60


def empirical_profit_probability(
    prediction: float, residuals: Iterable[float], *, min_rows: int = MIN_CALIBRATION_ROWS,
) -> float | None:
    """Tính P(lãi) từ sai số thực tế; thiếu mẫu thì trả None, không tự bịa xác suất.

    Sai số bằng lợi suất thật trừ dự báo ngoài mẫu. Với dự báo hiện tại p,
    đếm các trường hợp p + sai số > 0. Làm trơn Laplace bằng một mẫu mỗi lớp
    tránh khẳng định xác suất chắc chắn 0% hoặc 100% từ một tập hữu hạn.
    Các nhãn nhiều tháng có thể chồng lấn, nên đây là ước lượng thực nghiệm,
    không phải bằng chứng hiệu chỉnh xác suất hoặc khoảng tin cậy độc lập.
    """
    errors = np.asarray(list(residuals), dtype=float)
    errors = errors[np.isfinite(errors)]
    if not np.isfinite(prediction) or len(errors) < max(1, min_rows):
        return None
    return float((np.count_nonzero(prediction + errors > 0) + 1) / (len(errors) + 2))


def select_snapshot_features(train: pd.DataFrame, candidates: list[str], target: str) -> list[str]:
    """Chọn tối đa 120 đặc trưng chỉ từ tập huấn luyện của lần dự báo tương ứng."""
    y = pd.to_numeric(train[target], errors="coerce")
    scores = []
    for column in candidates:
        x = pd.to_numeric(train[column], errors="coerce").replace([np.inf, -np.inf], np.nan)
        # Ít hơn 200 quan sát hoặc giá trị không biến thiên không đủ để xét tương quan.
        if x.notna().sum() < 200 or x.nunique(dropna=True) < 2:
            continue
        correlation = abs(x.corr(y))
        if pd.notna(correlation):
            scores.append((column, correlation))
    return [column for column, _ in sorted(scores, key=lambda item: item[1], reverse=True)[:120]]


def make_point_model() -> Any:
    """Cùng cấu hình Random Forest cho dự báo snapshot và các fold hiệu chỉnh."""
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    # Bộ điền thiếu được fit trong pipeline trên train, không nhìn giá trị ngoài mẫu.
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", RandomForestRegressor(
            n_estimators=350, max_depth=7, min_samples_leaf=12, random_state=42, n_jobs=-1,
        )),
    ])


def make_q10_model() -> Any:
    """Dùng cùng cấu hình phân vị 10% cho snapshot và đánh giá lịch sử."""
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    return Pipeline([
        ('imputer', SimpleImputer(strategy='median')),
        ('model', GradientBoostingRegressor(
            loss='quantile', alpha=0.10, n_estimators=250, max_depth=3,
            learning_rate=0.035, random_state=42,
        )),
    ])


def temporal_calibration(
    frame: pd.DataFrame, candidates: list[str], horizon: int,
    *, model_factory: Callable[[], Any] = make_point_model,
    start_year: int | None = None, quantile_start_year: int | None = None,
    quantile_factory: Callable[[], Any] = make_q10_model,
) -> pd.DataFrame:
    """Dự báo ngoài mẫu từng năm trong ba năm gần nhất, loại nhãn chưa đáo hạn.

    Mỗi fold đóng băng mô hình trước đầu năm. Cả lựa chọn đặc trưng và bộ
    điền thiếu chỉ học từ nhãn có exit_date nhỏ hơn đầu fold. Dữ liệu đánh
    giá phải có kết quả vào ngày snapshot; không dùng nhãn tương lai dù CSV
    vô tình đã chứa chúng. Trả chi tiết để có thể kiểm toán từng sai số.
    """
    data = frame.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    target = f"net_return_{horizon}m"
    exit_dates = pd.to_datetime(data[f"exit_date_{horizon}m"], errors="coerce")
    y = pd.to_numeric(data[target], errors="coerce")
    snapshot_date = data["date"].max()
    records = []
    for year in range(start_year if start_year is not None else snapshot_date.year - 2, snapshot_date.year + 1):
        if quantile_start_year is not None:
            print(f'  -> Fold {year}: chỉ học nhãn đã đáo hạn trước đầu năm.', flush=True)
        start, end = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
        train = data.loc[(data["date"] < start) & (exit_dates < start) & np.isfinite(y)]
        test = data.loc[(data["date"] >= start) & (data["date"] < end)
                        & (exit_dates <= snapshot_date) & np.isfinite(y)]
        if len(train) < 300 or test.empty:
            continue
        selected = select_snapshot_features(train, candidates, target)
        if not selected:
            continue
        x_train = train[selected].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        x_test = test[selected].apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
        model = model_factory()
        model.fit(x_train, y.loc[train.index])
        predicted = model.predict(x_test)
        q10 = np.full(len(test), np.nan)
        if quantile_start_year is not None and year >= quantile_start_year:
            quantile_model = quantile_factory()
            quantile_model.fit(x_train, y.loc[train.index])
            q10 = quantile_model.predict(x_test)
        last_exit = exit_dates.loc[train.index].max()
        # Baseline được khóa từ train của chính fold; không tính lại bằng dữ liệu đánh giá.
        baseline_probability = float((y.loc[train.index] > 0).mean())
        baseline_q10 = float(y.loc[train.index].quantile(0.1))
        for index, prediction, quantile in zip(test.index, predicted, q10):
            actual = float(y.loc[index])
            if not np.isfinite(prediction):
                continue
            records.append({
                "horizon_months": horizon, "fold_start": start, "date": data.loc[index, "date"],
                "exit_date": exit_dates.loc[index], "train_last_exit_date": last_exit,
                "actual": actual, "predicted": float(prediction), "residual": actual - float(prediction),
                "q10_predicted_net_return": float(quantile),
                "baseline_probability": baseline_probability, "baseline_q10": baseline_q10,
            })
    return pd.DataFrame(records, columns=[
        "horizon_months", "fold_start", "date", "exit_date", "train_last_exit_date", "actual", "predicted", "residual",
        "q10_predicted_net_return", "baseline_probability", "baseline_q10",
    ])
