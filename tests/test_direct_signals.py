"""Tín hiệu trực tiếp dựa dự báo; phân biệt mua mới và bán vàng đang giữ."""

import bootstrap  # noqa: F401
import csv
import tempfile
import unittest
from pathlib import Path

from scripts.analysis.forecast_signals import direct_signal
from scripts.build_web_data import build_recommendations


class DirectSignalsTests(unittest.TestCase):
    def test_buy_sell_and_spread_neutral(self):
        self.assertEqual(direct_signal(.05, 100, 102)['signal'], 'buy')
        self.assertEqual(direct_signal(-.06, 100, 102)['signal'], 'sell')
        # Mua mới lỗ vì spread nhưng đang giữ vẫn có lợi khi chờ, nên không ép bán.
        self.assertEqual(direct_signal(-.01, 100, 103)['signal'], 'observe')

    def test_threshold_boundaries_and_invalid_numbers(self):
        self.assertEqual(direct_signal(.01, 100, 100)['signal'], 'observe')
        self.assertEqual(direct_signal(-.01, 100, 100)['signal'], 'observe')
        for pred, buy, sell in [(float('nan'), 100, 102), (.1, 0, 102), (.1, 104, 102),
                                 (None, 100, 102), (-1.1, 100, 102), (.1, 100, float('inf'))]:
            self.assertEqual(direct_signal(pred, buy, sell)['signal'], 'observe')

    def test_direct_signals_ignore_validation_but_reject_stale_data(self):
        with tempfile.TemporaryDirectory() as folder:
            lake = Path(folder)
            modeling = lake / 'modeling'
            modeling.mkdir()
            fields = ['snapshot_date', 'horizon_months', 'predicted_net_return', 'entry_sell_price', 'status']
            with (modeling / 'snapshot_forecasts.csv').open('w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fields)
                writer.writeheader()
                for h, pred in [(1, -.06), (3, .05), (5, .005)]:
                    writer.writerow(dict(snapshot_date='2026-10-24', horizon_months=h,
                                         predicted_net_return=pred, entry_sell_price=102, status='validation_pending'))
            (modeling / 'model_frame_daily.csv').write_text('date,buy_price,sell_price\n2026-10-24,100,102\n', encoding='utf-8')
            result = build_recommendations(lake, expected_snapshot_date='2026-10-24')
            self.assertEqual(result['signal_mode'], 'direct_forecast')
            self.assertEqual([h['signal'] for h in result['horizons']], ['sell', 'buy', 'observe'])
            self.assertEqual(result['primary_signal'], 'buy')
            self.assertEqual(result['primary_horizon_months'], 3)
            self.assertTrue(result['horizons'][1]['buy_signal'])
            self.assertFalse(result['horizons'][1]['validated_buy_signal'])
            self.assertEqual(result['horizons'][1]['status'], 'validation_pending')
            original = (modeling / 'snapshot_forecasts.csv').read_text(encoding='utf-8')
            for entry in ('', '999', 'nan', '-102'):
                (modeling / 'snapshot_forecasts.csv').write_text(
                    original.replace(',102,validation_pending', f',{entry},validation_pending'), encoding='utf-8')
                invalid = build_recommendations(lake, expected_snapshot_date='2026-10-24')
                self.assertTrue(all(h['signal'] == 'observe' for h in invalid['horizons']), entry)
            (modeling / 'snapshot_forecasts.csv').write_text(original, encoding='utf-8')
            stale = build_recommendations(lake, expected_snapshot_date='2026-10-25')
            self.assertTrue(all(h['signal'] == 'observe' for h in stale['horizons']))
            # Không lấy giá từ ngày khác để biến dự báo cũ thành tín hiệu mới.
            (modeling / 'model_frame_daily.csv').write_text('date,buy_price,sell_price\n2026-10-25,100,102\n', encoding='utf-8')
            missing = build_recommendations(lake, expected_snapshot_date='2026-10-24')
            self.assertTrue(all(h['signal'] == 'observe' for h in missing['horizons']))


if __name__ == '__main__':
    unittest.main()
