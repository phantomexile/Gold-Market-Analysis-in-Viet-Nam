"""Đánh giá tài sản và bất định của tín hiệu, không cộng lợi suất chồng lấn."""

from __future__ import annotations

import numpy as np
import pandas as pd
from .forecast_signals import direct_signal


def backtest(predictions: pd.DataFrame, prices: pd.DataFrame, *, margin=.01) -> dict:
    """Một danh mục tiền mặt/vàng, quyết định đầu tháng, không bán khống.

    Mua ở sell_price, bán và mark-to-market ở buy_price. Quan sát giữ nguyên
    trạng thái đang có. Equity bắt đầu 1 để drawdown bao gồm cả phí spread
    ngay giao dịch đầu tiên. Vị thế cuối kỳ được định giá theo giá mua lại.
    """
    p = predictions.sort_values('date').copy()
    f = prices.sort_values('date').copy()
    if p.empty:
        raise ValueError('Không có dự báo để backtest.')
    for rows in (p, f):
        rows['date'] = pd.to_datetime(rows.date)
        if rows.date.duplicated().any():
            raise ValueError('Backtest cần dự báo/báo giá duy nhất từng ngày.')
    f = f.loc[f.date.between(p.date.min(), p.date.max())]
    if f.empty or not np.isfinite(f[['buy_price', 'sell_price']].to_numpy(float)).all() or (f.buy_price <= 0).any() or (f.sell_price < f.buy_price).any():
        raise ValueError('Báo giá backtest không hợp lệ.')
    first = p.groupby(p.date.dt.to_period('M'), sort=True).head(1).set_index('date')
    cash, units, peak, drawdown = 1., 0., 1., 0.
    buys, sells, switches = 0, 0, 0
    previous, last_signal = None, 'observe'
    for row in f.itertuples():
        if row.date in first.index:
            band = float(first.at[row.date, 'margin']) if 'margin' in first else margin
            signal = direct_signal(first.at[row.date, 'predicted'], row.buy_price, row.sell_price, margin=band)['signal']
            switches += int(previous is not None and previous != signal)
            previous, last_signal = signal, signal
            if signal == 'buy' and units == 0:
                units, cash = cash / row.sell_price, 0.
                buys += 1
            elif signal == 'sell' and units > 0:
                cash, units = units * row.buy_price, 0.
                sells += 1
        equity = cash + units * row.buy_price
        peak = max(peak, equity)
        drawdown = min(drawdown, equity/peak-1)
    hold_path = f.buy_price.to_numpy(float) / float(f.sell_price.iloc[0])
    hold_peaks = np.maximum.accumulate(np.r_[1., hold_path])[1:]
    total = equity - 1
    return {'total_return': float(total), 'max_drawdown': float(drawdown), 'buys': buys, 'sells': sells,
            'completed_trades': sells, 'open_position': bool(units), 'signal_switches': switches,
            'buy_hold_return': float(hold_path[-1]-1), 'buy_hold_max_drawdown': float(np.min(hold_path/hold_peaks-1)),
            'cash_return': 0., 'excess_vs_buy_hold': float(total-(hold_path[-1]-1)),
            'observations': len(f), 'last_signal': last_signal}


def block_interval(predictions: pd.DataFrame, *, repeats=500, horizon=3) -> dict:
    """Khoảng bootstrap 90% theo khối dài bằng kỳ hạn, MAE bình quân tháng.

    Kết quả mô tả bất định trên lịch sử đã dùng phát triển; không biến thành
    bằng chứng tiến cứu. Khối 1/3/5 tháng giữ phụ thuộc theo kỳ hạn tương ứng.
    """
    p = predictions.loc[np.isfinite(predictions.actual) & np.isfinite(predictions.predicted)].copy()
    p['month'] = pd.to_datetime(p.date).dt.to_period('M')
    p['ae'] = abs(p.predicted-p.actual)
    p['zero'] = abs(p.actual)
    monthly = p.groupby('month')[['ae', 'zero']].mean().to_numpy()
    if len(monthly) < 6 or monthly[:, 1].mean() <= 0:
        return {'lower': None, 'upper': None, 'block_months': horizon, 'months': len(monthly)}
    rng = np.random.default_rng(42)
    results = []
    for _ in range(repeats):
        starts = rng.integers(0, len(monthly), size=int(np.ceil(len(monthly)/horizon)))
        indices = np.concatenate([(s + np.arange(horizon)) % len(monthly) for s in starts])[:len(monthly)]
        means = monthly[indices].mean(axis=0)
        results.append(1 - means[0]/means[1])
    low, high = np.quantile(results, [.05, .95])
    return {'lower': float(low), 'upper': float(high), 'block_months': horizon, 'months': len(monthly), 'confidence': .9}


