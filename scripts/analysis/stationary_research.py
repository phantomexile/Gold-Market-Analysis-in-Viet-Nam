"""Mô hình lợi suất theo kỳ hạn với đầu vào tỷ lệ và hiệu chỉnh ngoài mẫu theo thời gian."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .stationary_features import build_stationary_features

KINDS = ('zero', 'no_price_change', 'median', 'ridge', 'elasticnet', 'rf_small', 'rf_median', 'boosting')


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
    elif kind == 'rf_median':
        # Chấm MAE thì học trung vị bằng loss tuyệt đối; RF bình phương học
        # trung bình dễ bị các đợt tăng giá cực mạnh kéo dự báo lên quá mức.
        estimator = RandomForestRegressor(criterion='absolute_error', n_estimators=100,
            max_depth=4, min_samples_leaf=30, random_state=42, n_jobs=-1)
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
    # RF trung vị học đúng lợi suất ròng đang được chấm MAE. Các mô hình cũ
    # giữ mục tiêu giá mua lại để kết quả nghiên cứu vẫn so sánh được.
    model.fit(x_train[selected], y if kind == 'rf_median' else hold)
    future_hold = model.predict(x_test[selected])
    net = future_hold if kind == 'rf_median' else (1 + future_hold) * test.buy_price.to_numpy(float) / test.sell_price.to_numpy(float) - 1
    if not np.isfinite(net).all() or (net <= -1).any():
        raise ValueError('Dự báo lợi suất không hợp lệ.')
    return net, selected


def calibrate(past: pd.DataFrame, predicted: np.ndarray, *, baseline_probability=None, cutoff=None) -> dict:
    """Hiệu chỉnh P/Q10 từ dự báo ngoài mẫu đã đáo hạn, có đối chứng prior.

    Chưa đủ 120 dòng/6 tháng thì để thiếu. Chỉ một lớp nhãn thì không fit
    sigmoid hoặc giả vờ có xác suất đã hiệu chỉnh. Không nhìn nhãn tập test.
    """
    past = past.copy()
    if not past.empty:
        past['date'] = pd.to_datetime(past.date)
        past['exit_date'] = pd.to_datetime(past.exit_date)
        if cutoff is not None:
            past = past.loc[past.date.lt(cutoff) & past.exit_date.lt(cutoff)]
        past = past.loc[np.isfinite(past.actual) & np.isfinite(past.predicted)]
    empty = {'probability': np.full(len(predicted), np.nan), 'raw_probability': np.full(len(predicted), np.nan),
             'sigmoid_probability': np.full(len(predicted), np.nan), 'probability_weight': 0.,
             'q10': np.full(len(predicted), np.nan), 'q10_correction': 0., 'rows': len(past), 'last_exit': pd.NaT}
    if past.empty:
        return empty
    empty['last_exit'] = past.exit_date.max()
    if len(past) < 120 or pd.to_datetime(past.date).dt.to_period('M').nunique() < 6:
        return empty
    residual = (past.actual - past.predicted).to_numpy(float)
    empty['q10'] = predicted + float(np.quantile(residual, .1))
    if 'q10' in past:
        errors = past.loc[np.isfinite(past.q10)]
        if len(errors) >= 120 and errors.date.dt.to_period('M').nunique() >= 6:
            # Sai số của Q10 đã phát trước đây cho biết phần đuôi còn thiếu.
            # Chỉ hạ Q10 khi cần bù coverage, không nâng mức an toàn sau khi
            # thấy một giai đoạn đẹp. Giá trị sửa vẫn phải vượt kiểm tra pinball.
            correction = min(0., float(np.quantile(errors.actual-errors.q10, .1)))
            empty['q10'] += correction
            empty['q10_correction'] = correction
    # Vàng mua bằng vốn tự có có giá trị thu hồi không âm; hiệu chỉnh cộng
    # sai số không được tạo lợi suất đuôi thấp hơn mức mất toàn bộ vốn.
    empty['q10'] = np.maximum(empty['q10'], -1.)
    empty['raw_probability'] = np.array([(np.sum(p + residual > 0) + 1)/(len(residual)+2) for p in predicted])
    labels = (past.actual > 0).astype(int)
    if labels.nunique() < 2 or labels.value_counts().min() < 20:
        return empty
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    sigmoid = make_pipeline(StandardScaler(), LogisticRegression(C=1., random_state=42, max_iter=1000))
    sigmoid.fit(past[['predicted']], labels)
    probability = sigmoid.predict_proba(pd.DataFrame({'predicted': predicted}))[:, 1]
    empty['sigmoid_probability'] = probability
    weight = 1. if baseline_probability is None else 0.
    if baseline_probability is not None:
        if not np.isfinite(baseline_probability) or not 0 <= baseline_probability <= 1:
            raise ValueError('Prior xác suất phải nằm trong 0 đến 1.')
        if {'sigmoid_probability', 'baseline_probability'}.issubset(past.columns):
            known = past.loc[np.isfinite(past.sigmoid_probability) & np.isfinite(past.baseline_probability)].copy()
            if len(known) >= 120 and known.date.dt.to_period('M').nunique() >= 6:
                # Chọn trọng số bằng những xác suất đã phát trước origin,
                # không chấm sigmoid vừa fit trên chính nhãn fit của nó.
                # Mỗi tháng có trọng số ngang nhau dù số báo giá khác nhau.
                scores = {}
                for w in (0., .25, .5, .75, 1.):
                    mix = w*known.sigmoid_probability+(1-w)*known.baseline_probability
                    loss = (mix-known.actual.gt(0).astype(float))**2
                    scores[w] = float(loss.groupby(known.date.dt.to_period('M')).mean().mean())
                weight = min(scores, key=lambda w: (scores[w], w))
        probability = weight*probability+(1-weight)*float(baseline_probability)
    empty['probability_weight'] = weight
    empty['probability'] = probability
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
            prior = float((train[target] > 0).mean())
            calibrated = calibrate(past, predicted, baseline_probability=prior, cutoff=begin)
            for position, (index, row) in enumerate(test.iterrows()):
                known = pd.notna(row[exit_column]) and row[exit_column] <= f.date.max()
                actual = float(row[target]) if known else np.nan
                rows.append(dict(date=row.date, exit_date=row[exit_column], fold_start=begin,
                                 horizon_months=horizon, candidate=kind, predicted=float(predicted[position]), actual=actual,
                                 buy_price=float(row.buy_price), sell_price=float(row.sell_price),
                                 train_last_exit_date=train[exit_column].max(), train_rows=len(train),
                                 selected_features='|'.join(used), probability=float(calibrated['probability'][position]),
                                 raw_probability=float(calibrated['raw_probability'][position]), q10=float(calibrated['q10'][position]),
                                 sigmoid_probability=float(calibrated['sigmoid_probability'][position]),
                                 probability_weight=calibrated['probability_weight'], q10_correction=calibrated['q10_correction'],
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


def select_deployable_candidate(predictions: pd.DataFrame, cutoff: pd.Timestamp, *, horizon=3) -> dict:
    """Chỉ đưa ML lên khi có lợi thế MAE ổn định; không ép chọn một RF thua zero.

    Đây là lựa chọn trên lịch sử phát triển đã biết, không phải kiểm định độc
    lập. Dùng cùng ngày cho mọi ứng viên, nhãn phải đáo hạn trước cutoff,
    và bootstrap theo khối tháng để tránh coi lợi suất chồng lấn là độc lập.
    """
    from .snapshot_validation import load_policy
    from .stationary_evaluation import block_interval
    policy = load_policy()
    p = predictions.copy()
    p['date'] = pd.to_datetime(p.date)
    p['exit_date'] = pd.to_datetime(p.exit_date)
    names = sorted(p.candidate.unique())
    if 'zero' not in names:
        raise ValueError('Lựa chọn mô hình cần mốc lợi suất zero.')
    if p.duplicated(['date', 'candidate']).any():
        raise ValueError('Mỗi ứng viên chỉ có một dự báo mỗi ngày.')
    p = p.loc[p.date.ge('2023-01-01') & p.date.lt(cutoff) & p.exit_date.lt(cutoff)
              & np.isfinite(p.actual) & np.isfinite(p.predicted)]
    counts = p.groupby('date').candidate.nunique()
    p = p.loc[p.date.isin(counts[counts.eq(len(names))].index)]
    assessments = {}
    for name, group in p.groupby('candidate'):
        mae, zero = float(abs(group.predicted-group.actual).mean()), float(abs(group.actual).mean())
        improvement = 1-mae/zero if zero > 0 else 0.
        yearly = group.groupby(group.date.dt.year).apply(
            lambda rows: float(abs(rows.predicted-rows.actual).mean()) < float(abs(rows.actual).mean()))
        interval = block_interval(group, horizon=horizon)
        qualifies = (len(group) >= policy['min_matured_rows']
                     and (group.date.max()-group.date.min()).days >= policy['min_origin_span_days']
                     and improvement >= policy['min_mae_improvement']
                     and int(yearly.sum()) >= 3 and interval['lower'] is not None and interval['lower'] > 0)
        assessments[name] = dict(mae=mae, zero_mae=zero, improvement=improvement,
                                 stable_years=int(yearly.sum()), interval=interval, qualified=bool(qualifies))
    eligible = [name for name, item in assessments.items() if name != 'zero' and item['qualified']]
    winner = min(eligible, key=lambda name: (assessments[name]['mae'], name)) if eligible else 'zero'
    return dict(candidate=winner, improved_over_baseline=winner != 'zero', candidates=assessments,
                selection_rows=int(p.date.nunique()), cutoff=str(pd.Timestamp(cutoff).date()),
                selection_last_exit_date=str(p.exit_date.max().date()) if not p.empty else None,
                reason='Đạt tiêu chí MAE trên lịch sử phát triển.' if eligible else
                       'Chưa có ứng viên cải thiện MAE đủ ổn định; dùng mốc lợi suất 0 làm dự phòng.')
