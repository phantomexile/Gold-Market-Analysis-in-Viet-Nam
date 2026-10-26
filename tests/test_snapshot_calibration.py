"""Bảo vệ xác suất lãi khỏi sai số trong mẫu và nhãn tương lai."""

from __future__ import annotations

import bootstrap  # noqa: F401

import unittest

import numpy as np
import pandas as pd

from scripts.analysis import train_latest_snapshot as snapshot


class SnapshotCalibrationTests(unittest.TestCase):
    """Dữ liệu nhỏ có kết quả tính tay giúp phát hiện xác suất giả hoặc rò rỉ nhãn."""

    def test_empirical_probability_counts_out_of_sample_residuals(self):
        """Hai trong bốn sai số cho lãi; làm trơn (2 + 1)/(4 + 2) bằng 0,5."""
        self.assertAlmostEqual(snapshot.empirical_profit_probability(0.01, [-0.04, -0.02, 0, 0.02], min_rows=4), 0.5)
        self.assertAlmostEqual(snapshot.empirical_profit_probability(0.1, [0.0] * 60), 61 / 62)
        self.assertAlmostEqual(snapshot.empirical_profit_probability(-0.1, [0.0] * 60), 1 / 62)

    def test_missing_or_nonfinite_calibration_has_no_probability(self):
        """Không được thay thiếu mẫu bằng độ lệch chuẩn mặc định hoặc xác suất cực đoan."""
        self.assertIsNone(snapshot.empirical_profit_probability(0.1, []))
        self.assertIsNone(snapshot.empirical_profit_probability(0.1, [float('nan')] * 60))
        self.assertIsNone(snapshot.empirical_profit_probability(float('inf'), [0.01] * 60))

    def test_temporal_calibration_purges_unmatured_labels(self):
        """Mỗi fold chỉ học nhãn đã có kết quả trước đầu năm; loại nhãn tương lai."""
        dates = pd.date_range('2022-01-01', '2026-10-24', freq='D')
        frame = pd.DataFrame({'date': dates, 'x': np.arange(len(dates), dtype=float)})
        frame['exit_date_3m'] = dates + pd.DateOffset(months=3)
        frame['net_return_3m'] = np.sin(np.arange(len(dates)) / 100) * 0.05
        # Thử cả dòng có nhãn điền sẵn dù tương lai chưa xảy ra.
        result = snapshot.temporal_calibration(frame, ['x'], 3, model_factory=MeanRegressor)
        self.assertGreater(len(result), 60)
        self.assertTrue((result['train_last_exit_date'] < result['fold_start']).all())
        self.assertTrue((result['date'] >= result['fold_start']).all())
        self.assertTrue((result['exit_date'] <= pd.Timestamp('2026-10-24')).all())
        self.assertTrue(np.allclose(result['residual'], result['actual'] - result['predicted']))
        # Sửa nhãn chưa biết ở snapshot không được tác động tới bất kỳ dự báo ngoài mẫu nào.
        altered = frame.copy()
        altered.loc[altered['exit_date_3m'] > altered['date'].max(), 'net_return_3m'] = 999
        again = snapshot.temporal_calibration(altered, ['x'], 3, model_factory=MeanRegressor)
        pd.testing.assert_frame_equal(result, again)


class MeanRegressor:
    """Bộ dự báo trung bình thật, dùng để kiểm tra chia thời gian mà không cần thư viện ML."""

    def fit(self, x, y):
        """Chỉ học nhãn từ tập train được truyền vào, như một baseline đơn giản."""
        self.mean = float(np.mean(y))
        return self

    def predict(self, x):
        """Trả cùng dự báo cho tập ngoài mẫu để đối chiếu công thức sai số."""
        return np.full(len(x), self.mean)


if __name__ == '__main__':
    unittest.main()