def signal_diagnostics(predictions: pd.DataFrame, *, margin=.01) -> dict:
    """Độ đúng mua/bán trên cửa sổ không chồng lấn, tách hai bối cảnh sở hữu."""
    last_exit = pd.Timestamp.min
    actions = {'buy': [], 'sell': [], 'observe': []}
    missed_buys, missed_sells = [], []
    for row in predictions.sort_values('date').itertuples():
        if pd.isna(row.exit_date) or not np.isfinite(row.actual) or row.date < last_exit:
            continue
        band = getattr(row, 'margin', margin)
        signal = direct_signal(row.predicted, row.buy_price, row.sell_price, margin=band)['signal']
        hold_actual = (1+row.actual)*row.sell_price/row.buy_price-1
        outcome = row.actual if signal == 'buy' else (-hold_actual if signal == 'sell' else 0.)
        actions[signal].append(outcome)
        if signal == 'observe':
            missed_buys.append(row.actual > band)
            missed_sells.append(hold_actual < -band)
        last_exit = row.exit_date
    result = {name: {'windows': len(values), 'favorable_rate': float(np.mean(np.array(values)>0)) if values and name != 'observe' else None,
                   'mean_counterfactual_return': float(np.mean(values)) if values and name != 'observe' else None}
            for name, values in actions.items()}
    result['observe'].update(missed_profitable_buy_rate=float(np.mean(missed_buys)) if missed_buys else None,
                             missed_beneficial_sell_rate=float(np.mean(missed_sells)) if missed_sells else None)
    return result


def select_path(predictions: pd.DataFrame, prices: pd.DataFrame, *, start='2023-01-01') -> tuple[pd.DataFrame, list[dict]]:
    """Lựa chọn cấu hình và ngưỡng trước từng tháng, không dùng điểm của tháng đó.

    Chọn mô hình bằng nhãn đã đáo hạn. Chọn ngưỡng bằng danh mục lịch sử
    đánh dấu theo giá đã biết trước đầu tháng; thiếu 3 vòng mua-bán thì giữ 1%.
    Lãi danh mục chỉ để chọn ngưỡng, không gọi MAE là hiệu quả giao dịch.
    """
    from .stationary_research import choose_candidate
    path, choices = [], []
    for cutoff in pd.date_range(start, predictions.date.max(), freq='MS'):
        selection = choose_candidate(predictions, cutoff)
        name = selection['candidate']
        past = predictions.loc[(predictions.candidate == name) & (predictions.date < cutoff)
                               & (predictions.date >= cutoff-pd.DateOffset(years=2))]
        margins = []
        if not past.empty:
            for margin in (.005, .01, .02):
                result = backtest(past, prices.loc[prices.date < cutoff], margin=margin)
                margins.append({'margin': margin, **result})
        eligible = [r for r in margins if r['completed_trades'] >= 3]
        band = max(eligible, key=lambda r: (r['total_return'], -abs(r['margin']-.01)))['margin'] if eligible else .01
        selected = predictions.loc[(predictions.candidate == name) & (predictions.date >= cutoff)
                                   & (predictions.date < cutoff+pd.DateOffset(months=1))].copy()
        if not selected.empty:
            selected['margin'] = band
            path.append(selected)
            choices.append({'month': cutoff.strftime('%Y-%m'), 'margin': band, **selection,
                            'margin_scores': margins, 'margin_last_date': str(past.date.max().date()) if not past.empty else None})
    return pd.concat(path, ignore_index=True) if path else pd.DataFrame(), choices


