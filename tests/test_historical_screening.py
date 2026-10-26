"""Đánh giá lịch sử phải tách hiệu chỉnh khỏi năm đánh giá và không cấp validated."""

from __future__ import annotations

import bootstrap  # noqa: F401
import unittest

import numpy as np
import pandas as pd

from scripts.analysis import snapshot_historical as historical


class ConstantModel:
    """Baseline thật để kiểm tra chia thời gian mà không chạy rừng cây trong unit test."""
    def fit(self, x, y):
        self.value = float(np.mean(y))
        return self

    def predict(self, x):
        return np.full(len(x), self.value)


class QuantileModel(ConstantModel):
    """Phân vị chỉ học nhãn train được truyền vào, không nhìn dữ liệu đánh giá."""
    def fit(self, x, y):
        self.value = float(np.quantile(y, 0.1))
        return self


class HistoricalScreeningTests(unittest.TestCase):
    def test_training_calibration_and_evaluation_are_chronological(self):
        """Sửa nhãn năm đánh giá không làm đổi dự báo/xác suất của chính năm đó."""
        dates = pd.date_range('2018-01-01', '2026-10-24')
        frame = pd.DataFrame({'date': dates, 'x': np.arange(len(dates), dtype=float)})
        frame['exit_date_3m'] = dates + pd.DateOffset(months=3)
        frame['net_return_3m'] = np.sin(np.arange(len(dates))/100) * 0.08
        _, predictions = historical.run_historical_horizon(frame, ['x'], 3, point_factory=ConstantModel, quantile_factory=QuantileModel)
        self.assertGreater(len(predictions), 120)
        self.assertTrue((predictions['train_last_exit_date'] < predictions['fold_start']).all())
        self.assertTrue((predictions['calibration_last_exit_date'] < predictions['fold_start']).all())
        self.assertTrue((predictions['date'] >= predictions['fold_start']).all())
        self.assertTrue((predictions['exit_date'] <= pd.Timestamp('2026-10-24')).all())
        altered = frame.copy()
        altered.loc[altered.date.ge('2026-01-01'), 'net_return_3m'] = -0.9
        _, again = historical.run_historical_horizon(altered, ['x'], 3, point_factory=ConstantModel, quantile_factory=QuantileModel)
        fields = ['predicted_net_return', 'q10_predicted_net_return', 'prob_return_positive', 'baseline_probability', 'baseline_q10']
        pd.testing.assert_frame_equal(predictions.loc[predictions.date.ge('2026-01-01'), fields],
                                      again.loc[again.date.ge('2026-01-01'), fields])

    def test_historical_success_is_not_prospective_validated(self):
        """Đạt chỉ số lịch sử vẫn phải ghi rõ là nghiên cứu, không phải validated."""
        rows = []
        for index in range(120):
            origin = pd.Timestamp('2023-01-01') + pd.Timedelta(days=index*7)
            actual = 0.05 if index % 2 == 0 else -0.05
            for horizon in (1, 3, 5):
                rows.append({'snapshot_date': origin.date().isoformat(), 'date': origin,
                             'exit_date': origin + pd.DateOffset(months=horizon), 'horizon_months': horizon,
                             'actual': actual, 'predicted_net_return': actual, 'q10_predicted_net_return': actual-0.005,
                             'prob_return_positive': 0.95 if actual > 0 else 0.05,
                             'baseline_probability': 0.5, 'baseline_q10': -0.1})
        report = historical.build_historical_report(pd.DataFrame(rows), snapshot_date='2026-10-24', protocol_id='test-protocol')
        self.assertFalse(report['independent_validation'])
        self.assertTrue(all(item['status'] == 'historical_passed' for item in report['horizons']))
        empty = historical.build_historical_report(pd.DataFrame(), snapshot_date='2026-10-24', protocol_id='test-protocol')
        self.assertTrue(all(item['status'] == 'historical_insufficient' for item in empty['horizons']))


if __name__ == '__main__':
    unittest.main()
