"""Bộ đặc trưng gọn mô tả tỷ lệ và biến động, không dùng nhãn hoặc mức giá tuyệt đối."""

from __future__ import annotations

import numpy as np
import pandas as pd


def build_stationary_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Tính 34 biến chỉ từ các phiên đã có đến ngày dự báo.

    Dự báo được phát sau báo giá cuối ngày. Giá nội địa ngày đó đã biết;
    cột quốc tế trong frame đã ghép as-of, tiếp tục trễ một phiên để bảo thủ.
    Không bfill/fit scaler ở đây: điền thiếu và chuẩn hóa phải học trong train.
    """
    dates = pd.to_datetime(frame['date'], errors='coerce')
    if dates.isna().any() or dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError('Frame phải có ngày hợp lệ, duy nhất và tăng dần.')
    def numeric(name):
        return pd.to_numeric(frame.get(name, pd.Series(np.nan, index=frame.index)), errors='coerce').replace([np.inf, -np.inf], np.nan)
    buy, sell = numeric('buy_price'), numeric('sell_price')
    buy = buy.where(buy > 0)
    sell = sell.where((sell > 0) & (sell >= buy))
    returns = np.log(buy / buy.shift(1))
    cols = {'spread_ratio': (sell - buy) / sell}
    for window in (1, 5, 10, 21, 63, 126):
        cols[f'gold_return_{window}'] = buy / buy.shift(window) - 1
    for window in (5, 21, 63):
        cols[f'gold_volatility_{window}'] = returns.rolling(window, min_periods=window).std()
    for window in (21, 63, 126):
        cols[f'gold_relative_ma_{window}'] = buy / buy.rolling(window, min_periods=window).mean() - 1
    for window in (63, 126):
        high = buy.rolling(window, min_periods=window).max()
        low = buy.rolling(window, min_periods=window).min()
        cols[f'gold_drawdown_{window}'] = buy / high - 1
        cols[f'gold_range_{window}'] = high / low - 1
    cols['momentum_difference'] = cols['gold_return_5'] - cols['gold_return_21']
    cols['spread_change_21'] = cols['spread_ratio'] - cols['spread_ratio'].shift(21)
    gold = numeric('gold_futures_close_usd_oz').shift(1)
    fx = numeric('usd_vnd').shift(1)
    for name, values in [('global_gold', gold), ('fx', fx)]:
        values = values.where(values > 0)
        for window in (5, 21, 63):
            cols[f'{name}_return_{window}'] = values / values.shift(window) - 1
    cols['global_gold_relative_ma'] = gold / gold.rolling(63, min_periods=63).mean() - 1
    dxy = numeric('dxy_index').shift(1)
    cols['dxy_return_21'] = dxy / dxy.shift(21) - 1
    treasury = numeric('treasury_10y_pct').shift(1)
    cols['yield_change_21'] = treasury - treasury.shift(21)
    vix = numeric('vix').shift(1)
    cols['vix_relative_ma'] = vix / vix.rolling(63, min_periods=63).mean() - 1
    premium = numeric('premium_pct').shift(1)
    cols['premium_ratio'] = premium
    cols['premium_change_21'] = premium - premium.shift(21)
    cols['premium_deviation_63'] = premium - premium.rolling(63, min_periods=63).mean()
    # Mùa trong năm biết trước; không dùng danh sách sự kiện/tin được gắn nhãn hồi cứu.
    cols['season_sin'] = np.sin(2 * np.pi * dates.dt.dayofyear / 365.25)
    cols['season_cos'] = np.cos(2 * np.pi * dates.dt.dayofyear / 365.25)
    return pd.DataFrame(cols, index=frame.index).replace([np.inf, -np.inf], np.nan)
