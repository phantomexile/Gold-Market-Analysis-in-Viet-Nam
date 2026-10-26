"""Đối chứng quantile boosting độc lập; không sửa mô hình hay campaign đang dùng."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .stationary_features import build_stationary_features
from .stationary_research import calibrate

PARAMETERS = {
    'lightgbm_quantile': dict(n_estimators=200, learning_rate=.04, max_depth=4, num_leaves=15,
                            min_child_samples=40, reg_lambda=5., random_state=42, n_jobs=4),
    'catboost_multiquantile': dict(iterations=200, learning_rate=.04, depth=4, l2_leaf_reg=5.,
                                  random_seed=42, thread_count=4),
}


def ordered_net_quantiles(hold: np.ndarray, buy: np.ndarray, sell: np.ndarray) -> tuple[np.ndarray, int]:
    """Đổi phân vị giá giữ vàng sang lợi suất mua mới và sắp thứ tự nếu giao nhau.

    Phép đổi là affine có hệ số buy/sell dương nên giữ thứ tự phân vị.
    Việc sắp tăng từng dòng là hậu xử lý khóa trước thử; không dùng actual
    để sửa độ phủ. Số dòng giao nhau được giữ lại để đánh giá chất lượng.
    """
    values = np.asarray(hold, dtype=float)
    buy, sell = np.asarray(buy, dtype=float), np.asarray(sell, dtype=float)
    if (values.shape != (len(buy), 3) or sell.shape != buy.shape or not np.isfinite(values).all()
            or not np.isfinite(buy).all() or not np.isfinite(sell).all() or (buy <= 0).any() or (sell < buy).any()):
        raise ValueError('Phân vị/giá không đúng shape hoặc không hợp lệ.')
    net = (1+values)*buy[:, None]/sell[:, None]-1
    if not np.isfinite(net).all() or (net <= -1).any():
        raise ValueError('Lợi suất phân vị không hợp lệ.')
    crossed = int(np.any(np.diff(net, axis=1)<0, axis=1).sum())
    return np.sort(net, axis=1), crossed


def fit_quantiles(kind: str, train: np.ndarray, y: np.ndarray, test: np.ndarray) -> np.ndarray:
    """LightGBM ba đầu quantile riêng; CatBoost học ba đầu trong một mô hình CPU."""
    if kind == 'lightgbm_quantile':
        from lightgbm import LGBMRegressor
        outputs = []
        for alpha in (.1,.5,.9):
            model = LGBMRegressor(objective='quantile', alpha=alpha, verbosity=-1,
                                  deterministic=True, force_col_wise=True, **PARAMETERS[kind])
            model.fit(train,y)
            outputs.append(model.predict(test))
        return np.column_stack(outputs)
    if kind == 'catboost_multiquantile':
        from catboost import CatBoostRegressor
        model = CatBoostRegressor(loss_function='MultiQuantile:alpha=0.1,0.5,0.9',
                                  task_type='CPU', allow_writing_files=False, verbose=False, **PARAMETERS[kind])
        model.fit(train,y)
        return np.asarray(model.predict(test),dtype=float)
    raise ValueError('Thuật toán đối chứng không hợp lệ.')


def run_challengers(frame: pd.DataFrame, *, start='2021-01-01', progress=print) -> pd.DataFrame:
    """Đúng lịch tháng/cửa sổ train như RF; chỉ calibrate bằng OOS đã đáo hạn."""
    from sklearn.impute import SimpleImputer
    f = frame.copy().sort_values('date').reset_index(drop=True)
    f['date'] = pd.to_datetime(f.date)
    f['exit_date_3m'] = pd.to_datetime(f.exit_date_3m,errors='coerce')
    x = build_stationary_features(f)
    records = []
    for begin in pd.date_range(start,f.date.max(),freq='MS'):
        train_mask = (f.date.ge(begin-pd.DateOffset(years=5)) & f.date.lt(begin)
                      & f.exit_date_3m.lt(begin) & np.isfinite(f.net_return_3m))
        test_mask = f.date.ge(begin) & f.date.lt(begin+pd.DateOffset(months=1))
        if train_mask.sum()<300 or not test_mask.any():
            continue
        train,test = f.loc[train_mask],f.loc[test_mask]
        selected = list(x.columns[(x.loc[train_mask].count()>=200)&(x.loc[train_mask].nunique()>1)])
        if not selected:
            raise ValueError('Thiếu đặc trưng hợp lệ cho cả hai thuật toán.')
        imputer = SimpleImputer(strategy='median')
        x_train = imputer.fit_transform(x.loc[train_mask,selected])
        x_test = imputer.transform(x.loc[test_mask,selected])
        hold_y = ((1+train.net_return_3m)*train.sell_price/train.buy_price-1).to_numpy(float)
        history = pd.DataFrame(records)
        if progress:
            progress(f'{begin:%Y-%m}: train {len(train)}, test {len(test)}, hai thuật toán',flush=True)
        for kind in PARAMETERS:
            raw_hold = fit_quantiles(kind,x_train,hold_y,x_test)
            net,_ = ordered_net_quantiles(raw_hold,test.buy_price.to_numpy(),test.sell_price.to_numpy())
            raw_net = (1+raw_hold)*test.buy_price.to_numpy()[:,None]/test.sell_price.to_numpy()[:,None]-1
            crossing = np.any(np.diff(raw_net,axis=1)<0,axis=1)
            point = net[:,1]
            past = history.loc[(history.candidate==kind)&history.exit_date.lt(begin)
                               &history.date.ge(begin-pd.DateOffset(years=2))&np.isfinite(history.actual)] if not history.empty else pd.DataFrame()
            cal = calibrate(past,point)
            for pos,(_,r) in enumerate(test.iterrows()):
                known = pd.notna(r.exit_date_3m) and r.exit_date_3m<=f.date.max()
                records.append(dict(date=r.date,exit_date=r.exit_date_3m,fold_start=begin,horizon_months=3,candidate=kind,
                    predicted=float(point[pos]),actual=float(r.net_return_3m) if known else np.nan,
                    q10=float(net[pos,0]),q90=float(net[pos,2]),q10_residual=float(cal['q10'][pos]),
                    q10_uncorrected=float(raw_net[pos,0]),q50_uncorrected=float(raw_net[pos,1]),q90_uncorrected=float(raw_net[pos,2]),
                    raw_crossing=bool(crossing[pos]),probability=float(cal['probability'][pos]),raw_probability=float(cal['raw_probability'][pos]),
                    calibration_rows=cal['rows'],calibration_last_exit_date=cal['last_exit'],
                    buy_price=float(r.buy_price),sell_price=float(r.sell_price),
                    train_rows=len(train),train_last_exit_date=train.exit_date_3m.max(),selected_features='|'.join(selected),
                    baseline_probability=float((train.net_return_3m>0).mean()),baseline_q10=float(train.net_return_3m.quantile(.1))))
    return pd.DataFrame(records)


def reference_intervals(reference: pd.DataFrame) -> pd.DataFrame:
    """Bổ sung Q90 residual cho RF/zero bằng đúng OOS trước mỗi tháng như Q10 cũ."""
    p = reference.copy()
    p['q90'] = np.nan
    p['q10_residual'] = p.q10
    for (kind,cutoff), group in p.groupby(['candidate','fold_start']):
        past = p.loc[(p.candidate==kind)&p.exit_date.lt(cutoff)&p.date.ge(cutoff-pd.DateOffset(years=2))&np.isfinite(p.actual)]
        if len(past)>=120 and past.date.dt.to_period('M').nunique()>=6:
            residual = (past.actual-past.predicted).to_numpy(float)
            expected = group.predicted.to_numpy()+float(np.quantile(residual,.1))
            if not np.allclose(expected,group.q10.to_numpy(),atol=1e-10,rtol=0,equal_nan=True):
                raise ValueError('Q10 RF tham chiếu không khớp công thức OOS đang dùng.')
            p.loc[group.index,'q90'] = group.predicted+float(np.quantile(residual,.9))
    return p


def interval_metrics(predictions: pd.DataFrame) -> dict:
    """Độ phủ 80% là mục tiêu Q10–Q90, không phải bảo đảm cho từng dự báo."""
    p = predictions.loc[np.isfinite(predictions.actual)&np.isfinite(predictions.q10)&np.isfinite(predictions.q90)]
    if p.empty:
        return {'rows':0,'coverage':None,'mean_width':None}
    def pinball(column,alpha):
        error = p.actual-p[column]
        return float(np.maximum(alpha*error,(alpha-1)*error).mean())
    return {'rows':len(p),'coverage':float(((p.actual>=p.q10)&(p.actual<=p.q90)).mean()),
            'mean_width':float((p.q90-p.q10).mean()),'pinball_q10':pinball('q10',.1),'pinball_q90':pinball('q90',.9),
            'raw_crossing_rows':int(p.raw_crossing.fillna(False).sum()) if 'raw_crossing' in p else 0}
