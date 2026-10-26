"""Tin và sự kiện chưa xác minh không được ảnh hưởng đặc trưng hoặc kiểm định."""

from __future__ import annotations

import bootstrap  # noqa: F401
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from gold_collectors.modeling import ModelingConfig, build_model_frame
from gold_collectors.modeling.features import _maybe_merge_news
from scripts.analysis.snapshot_validation import input_availability_blockers


class ModelInputPolicyTests(unittest.TestCase):
    def test_unsafe_events_and_their_derived_features_are_excluded(self):
        """Đổi tin/proxy chưa xác minh không được làm thay đổi ma trận mô hình."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            lake = Path(folder)
            dates = pd.date_range('2022-01-01', '2024-02-20')
            pd.DataFrame({'date': dates, 'buy': 99.0, 'sell': 100.0}).to_csv(lake/'gold_quotes_sjc_historical.csv', index=False)
            events = pd.DataFrame([
                {'event_date': '2024-02-10', 'event_type': 'tet_proximity', 'source': 'rule_generated', 'severity': 'low', 'expected_channel': 'premium_spike'},
                {'event_date': '2024-01-10', 'event_type': 'sbv_policy', 'source': 'google_news_rss_event_proxy', 'severity': 'high', 'expected_channel': 'unsafe_channel'},
                {'event_date': '2024-01-11', 'event_type': 'policy_import', 'source': 'rule_generated', 'severity': 'high', 'expected_channel': 'unsafe_channel'},
            ])
            events.to_csv(lake/'pipeline_output_event_regime.csv', index=False)
            pd.DataFrame([{'event_date': '2023-01-01', 'headline': 'Tăng giá', 'feature_mode_strict': 'backfilled_not_realtime'}]).to_csv(lake/'news_raw_headlines_vietnam_gold.csv', index=False)
            config = ModelingConfig(data_lake=lake)
            first = build_model_frame(config)
            columns = first.attrs['feature_columns']
            self.assertNotIn('channel_unsafe_channel', columns)
            self.assertFalse(any(name.startswith('raw_news_') for name in columns))
            self.assertIn('days_until_next_tet', columns)
            self.assertEqual(input_availability_blockers(first, columns, lake), [])
            self.assertEqual(first.loc[first.date.eq('2024-01-10'), 'event_count'].iloc[0], 0)
            self.assertEqual(first.loc[first.date.eq('2024-02-10'), 'event_count'].iloc[0], 1)
            events.loc[1:, 'event_date'] = '2023-01-01'
            events.loc[1:, 'severity'] = 'extreme'
            events.to_csv(lake/'pipeline_output_event_regime.csv', index=False)
            second = build_model_frame(config)
            pd.testing.assert_frame_equal(first[columns], second[columns])
            self.assertEqual(first.attrs['diagnostics']['events_excluded_rows'], 2)

    def test_verified_news_uses_availability_not_publication_date(self):
        """Tin đăng ngày 1 nhưng thu thập ngày 11 chỉ được vào đặc trưng từ ngày 13."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            lake = Path(folder)
            news = pd.DataFrame([
                {'event_date': '2024-01-01', 'headline': 'Giá vàng tăng', 'feature_mode_strict': 'strict_realtime_verified',
                 'availability_from': '2024-01-12', 'published_at': '2024-01-01', 'fetched_at': '2024-01-11'},
                {'event_date': '2024-01-01', 'headline': 'Chính sách giảm giá', 'feature_mode_strict': 'backfilled_not_realtime',
                 'availability_from': '2024-01-12', 'published_at': '2024-01-01', 'fetched_at': '2024-01-11'},
                {'event_date': '2024-01-01', 'headline': 'Tin gắn cờ sai', 'feature_mode_strict': 'strict_realtime_verified',
                 'availability_from': '2024-01-02', 'published_at': '2024-01-01', 'fetched_at': '2024-01-11'},
            ])
            news.to_csv(lake/'news_raw_headlines_vietnam_gold.csv', index=False)
            frame = pd.DataFrame({'date': pd.date_range('2024-01-01', '2024-01-20')})
            diagnostics = {}
            merged = _maybe_merge_news(frame, ModelingConfig(data_lake=lake), diagnostics)
            self.assertEqual(merged.loc[merged.date.eq('2024-01-10'), 'raw_news_count'].iloc[0], 0)
            self.assertEqual(merged.loc[merged.date.eq('2024-01-12'), 'raw_news_count'].iloc[0], 0)
            self.assertEqual(merged.loc[merged.date.eq('2024-01-13'), 'raw_news_count'].iloc[0], 1)
            self.assertEqual(merged.loc[merged.date.eq('2024-01-20'), 'raw_news_count'].iloc[0], 0)
            self.assertTrue(diagnostics['raw_news_availability_verified'])
            self.assertEqual(diagnostics['news_excluded_rows'], 2)
            # Ngày sự kiện là metadata tùy chọn; nguồn đủ bằng chứng vẫn phải dùng được.
            news.drop(columns=['event_date']).to_csv(lake/'news_raw_headlines_vietnam_gold.csv', index=False)
            without_event_date = _maybe_merge_news(frame, ModelingConfig(data_lake=lake), {})
            pd.testing.assert_frame_equal(merged, without_event_date)


if __name__ == '__main__':
    unittest.main()
