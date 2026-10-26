"""Mô hình lợi suất theo kỳ hạn với đầu vào tỷ lệ và hiệu chỉnh ngoài mẫu theo thời gian."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .stationary_features import build_stationary_features

KINDS = ('zero', 'no_price_change', 'median', 'ridge', 'elasticnet', 'rf_small', 'boosting')


def make_model(kind: str):
    """Khóa trước tham số của bốn mô hình, không dò lại sau khi xem kết quả."""
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import make_pipeline
    from sklearn.linear_model import Ridge, ElasticNet
    from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
    if kind == 'ridge':
        estimator = Ridge(alpha=10., solver='lsqr')
    elif kind == 'elasticnet':
        estimator = ElasticNet(alpha=.001, l1_ratio=.5, max_iter=5000, tol=1e-5, random_state=42)
    elif kind == 'rf_small':
        estimator = RandomForestRegressor(n_estimators=100, max_depth=4, min_samples_leaf=30, random_state=42, n_jobs=-1)
    elif kind == 'boosting':
        estimator = GradientBoostingRegressor(loss='huber', n_estimators=100, max_depth=2, min_samples_leaf=30, random_state=42)
    else:
        raise ValueError(f'Mô hình không hợp lệ: {kind}')
    return make_pipeline(SimpleImputer(strategy='median'), StandardScaler(), estimator)


def fit_predict(kind: str, train: pd.DataFrame, test: pd.DataFrame,
                x_train: pd.DataFrame, x_test: pd.DataFrame, *, horizon=3) -> tuple[np.ndarray, list[str]]:
    """Học biến động giá mua lại, đổi về lợi suất mua mới bằng spread thực tế.

    Mốc zero là lợi suất mua mới 0. Mốc no_price_change giả định giá mua lại
    không đổi: mua mới vẫn lỗ spread. Baseline median học lợi suất ròng train.
    Các mô hình học giá tương đối, nên dự báo không phụ thuộc đơn vị đồng/nghìn đồng.
    """
    if horizon not in (1, 3, 5):
        raise ValueError('Kỳ hạn phải là 1, 3 hoặc 5 tháng.')
    y = train[f'net_return_{horizon}m'].astype(float)
    if kind == 'zero':
        return np.zeros(len(test)), []
    if kind == 'no_price_change':
        return (test.buy_price / test.sell_price - 1).to_numpy(float), []
    if kind == 'median':
        return np.full(len(test), float(y.median())), []
    selected = list(x_train.columns[(x_train.count() >= 200) & (x_train.nunique() > 1)])
    if not selected:
        raise ValueError('Không đủ đặc trưng biến thiên trong train.')
    hold = (1 + y) * train.sell_price / train.buy_price - 1
    model = make_model(kind)
    model.fit(x_train[selected], hold)
    future_hold = model.predict(x_test[selected])
    net = (1 + future_hold) * test.buy_price.to_numpy(float) / test.sell_price.to_numpy(float) - 1
    if not np.isfinite(net).all() or (net <= -1).any():
        raise ValueError('Dự báo lợi suất không hợp lệ.')
    return net, selected


def calibrate(past: pd.DataFrame, predicted: np.ndarray) -> dict:
    """Sigmoid và Q10 residual chỉ học dự báo ngoài mẫu đã đáo hạn.

    Chưa đủ 120 dòng/6 tháng thì để thiếu. Chỉ một lớp nhãn thì không fit
    sigmoid hoặc giả vờ có xác suất đã hiệu chỉnh. Không nhìn nhãn tập test.
    """
    empty = {'probability': np.full(len(predicted), np.nan), 'raw_probability': np.full(len(predicted), np.nan),
             'q10': np.full(len(predicted), np.nan), 'rows': len(past), 'last_exit': pd.NaT}
    if past.empty:
        return empty
    empty['last_exit'] = past.exit_date.max()
    if len(past) < 120 or pd.to_datetime(past.date).dt.to_period('M').nunique() < 6:
        return empty
    residual = (past.actual - past.predicted).to_numpy(float)
    empty['q10'] = predicted + float(np.quantile(residual, .1))
    empty['raw_probability'] = np.array([(np.sum(p + residual > 0) + 1)/(len(residual)+2) for p in predicted])
    labels = (past.actual > 0).astype(int)
    if labels.nunique() < 2 or labels.value_counts().min() < 20:
        return empty
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    sigmoid = make_pipeline(StandardScaler(), LogisticRegression(C=1., random_state=42, max_iter=1000))
    sigmoid.fit(past[['predicted']], labels)
    empty['probability'] = sigmoid.predict_proba(pd.DataFrame({'predicted': predicted}))[:, 1]
    return empty


def run_experiment(frame: pd.DataFrame, *, start='2021-01-01', kinds=KINDS, progress=print, horizon=3) -> pd.DataFrame:
    """Fit đầu tháng, cùng tập ngày cho mọi ứng viên, gồm cả dự báo chưa đáo hạn.

    actual chưa đáo hạn vẫn để NaN trong CSV và không vào điểm chất lượng.
    Các dự báo đó có thể dùng backtest tới giá đã biết ở snapshot, không dùng
    giá tương lai để tính tài sản hoặc chọn mô hình của các tháng trước.
    """
    if horizon not in (1, 3, 5):
        raise ValueError('Kỳ hạn phải là 1, 3 hoặc 5 tháng.')
    target, exit_column = f'net_return_{horizon}m', f'exit_date_{horizon}m'
    f = frame.copy().sort_values('date').reset_index(drop=True)
    f['date'] = pd.to_datetime(f.date)
    f[exit_column] = pd.to_datetime(f[exit_column], errors='coerce')
    f[target] = pd.to_numeric(f[target], errors='coerce')
    x = build_stationary_features(f)
    if len(set(kinds)) != len(kinds) or any(k not in KINDS for k in kinds):
        raise ValueError('Registry ứng viên không hợp lệ.')
    rows = []
    for begin in pd.date_range(start, f.date.max(), freq='MS'):
        train_mask = (f.date.ge(begin-pd.DateOffset(years=5)) & f.date.lt(begin)
                      & f[exit_column].lt(begin) & np.isfinite(f[target]))
        test_mask = f.date.ge(begin) & f.date.lt(begin+pd.DateOffset(months=1))
        if train_mask.sum() < 300 or not test_mask.any():
            continue
        train, test = f.loc[train_mask], f.loc[test_mask]
        if progress:
            progress(f'{horizon}m {begin:%Y-%m}: {len(train)} train, {len(test)} dự báo', flush=True)
        # Q10 trực tiếp là đối chứng chung; phương pháp khóa chính là residual OOS.
        from sklearn.pipeline import make_pipeline
        from sklearn.impute import SimpleImputer
        from sklearn.ensemble import GradientBoostingRegressor
        selected = list(x.columns[(x.loc[train_mask].count() >= 200) & (x.loc[train_mask].nunique() > 1)])
        quantile = make_pipeline(SimpleImputer(strategy='median'), GradientBoostingRegressor(
            loss='quantile', alpha=.1, n_estimators=100, max_depth=2, min_samples_leaf=30, random_state=42))
        quantile.fit(x.loc[train_mask, selected], train[target])
        q_gbr = quantile.predict(x.loc[test_mask, selected])
        history = pd.DataFrame(rows)
        for kind in kinds:
            predicted, used = fit_predict(kind, train, test, x.loc[train_mask], x.loc[test_mask], horizon=horizon)
            past = history.loc[(history.candidate == kind) & history.exit_date.lt(begin)
                               & history.date.ge(begin-pd.DateOffset(years=2)) & np.isfinite(history.actual)] if not history.empty else pd.DataFrame()
            calibrated = calibrate(past, predicted)
            for position, (index, row) in enumerate(test.iterrows()):
                known = pd.notna(row[exit_column]) and row[exit_column] <= f.date.max()
                actual = float(row[target]) if known else np.nan
                rows.append(dict(date=row.date, exit_date=row[exit_column], fold_start=begin,
                                 horizon_months=horizon, candidate=kind, predicted=float(predicted[position]), actual=actual,
                                 buy_price=float(row.buy_price), sell_price=float(row.sell_price),
                                 train_last_exit_date=train[exit_column].max(), train_rows=len(train),
                                 selected_features='|'.join(used), probability=float(calibrated['probability'][position]),
                                 raw_probability=float(calibrated['raw_probability'][position]), q10=float(calibrated['q10'][position]),
                                 q10_gbr=float(q_gbr[position]), calibration_rows=calibrated['rows'],
                                 calibration_last_exit_date=calibrated['last_exit'],
                                 baseline_probability=float((train[target] > 0).mean()),
                                 baseline_q10=float(train[target].quantile(.1))))
    return pd.DataFrame(rows)


def choose_candidate(predictions: pd.DataFrame, cutoff: pd.Timestamp) -> dict:
    """Chọn theo 24 tháng OOS đã đáo hạn, cải thiện <5% thì giữ zero."""
    empty = {'candidate': 'zero', 'scores': {}, 'selection_rows': 0, 'selection_last_exit_date': None}
    if predictions.empty:
        return empty
    p = predictions.loc[(predictions.date < cutoff) & (predictions.date >= cutoff-pd.DateOffset(years=2))
                        & (predictions.exit_date < cutoff) & np.isfinite(predictions.actual)].copy()
    names = predictions.candidate.unique()
    common = p.groupby('date').candidate.nunique()
    p = p.loc[p.date.isin(common[common.eq(len(names))].index)]
    if p.empty or p.date.nunique() < 120 or p.date.dt.to_period('M').nunique() < 6:
        return empty
    p['ae'] = abs(p.predicted-p.actual)
    p['month'] = p.date.dt.to_period('M')
    scores = p.groupby(['candidate', 'month']).ae.mean().groupby('candidate').mean().to_dict()
    if 'zero' not in scores:
        raise ValueError('Thiếu mốc so sánh zero.')
    winner = min(scores, key=lambda k: (scores[k], k != 'zero', k))
    if scores[winner] > .95*scores['zero']:
        winner = 'zero'
    return {'candidate': winner, 'scores': scores, 'selection_rows': int(p.date.nunique()),
            'selection_last_exit_date': str(p.exit_date.max().date())}
