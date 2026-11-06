# BẢN ĐỌC THUYẾT TRÌNH — nguồn vận hành: src/gold_collectors/modeling/targets.py
# Chỉ thêm comment tiếng Việt; không import hoặc chạy bản sao này.
# Tạo lại: python scripts/reporting/prepare_presentation_sources.py

"""Tạo nhãn lợi suất theo tháng lịch và phiên SJC hợp lệ đầu tiên sau ngày đích."""

from __future__ import annotations

import numpy as np
import pandas as pd



# Nhãn là lợi suất mua vàng ở giá bán hôm nay và thoát ở giá mua phiên sau ngày tròn tháng.
def _add_calendar_month_targets(frame: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    """Tạo nhãn 1/3/5 tháng lịch theo báo giá đầu tiên từ ngày đáo hạn trở đi."""
    # Giá mua là giá cửa hàng trả cho người bán vàng; giá bán là số tiền
    # nhà đầu tư trả khi mua. Vì vậy lợi suất phải tính tương lai mua / hiện tại bán.
    frame = frame.sort_values("date").copy()
    dates = pd.DatetimeIndex(pd.to_datetime(frame["date"]))
    buy_values = frame["buy_price"].to_numpy(dtype=float)
    sell_values = frame["sell_price"].to_numpy(dtype=float)
    for months in horizons:
        # DateOffset xử lý đúng ngày cuối tháng và năm nhuận; searchsorted chọn
        # phiên giao dịch đầu tiên không sớm hơn ngày tròn tháng.
        target_dates = dates + pd.DateOffset(months=months)
        exit_positions = dates.searchsorted(target_dates, side="left")
        # Chỉ gán nhãn khi đã có báo giá thoát trong dữ liệu. Các dự báo
        # chưa đủ kỳ hạn giữ NaN, tuyệt đối không xem là lợi suất bằng 0.
        known = exit_positions < len(frame)
        future_buy = np.full(len(frame), np.nan)
        future_sell = np.full(len(frame), np.nan)
        future_min_buy = np.full(len(frame), np.nan)
        exit_dates = np.full(len(frame), np.datetime64("NaT"), dtype="datetime64[ns]")
        future_buy[known] = buy_values[exit_positions[known]]
        future_sell[known] = sell_values[exit_positions[known]]
        exit_dates[known] = dates.to_numpy()[exit_positions[known]]
        for position in np.flatnonzero(known):
            # Mức mua thấp nhất giữa ngày vào và ngày thoát phục vụ đo drawdown.
            future_min_buy[position] = np.min(buy_values[position + 1:exit_positions[position] + 1])
        frame[f"target_date_{months}m"] = target_dates
        frame[f"exit_date_{months}m"] = exit_dates
        frame[f"future_buy_{months}m"] = future_buy
        # Lợi suất ròng đã phản ánh chênh lệch mua–bán: mua 100 triệu,
        # bán lại được 103 triệu thì nhãn là 0,03, tức lãi 3%.
        frame[f"net_return_{months}m"] = future_buy / sell_values - 1
        frame[f"gross_sell_return_{months}m"] = future_sell / sell_values - 1
        frame[f"future_drawdown_{months}m"] = future_min_buy / sell_values - 1
        frame[f"positive_return_{months}m"] = (frame[f"net_return_{months}m"] > 0).astype(float)
        frame.loc[frame[f"net_return_{months}m"].isna(), f"positive_return_{months}m"] = np.nan
    return frame
