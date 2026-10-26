"""Chuyển dự báo lợi suất thành Mua/Bán/Quan sát, tách khỏi trạng thái kiểm định."""

from __future__ import annotations

import math

NEUTRAL_MARGIN = 0.01
PRIMARY_HORIZON_MONTHS = 3


def direct_signal(prediction, buy_price, sell_price, *, margin=NEUTRAL_MARGIN) -> dict:
    """Tính tín hiệu từ góc nhìn người mua mới và người đang giữ vàng.

    prediction là lợi suất ròng mua mới, đơn vị thập phân (0,05 = 5%).
    Giá bán của tiệm là chi phí mua mới, giá mua của tiệm là tiền nhận khi
    bán ngay. Giữ vàng so với bán ngay phải dùng giá mua, tránh coi khoản
    chênh lệch mua/bán của người mua mới là khoản lỗ của người đang giữ.
    margin là vùng trung tính nghiệp vụ, không phải ngưỡng đã tối ưu/thẩm định.
    """
    empty = {'signal': 'observe', 'action': 'Quan sát', 'badge_type': 'warning',
             'predicted_hold_return': None, 'reason': 'Chưa đủ dự báo và giá mua/bán hợp lệ.'}
    try:
        values = (prediction, buy_price, sell_price, margin)
        if any(isinstance(value, bool) for value in values):
            return empty
        pred, buy, sell, band = map(float, values)
    except (ValueError, TypeError, OverflowError):
        return empty
    if not all(math.isfinite(v) for v in (pred, buy, sell, band)) or buy <= 0 or sell < buy or pred <= -1 or band < 0:
        return empty
    hold = (1 + pred) * sell / buy - 1
    if not math.isfinite(hold):
        return empty
    # Sai số số thực sát biên không được biến đúng 1% thành mua/bán ngoài ý muốn.
    above = pred > band and not math.isclose(pred, band, abs_tol=1e-12, rel_tol=0)
    below = hold < -band and not math.isclose(hold, -band, abs_tol=1e-12, rel_tol=0)
    if above:
        signal, action, theme = 'buy', 'Mua', 'positive'
        reason = f'Lợi suất mua mới dự báo {pred*100:+.2f}%, đã tính chênh lệch mua–bán và vượt ngưỡng {band*100:g}%.'
    elif below:
        signal, action, theme = 'sell', 'Bán', 'negative'
        reason = f'Nếu đang giữ vàng, giá bán lại dự báo thấp hơn bán ngay {abs(hold)*100:.2f}%.'
    else:
        signal, action, theme = 'observe', 'Quan sát', 'warning'
        reason = f'Dự báo chưa đủ chênh lệch để mua mới hoặc bán vàng đang giữ theo vùng trung tính {band*100:g}%.'
    return {'signal': signal, 'action': action, 'badge_type': theme,
            'predicted_hold_return': hold, 'reason': reason}
