"""Chẩn đoán nhãn và lỗi dự báo; chỉ mô tả nghiên cứu, không cấp quyền giao dịch."""

from __future__ import annotations

import numpy as np
import pandas as pd


def audit_targets(frame: pd.DataFrame, horizons=(1, 3, 5)) -> list[dict]:
    """Đối chiếu nhãn với giá mua lúc thoát / giá bán lúc vào theo tháng lịch.

    Chỉ kiểm chứng tính nhất quán trong model frame; không chứng minh báo giá
    gốc đúng hoặc đã khả dụng trong quá khứ. Ngày chưa có phiên thoát phải
    giữ nhãn thiếu, kể cả khi file vô tình chứa sẵn một lợi suất tương lai.
    """
    f = frame.sort_values('date').reset_index(drop=True)
    dates = pd.DatetimeIndex(pd.to_datetime(f['date']))
    if dates.has_duplicates or dates.hasnans:
        raise ValueError('Ngày dữ liệu trùng hoặc không hợp lệ.')
    buy = pd.to_numeric(f['buy_price'], errors='coerce').to_numpy(float)
    sell = pd.to_numeric(f['sell_price'], errors='coerce').to_numpy(float)
    valid_prices = np.isfinite(buy) & np.isfinite(sell) & (buy > 0) & (sell >= buy)
    results = []
    for h in horizons:
        positions = dates.searchsorted(dates + pd.DateOffset(months=h))
        known = positions < len(f)
        expected_exit = pd.Series(pd.NaT, index=f.index, dtype='datetime64[ns]')
        expected_return = np.full(len(f), np.nan)
        expected_exit.loc[known] = dates[positions[known]].to_numpy()
        valid = known & valid_prices
        valid[known] &= valid_prices[positions[known]]
        expected_return[valid] = buy[positions[valid]] / sell[valid] - 1
        observed_exit = pd.to_datetime(f[f'exit_date_{h}m'], errors='coerce')
        observed_return = pd.to_numeric(f[f'net_return_{h}m'], errors='coerce').to_numpy(float)
        same_exit = observed_exit.eq(expected_exit) | (observed_exit.isna() & expected_exit.isna())
        results.append({
            'horizon_months': h, 'rows': len(f), 'matured_rows': int(known.sum()),
            'pending_rows': int((~known).sum()), 'invalid_price_rows': int((~valid_prices).sum()),
            'exit_mismatches': int((~same_exit).sum()),
            'return_mismatches': int((~np.isclose(expected_return, observed_return, atol=1e-10, rtol=1e-8, equal_nan=True)).sum()),
            'scope': 'internal_frame_consistency_only',
        })
    return results


def _errors(group: pd.DataFrame) -> dict:
    """Dấu bias dương nghĩa là dự báo quá cao; Q10 không phải bảo đảm mức lỗ."""
    actual = group['actual'].to_numpy(float)
    pred = group['predicted'].to_numpy(float)
    out = {'rows': len(group), 'mae': float(np.mean(abs(pred - actual))),
           'zero_mae': float(np.mean(abs(actual))), 'bias': float(np.mean(pred - actual)),
           'actual_mean': float(np.mean(actual)), 'predicted_mean': float(np.mean(pred))}
    if 'prob_return_positive' in group:
        p = group['prob_return_positive'].to_numpy(float)
        finite = np.isfinite(p) & (p >= 0) & (p <= 1)
        p, wins = p[finite], (actual[finite] > 0).astype(float)
        bins = np.minimum((p * 10).astype(int), 9)
        reliability = []
        for b in sorted(set(bins)):
            mask = bins == b
            reliability.append({'bin': int(b), 'rows': int(mask.sum()),
                                'mean_probability': float(p[mask].mean()),
                                'realized_profit_rate': float(wins[mask].mean())})
        out['probability_bins'] = reliability
        out['ece'] = sum(v['rows'] * abs(v['mean_probability'] - v['realized_profit_rate']) for v in reliability) / len(p) if len(p) else None
        out['brier'] = float(np.mean((p - wins) ** 2)) if len(p) else None
    if 'q10_predicted_net_return' in group:
        q = group['q10_predicted_net_return'].to_numpy(float)
        valid = np.isfinite(q)
        out['q10_breach_rate'] = float(np.mean(actual[valid] < q[valid])) if valid.any() else None
    return out


def diagnose_history(predictions: pd.DataFrame, frame: pd.DataFrame) -> dict:
    """Tách lỗi theo năm, tháng và xu hướng chỉ biết trước ngày dự báo.

    Nhóm tăng/giảm dùng biến động giá bán 63 ngày đã qua, không dùng lợi
    suất tương lai để mô tả chế độ mà mô hình có thể nhận biết lúc dự báo.
    Các nhóm chỉ phục vụ tìm điểm yếu, không xác nhận quan hệ nhân quả.
    """
    p = predictions.copy()
    p['date'] = pd.to_datetime(p['date'])
    if p.duplicated(['date', 'horizon_months']).any():
        raise ValueError('Dự báo lịch sử trùng ngày/kỳ hạn.')
    finite = np.isfinite(pd.to_numeric(p['actual'], errors='coerce')) & np.isfinite(pd.to_numeric(p['predicted'], errors='coerce'))
    excluded = int((~finite).sum())
    p = p.loc[finite].copy()
    f = frame.sort_values('date').copy()
    f['date'] = pd.to_datetime(f['date'])
    prices = pd.to_numeric(f['sell_price'], errors='coerce')
    past = prices / prices.shift(63) - 1
    f['regime'] = np.select([past > .03, past < -.03, past.notna()], ['up', 'down', 'sideways'], default='unknown')
    p = p.merge(f[['date', 'regime']], on='date', how='left', validate='many_to_one')
    p['regime'] = p.regime.fillna('unknown')
    p['year'] = p.date.dt.year
    p['month'] = p.date.dt.strftime('%Y-%m')
    out = {'status': 'research_only', 'excluded_nonfinite_rows': excluded,
           'regime_definition': 'past_63_observations_sell_return_above_3pct_below_minus3pct',
           'by_horizon': [], 'by_year': [], 'by_regime': [], 'worst_months': []}
    for h, group in p.groupby('horizon_months'):
        out['by_horizon'].append({'horizon_months': int(h), **_errors(group)})
        for year, rows in group.groupby('year'):
            out['by_year'].append({'horizon_months': int(h), 'year': int(year), **_errors(rows)})
        for regime, rows in group.groupby('regime'):
            out['by_regime'].append({'horizon_months': int(h), 'regime': regime, **_errors(rows)})
        months = [{'horizon_months': int(h), 'month': month, **_errors(rows)} for month, rows in group.groupby('month')]
        out['worst_months'].extend(sorted(months, key=lambda row: row['mae'], reverse=True)[:5])
    return out