def evaluate_candidate(predictions: pd.DataFrame, prices: pd.DataFrame, *, horizon=3) -> dict:
    """Giữ nguyên ngưỡng chất lượng dự án, nhưng lịch sử chỉ là research_only.

    Báo rõ tỷ lệ dự báo có đủ P/Q10, tránh chỉ chấm tập con đẹp. Quy tắc
    qualification thêm ổn định theo năm, khoảng bất định và danh mục để
    ngăn một con số MAE tổng che lỗi tín hiệu thực tế.
    """
    from .snapshot_validation import evaluate_horizon, load_policy
    p = predictions.copy()
    matured = p.loc[np.isfinite(p.actual) & pd.to_datetime(p.exit_date).le(prices.date.max())]
    enough = matured.loc[np.isfinite(matured.probability) & np.isfinite(matured.q10)]
    rows = []
    for r in enough.itertuples():
        rows.append(dict(horizon_months=horizon, snapshot_date=r.date.date().isoformat(), exit_date=r.exit_date.date().isoformat(),
                         actual=r.actual, predicted_net_return=r.predicted, prob_return_positive=r.probability,
                         q10_predicted_net_return=r.q10, baseline_probability=r.baseline_probability, baseline_q10=r.baseline_q10))
    quality = evaluate_horizon(rows, horizon, load_policy())
    # Tuyệt đối không giữ nhãn validated của hàm đánh giá dùng chung trong báo cáo nghiên cứu.
    quality['status'] = {'validated': 'research_passed', 'validation_failed': 'research_failed',
                         'validation_pending': 'research_insufficient'}[quality['status']]
    by_year = []
    for year, group in matured.groupby(matured.date.dt.year):
        mae, zero = float(abs(group.predicted-group.actual).mean()), float(abs(group.actual).mean())
        by_year.append({'year': int(year), 'rows': len(group), 'mae': mae, 'zero_mae': zero,
                        'improvement': 1-mae/zero if zero > 0 else None})
    mae = float(abs(matured.predicted-matured.actual).mean()) if len(matured) else None
    zero = float(abs(matured.actual).mean()) if len(matured) else None
    interval = block_interval(matured, horizon=horizon)
    portfolio = backtest(p, prices)
    alternative = {}
    # So sánh phương pháp P/Q10 trên cùng tập đủ số liệu, không âm thầm đổi
    # sang phương pháp thắng bảng sau khi nhìn toàn bộ giai đoạn đánh giá.
    for column in ('raw_probability', 'probability'):
        if column in matured:
            valid = matured.loc[np.isfinite(matured[column])]
            alternative[column] = {'rows': len(valid), 'brier': float(np.mean((valid[column]-(valid.actual>0).astype(float))**2)) if len(valid) else None}
    for column in ('q10', 'q10_gbr'):
        if column in matured:
            valid = matured.loc[np.isfinite(matured[column])]
            residual = valid.actual-valid[column]
            alternative[column] = {'rows': len(valid), 'breach_rate': float((residual<0).mean()) if len(valid) else None,
                                   'pinball': float(np.maximum(.1*residual, -.9*residual).mean()) if len(valid) else None}
    checks = dict(
        quality_all=all(quality['checks'].values()),
        calibration_coverage=len(enough) == len(matured) and len(matured) > 0,
        stable_years=sum(y['improvement'] is not None and y['improvement'] > 0 for y in by_year) >= 3,
        positive_block_lower=interval['lower'] is not None and interval['lower'] > 0,
        portfolio_vs_cash=portfolio['total_return'] > 0,
        portfolio_vs_buy_hold=portfolio['excess_vs_buy_hold'] >= 0,
        portfolio_drawdown=portfolio['max_drawdown'] >= portfolio['buy_hold_max_drawdown'],
        enough_completed_trades=portfolio['completed_trades'] >= 6,
    )
    return {'status': 'research_only', 'independent_validation': False, 'development_qualified': all(checks.values()),
            'checks': checks, 'rows': len(p), 'matured_rows': len(matured), 'calibrated_rows': len(enough),
            'mae': mae, 'zero_mae': zero, 'mae_improvement': 1-mae/zero if zero else None,
            'by_year': by_year, 'block_interval': interval, 'quality': quality, 'portfolio': portfolio,
            'signal_diagnostics': signal_diagnostics(matured), 'calibration_comparison': alternative}
