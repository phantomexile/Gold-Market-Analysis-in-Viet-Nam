"""Tách mô hình phát dự báo thử nghiệm khỏi mốc đối chứng dùng đánh giá."""

from __future__ import annotations

import pandas as pd
from .stationary_research import select_deployable_candidate


def select_research_forecast(predictions: pd.DataFrame, cutoff: pd.Timestamp, *, horizon=3) -> dict:
    """Chọn ML riêng từng kỳ hạn nhưng không tự nhận nó đã thắng baseline.

    Dashboard của dự án dùng chế độ dự báo trực tiếp. Vì vậy, zero là mốc
    so sánh độ chính xác, không phải số thay thế cho dự báo khi ML chưa đạt.
    Việc chọn ML chỉ nhìn nhãn đã đáo hạn trước cutoff; đánh giá vượt mốc
    và kiểm chứng tiến cứu vẫn phải giữ kết quả không đạt nếu có.
    """
    evidence = select_deployable_candidate(predictions,cutoff,horizon=horizon)
    scores = evidence['candidates']
    learning = [name for name in ('rf_small','rf_median') if name in scores]
    if not learning:
        raise ValueError('Chưa có đủ dự báo ML đã đáo hạn để chọn mô hình thử nghiệm.')
    # Nếu đã có ML đạt tiêu chí, ưu tiên nhóm đó. Chỉ khi chưa có ứng viên
    # đủ chuẩn mới chọn ML có MAE thấp nhất để hiển thị thử nghiệm.
    qualified_learning = [name for name in learning if scores[name]['qualified']]
    selected = min(qualified_learning or learning,key=lambda name:(scores[name]['mae'],name))
    qualified = bool(scores[selected]['qualified'])
    return {**evidence,'candidate':selected,'benchmark_winner':evidence['candidate'],
            'improved_over_baseline':qualified,'forecast_role':'research',
            'baseline_candidate':'zero','point_comparison':scores[selected],
            'reason':'Dự báo ML riêng cho kỳ hạn này; baseline lợi suất 0 chỉ dùng làm đối chứng. '
                     + ('Đạt tiêu chí phát triển, vẫn cần kiểm chứng tiến cứu.' if qualified else
                        'Chưa đạt tiêu chí tốt hơn baseline; chưa chứng minh độ tin cậy giao dịch.')}
