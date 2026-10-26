"""Kiểm định tự động phải cấp trạng thái theo bằng chứng mới, không theo nhãn tự đặt."""

from __future__ import annotations

import bootstrap  # noqa: F401

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from scripts.analysis import snapshot_validation as validation


class AutomaticValidationTests(unittest.TestCase):
    """Đối chiếu các trường hợp đạt, chưa đủ và thất bại bằng dữ liệu có kết quả tính tay."""

    def matured_rows(self, count=120):
        """120 dự báo trải 476 ngày, xen kẽ lãi/lỗ 5%, dự báo điểm chính xác."""
        rows = []
        for index in range(count):
            origin = pd.Timestamp('2027-01-01') + pd.Timedelta(days=index * 4)
            actual = 0.05 if index % 2 == 0 else -0.05
            rows.append({
                'snapshot_date': origin.date().isoformat(), 'horizon_months': 1,
                'exit_date': (origin + pd.DateOffset(months=1)).date().isoformat(),
                'actual': actual, 'predicted_net_return': actual,
                'q10_predicted_net_return': actual - 0.005,
                'prob_return_positive': 0.95 if actual > 0 else 0.05,
                'baseline_probability': 0.5, 'baseline_q10': -0.1,
            })
        return rows

    def test_good_independent_evidence_automatically_validates(self):
        """Đạt mọi tiêu chí thì tự cấp validated, không cần sửa trạng thái bằng tay."""
        result = validation.evaluate_horizon(self.matured_rows(), 1, validation.load_policy())
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(all(result['checks'].values()))
        self.assertAlmostEqual(result['metrics']['mae'], 0.0)
        self.assertAlmostEqual(result['metrics']['brier'], 0.0025)
        self.assertGreaterEqual(result['metrics']['nonoverlapping_windows'], 6)

    def test_insufficient_or_overlapping_evidence_stays_pending(self):
        """Nhiều dòng dự báo cùng giai đoạn không thay thế được các chu kỳ độc lập."""
        for case in ('few_rows', 'short_period', 'overlap'):
            with self.subTest(case=case):
                rows = self.matured_rows(119 if case == 'few_rows' else 120)
                if case == 'short_period':
                    for index, row in enumerate(rows):
                        row['snapshot_date'] = (pd.Timestamp('2027-01-01') + pd.Timedelta(days=index)).date().isoformat()
                elif case == 'overlap':
                    for row in rows:
                        row['exit_date'] = '2030-01-01'
                result = validation.evaluate_horizon(rows, 1, validation.load_policy())
                self.assertEqual(result['status'], 'validation_pending')

    def test_each_quality_gate_can_reject_a_model(self):
        """Sai số, xác suất, phân vị và hiệu chỉnh đều có quyền từ chối riêng."""
        for field, value in (
            ('predicted_net_return', 0.5), ('prob_return_positive', 0.5),
            ('q10_predicted_net_return', 0.1), ('q10_predicted_net_return', -0.5),
            ('prob_return_positive', 0.7), ('predicted_net_return', float('nan')),
        ):
            with self.subTest(field=field, value=value):
                rows = self.matured_rows()
                for row in rows:
                    row[field] = value
                result = validation.evaluate_horizon(rows, 1, validation.load_policy())
                self.assertEqual(result['status'], 'validation_failed')
                self.assertTrue(result['reasons'])

    def test_unsafe_input_cannot_validate_even_with_good_metrics(self):
        """Không bỏ qua nguồn tin hồi cứu chỉ vì kết quả dự báo đẹp."""
        result = validation.evaluate_horizon(
            self.matured_rows(), 1, validation.load_policy(),
            blockers=['Tin hồi cứu chưa xác minh thời điểm khả dụng.'],
        )
        self.assertEqual(result['status'], 'validation_failed')

    def forecast(self, day='2026-10-25'):
        """Một dự báo hoàn chỉnh, có baseline đóng băng từ tập train tại ngày phát."""
        return {
            'snapshot_date': day, 'horizon_months': 1,
            'predicted_net_return': 0.03, 'q10_predicted_net_return': -0.04,
            'prob_return_positive': 0.75, 'baseline_probability': 0.5,
            'baseline_q10': -0.06, 'entry_sell_price': 100,
            'probability_method': 'temporal_oos_empirical_laplace', 'calibration_rows': 120,
        }

    def test_protocol_change_resets_evidence_and_cannot_backdate_start(self):
        """Sửa thuật toán phải mở đợt mới; sửa ngày khóa về quá khứ phải bị phát hiện."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            now = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)
            first = validation.ensure_protocol(root, 'source-v1', now=now)
            same = validation.ensure_protocol(root, 'source-v1', now=now)
            changed = validation.ensure_protocol(root, 'source-v2', now=now)
            self.assertEqual(first['protocol_id'], same['protocol_id'])
            self.assertNotEqual(first['protocol_id'], changed['protocol_id'])
            self.assertEqual(first['validation_start'], '2026-10-25')
            changed_policy = {**validation.load_policy(), 'max_q10_breach_rate': 0.2}
            policy_protocol = validation.ensure_protocol(root, 'source-v1', now=now, policy=changed_policy)
            self.assertNotEqual(first['protocol_id'], policy_protocol['protocol_id'])
            import json
            path = root / first['protocol_id'] / 'protocol.json'
            contents = json.loads(path.read_text(encoding='utf-8'))
            contents['validation_start'] = '2020-01-01'
            path.write_text(json.dumps(contents), encoding='utf-8')
            with self.assertRaises(ValueError):
                validation.ensure_protocol(root, 'source-v1', now=now)

    def test_fingerprint_covers_input_processing_and_configuration(self):
        """Đổi collector, chuẩn hóa, entrypoint hoặc cấu hình phải làm mất hiệu lực thành tích cũ."""
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            fixed = ['scripts/analysis/train_latest_snapshot.py', 'scripts/analysis/snapshot_calibration.py', 'scripts/analysis/snapshot_historical.py',
                     'scripts/analysis/snapshot_validation.py', 'scripts/pipeline/refresh_latest_forecast.py',
                     'scripts/pipeline/update_incremental.py']
            changing = ['scripts/processing/improve_premium_coverage.py',
                        'scripts/collection/refresh_event_inputs.py', 'src/gold_collectors/modeling/__init__.py',
                        'configs/forecast_validation_policy.json']
            for name in fixed + changing:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# Ban đầu\n', encoding='utf-8')
            with patch.object(validation, 'ROOT', root):
                previous = validation.model_source_fingerprint()
                for name in changing:
                    (root / name).write_text('# Quy tắc đã thay đổi\n', encoding='utf-8')
                    current = validation.model_source_fingerprint()
                    self.assertNotEqual(current, previous, name)
                    previous = current

    def test_forecasts_are_prospective_and_first_version_is_immutable(self):
        """Không nhập dự báo cũ và không thay dự báo sau khi đã thấy kết quả."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            protocol = validation.ensure_protocol(root, 'source-v1', now=datetime(2026, 10, 24, 12, tzinfo=timezone.utc))
            before = self.forecast('2026-10-24')
            validation.record_forecasts(root, protocol, [before], now=datetime(2026, 10, 24, 13, tzinfo=timezone.utc))
            self.assertEqual(validation.read_journal(root, protocol), [])
            forecast = self.forecast()
            validation.record_forecasts(root, protocol, [forecast], now=datetime(2026, 10, 25, 12, tzinfo=timezone.utc))
            forecast['predicted_net_return'] = 0.99
            validation.record_forecasts(root, protocol, [forecast], now=datetime(2026, 10, 25, 13, tzinfo=timezone.utc))
            # Dự báo phát muộn một ngày không được nhập lại vào tập đánh giá độc lập.
            validation.record_forecasts(root, protocol, [self.forecast('2026-10-26')], now=datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
            records = validation.read_journal(root, protocol)
            self.assertEqual(len(records), 1)
            self.assertAlmostEqual(records[0]['predicted_net_return'], 0.03)
            # Mất một dự báo cũng phải phát hiện, không chỉ phát hiện sửa nội dung.
            saved = next((root / protocol['protocol_id'] / 'forecasts').glob('*.json'))
            saved.unlink()
            with self.assertRaises(ValueError):
                validation.read_journal(root, protocol)

    def test_realized_return_uses_frozen_entry_and_first_valid_exit(self):
        """Giá mua lại đầu tiên sau tròn tháng phải chia giá bán đã lưu khi vào lệnh."""
        record = {**self.forecast('2026-01-31'), 'recorded_at': '2026-01-31T10:00:00+00:00'}
        prices = pd.DataFrame({
            'date': ['2026-01-31', '2026-03-01', '2026-03-02'],
            'buy_price': [98, 110, 120], 'sell_price': [101, 112, 122],
        })
        rows = validation.matured_forecasts([record], prices, as_of='2026-03-01')
        self.assertEqual(rows[0]['exit_date'], '2026-03-01')
        self.assertAlmostEqual(rows[0]['actual'], 0.10)
        self.assertEqual(validation.matured_forecasts([record], prices, as_of='2026-02-28'), [])

    def test_fallback_events_or_unknown_event_sources_block_validation(self):
        """Kiểm tra đúng nguồn builder đang đọc, kể cả khi mất tệp event ưu tiên."""
        for missing_source in (False, True):
            with self.subTest(missing_source=missing_source), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
                lake = Path(folder)
                events = lake / 'normalized' / 'event_regime_panel.csv'
                events.parent.mkdir(parents=True)
                events.write_text('event_date\n2026-01-01\n' if missing_source else
                                  'event_date,source\n2026-01-01,google_news_rss_event_proxy\n', encoding='utf-8')
                frame = pd.DataFrame({'date': ['2026-01-01']})
                self.assertTrue(validation.input_availability_blockers(frame, ['event_count'], lake))

    def test_validation_report_controls_status_and_buy_per_horizon(self):
        """Bỏ cờ mua viết cứng; chỉ kỳ hạn đạt báo cáo mới được bật tín hiệu."""
        forecasts = [{**self.forecast(), 'horizon_months': horizon} for horizon in (1, 3, 5)]
        report = {
            'snapshot_date': '2026-10-25', 'protocol_id': 'locked-test-protocol',
            'horizons': [validation.evaluate_horizon(self.matured_rows(), 1, validation.load_policy()),
                         validation.evaluate_horizon([], 3, validation.load_policy()),
                         validation.evaluate_horizon([], 5, validation.load_policy(), blockers=['Nguồn chưa xác minh.'])],
        }
        validation.apply_validation_results(forecasts, report)
        self.assertEqual([row['status'] for row in forecasts], ['validated', 'validation_pending', 'validation_failed'])
        self.assertEqual([row['buy_signal'] for row in forecasts], [True, False, False])
        # Báo cáo khác ngày không được cấp trạng thái cho snapshot mới.
        report['snapshot_date'] = '2026-10-24'
        validation.apply_validation_results(forecasts, report)
        self.assertTrue(all(row['status'] == 'validation_failed' and not row['buy_signal'] for row in forecasts))
        report['snapshot_date'] = '2026-10-25'
        for bad_checks in ({'enough_rows': True}, {'enough_rows': 'true'}, None):
            with self.subTest(checks=bad_checks):
                report['horizons'][0]['checks'] = bad_checks
                validation.apply_validation_results(forecasts, report)
                self.assertEqual(forecasts[0]['status'], 'validation_failed')
                self.assertFalse(forecasts[0]['buy_signal'])

    def test_full_step_can_validate_then_revoke_and_reset(self):
        """Chạy thật nhật ký → giá đáo hạn → báo cáo → trạng thái, cả nhánh đạt và thu hồi."""
        import numpy as np
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            modeling = Path(folder)
            root = modeling / 'validation'
            protocol = validation.ensure_protocol(root, 'fixed-v1', now=datetime(2017, 12, 31, 12, tzinfo=timezone.utc))
            dates = pd.date_range('2018-01-01', '2020-01-01', freq='D')
            buy = 100 + 10 * np.sin(np.arange(len(dates)) / 20)
            prices = pd.DataFrame({'date': dates, 'buy_price': buy, 'sell_price': buy + 1})
            curve = prices.set_index('date')
            # Giá và dự báo đều là fixture kiểm thử; bản phát được ghi ở đúng ngày origin.
            for index in range(120):
                origin = pd.Timestamp('2018-01-01') + pd.Timedelta(days=index * 4)
                target = origin + pd.DateOffset(months=1)
                entry = float(curve.loc[origin, 'sell_price'])
                actual = float(curve.loc[target, 'buy_price']) / entry - 1
                forecast = {**self.forecast(origin.date().isoformat()),
                            'entry_sell_price': entry, 'predicted_net_return': actual,
                            'q10_predicted_net_return': actual - 0.005,
                            'prob_return_positive': 0.95 if actual > 0 else 0.05,
                            'baseline_q10': -0.2}
                recorded = origin.to_pydatetime().replace(hour=12, tzinfo=timezone.utc)
                validation.record_forecasts(root, protocol, [forecast], now=recorded)
            forecasts = [{**self.forecast('2020-01-01'), 'horizon_months': h} for h in (1, 3, 5)]
            now = datetime(2020, 1, 1, 12, tzinfo=timezone.utc)
            report = validation.run_validation(modeling, forecasts, prices, source_id='fixed-v1', blockers=[], now=now)
            validation.apply_validation_results(forecasts, report)
            self.assertEqual(forecasts[0]['status'], 'validated')
            self.assertTrue(forecasts[0]['buy_signal'])
            # Đầu vào mới không đạt thì trạng thái cũ bị thu hồi ngay, không lưu validated vĩnh viễn.
            report = validation.run_validation(modeling, forecasts, prices, source_id='fixed-v1', blockers=['Nguồn mới chưa xác minh.'], now=now)
            validation.apply_validation_results(forecasts, report)
            self.assertEqual(forecasts[0]['status'], 'validation_failed')
            self.assertFalse(forecasts[0]['buy_signal'])
            report = validation.run_validation(modeling, forecasts, prices, source_id='changed-v2', blockers=[], now=now)
            validation.apply_validation_results(forecasts, report)
            self.assertEqual(forecasts[0]['status'], 'validation_pending')
            self.assertFalse(forecasts[0]['buy_signal'])


if __name__ == '__main__':
    unittest.main()
