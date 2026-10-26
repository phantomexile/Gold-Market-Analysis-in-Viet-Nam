"""Sàng lọc lịch sử với train/hiệu chỉnh/đánh giá tách theo thời gian, không cấp validated."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from .snapshot_calibration import empirical_profit_probability, make_point_model, make_q10_model, temporal_calibration
from .snapshot_validation import evaluate_horizon, load_policy


def run_historical_horizon(
    frame: pd.DataFrame, candidates: list[str], horizon: int,
    *, evaluation_start: int = 2023,
    point_factory: Callable[[], Any] = make_point_model,
    quantile_factory: Callable[[], Any] = make_q10_model,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dự báo từng năm, chỉ hiệu chỉnh bằng residuals đã biết trước đầu năm đánh giá.

    Các năm trước evaluation_start phục vụ hiệu chỉnh, không được đưa vào
    điểm chất lượng. Trong từng năm đánh giá, cả point/Q10/feature selection
    đóng băng trước đầu năm. Không dùng sai số ngay trong năm đó để tính P(lãi).
    """
    all_predictions = temporal_calibration(
        frame, candidates, horizon, model_factory=point_factory,
        start_year=evaluation_start - 2, quantile_start_year=evaluation_start,
        quantile_factory=quantile_factory,
    )
    records = []
    for year in range(evaluation_start, pd.Timestamp(frame['date'].max()).year + 1):
        start = pd.Timestamp(year, 1, 1)
        # Hai năm trước cùng năm hiện tại là cửa sổ ba năm của snapshot.
        # Ở đầu năm chưa có nhãn năm hiện tại đáo hạn, nên chỉ dùng các năm trước.
        calibration = all_predictions.loc[
            (all_predictions['date'] >= pd.Timestamp(year - 2, 1, 1))
            & (all_predictions['date'] < start) & (all_predictions['exit_date'] < start)
        ]
        evaluation = all_predictions.loc[all_predictions['fold_start'].eq(start)]
        for row in evaluation.to_dict('records'):
            probability = empirical_profit_probability(row['predicted'], calibration['residual'])
            if probability is None or not np.isfinite(row['q10_predicted_net_return']):
                # Thiếu hiệu chỉnh phải được phản ánh bằng số mẫu chưa đủ, không thay bằng 50%.
                continue
            records.append({
                **row, 'snapshot_date': row['date'].date().isoformat(),
                'predicted_net_return': row['predicted'], 'prob_return_positive': probability,
                'calibration_rows': len(calibration),
                'calibration_last_exit_date': calibration['exit_date'].max(),
            })
    return all_predictions, pd.DataFrame(records)


def build_historical_report(
    predictions: pd.DataFrame, *, snapshot_date: str, protocol_id: str,
    blockers: list[str] | None = None,
) -> dict:
    """Gắn nhãn kết quả lịch sử riêng, không cho báo cáo này thay thế kiểm chứng tiến cứu."""
    policy = load_policy()
    records = predictions.to_dict('records') if not predictions.empty else []
    horizons = []
    for horizon in (1, 3, 5):
        result = evaluate_horizon(records, horizon, policy, blockers=blockers)
        result['status'] = {
            'validated': 'historical_passed', 'validation_failed': 'historical_failed',
            'validation_pending': 'historical_insufficient',
        }[result['status']]
        subset = predictions.loc[predictions['horizon_months'].eq(horizon)] if not predictions.empty else pd.DataFrame()
        result['evaluation_start'] = str(subset['date'].min().date()) if not subset.empty else ''
        result['evaluation_end'] = str(subset['date'].max().date()) if not subset.empty else ''
        horizons.append(result)
    return {
        'snapshot_date': snapshot_date, 'protocol_id': protocol_id,
        'evaluation_kind': 'historical_screening', 'independent_validation': False,
        'notice': 'Dữ liệu lịch sử đã được xem khi phát triển mô hình. Kết quả chỉ phục vụ nghiên cứu, không cấp validated hay khuyến nghị mua thực tế.',
        'policy': policy, 'horizons': horizons,
    }
