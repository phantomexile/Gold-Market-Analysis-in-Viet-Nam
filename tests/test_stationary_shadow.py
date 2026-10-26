"""Bản khóa và dự báo thử nghiệm mới phải bất biến và không hợp thức hóa lịch sử."""

import bootstrap  # noqa: F401
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch
from scripts.analysis import stationary_shadow as shadow

from scripts.analysis.stationary_shadow import create_lock, read_lock, append_forecast, read_records


class ShadowTests(unittest.TestCase):
    def test_refresh_runs_shadow_hook_only_when_lock_exists(self):
        """Nút cập nhật dùng cùng collector record-only; chưa khóa thì không gọi."""
        from scripts.pipeline import refresh_latest_forecast as pipeline
        for active in (False, True):
            with self.subTest(active=active), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                lake = root/'data/lake'
                (lake/'modeling').mkdir(parents=True)
                (root/'web/data').mkdir(parents=True)
                (lake/'global_reference_daily.csv').write_text('date,value\n2026-10-24,1\n', encoding='utf-8')
                (lake/'modeling/model_frame_daily.csv').write_text('date\n2026-10-24\n', encoding='utf-8')
                (lake/'modeling/snapshot_forecasts.csv').write_text(
                    'snapshot_date,horizon_months\n2026-10-24,1\n2026-10-24,3\n2026-10-24,5\n', encoding='utf-8')
                (root/'web/data/gold_dashboard_data.json').write_text(json.dumps({'summary': {'end_date': '2026-10-24'}}), encoding='utf-8')
                if active:
                    (lake/'modeling/stationary_shadow').mkdir()
                    (lake/'modeling/stationary_shadow/active.json').write_text('{}', encoding='utf-8')
                with patch.object(pipeline, 'ROOT', root), patch.object(pipeline, 'LAKE', lake), \
                        patch.object(pipeline, 'run_step') as run, patch.object(pipeline, 'report_progress'):
                    self.assertEqual(pipeline.refresh(skip_collect=True), '2026-10-24')
                    hooks = [call for call in run.call_args_list if call.args[0].name == 'run_stationary_research.py']
                    self.assertEqual(len(hooks), int(active))
                    if hooks:
                        self.assertEqual(hooks[0].args[1:], ('--record-only',))

    def test_fingerprint_covers_shared_upstream_pipeline(self):
        """Maturity/scoring/features dùng chung thay đổi phải tạo campaign khác."""
        with patch.object(shadow, 'model_source_fingerprint', return_value='upstream-v1', create=True):
            first = shadow.algorithm_fingerprint()
        with patch.object(shadow, 'model_source_fingerprint', return_value='upstream-v2', create=True):
            second = shadow.algorithm_fingerprint()
        self.assertNotEqual(first, second)

    def test_invalid_probability_does_not_leave_partial_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            initial = root/'initial.csv'
            initial.write_text('date,predicted\n', encoding='utf-8')
            now = datetime(2026, 10, 25, 4, tzinfo=timezone.utc)
            lock = create_lock(root/'shadow', initial, candidate='ridge', margin=.01, now=now, source_id='test')
            row = dict(snapshot_date='2026-10-26', horizon_months=3, predicted_net_return=.1,
                       q10_predicted_net_return=-.1, prob_return_positive=float('nan'),
                       baseline_probability=.5, baseline_q10=-.1, entry_sell_price=102.)
            with self.assertRaises(ValueError):
                append_forecast(root/'shadow', lock, row, now=now+timedelta(days=1))
            self.assertEqual(list((root/'shadow'/lock['protocol_id']/'forecasts').glob('*.json')), [])
            row['prob_return_positive'] = 1.5
            with self.assertRaises(ValueError):
                append_forecast(root/'shadow', lock, row, now=now+timedelta(days=1))

    def test_lock_and_journal_first_forecast_is_immutable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            calibration = root / 'initial.csv'
            calibration.write_text('date,predicted\n2026-10-24,0.1\n', encoding='utf-8')
            now = datetime(2026, 10, 25, 4, tzinfo=timezone.utc)
            lock = create_lock(root/'shadow', calibration, candidate='ridge', margin=.01, now=now, source_id='code1')
            self.assertEqual(lock['validation_start'], '2026-10-26')
            self.assertEqual(read_lock(root/'shadow', source_id='code1')['candidate'], 'ridge')
            row = dict(snapshot_date='2026-10-25', horizon_months=3, predicted_net_return=.1,
                       q10_predicted_net_return=-.05, prob_return_positive=.7,
                       baseline_probability=.5, baseline_q10=-.1, entry_sell_price=102.)
            append_forecast(root/'shadow', lock, row, now=now)
            self.assertEqual(read_records(root/'shadow', lock), [])
            tomorrow = now + timedelta(days=1)
            row['snapshot_date'] = '2026-10-26'
            append_forecast(root/'shadow', lock, row, now=tomorrow)
            row['predicted_net_return'] = .9
            append_forecast(root/'shadow', lock, row, now=tomorrow)
            self.assertEqual(read_records(root/'shadow', lock)[0]['predicted_net_return'], .1)
            path = next((root/'shadow'/lock['protocol_id']/'forecasts').glob('*.json'))
            path.unlink()
            with self.assertRaises(ValueError):
                read_records(root/'shadow', lock)

    def test_code_or_initial_calibration_change_invalidates_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = root/'initial.csv'
            data.write_text('date,predicted\n', encoding='utf-8')
            lock = create_lock(root/'shadow', data, candidate='ridge', margin=.01,
                               now=datetime.now(timezone.utc), source_id='code1')
            with self.assertRaises(ValueError):
                read_lock(root/'shadow', source_id='code2')
            stored = root/'shadow'/lock['protocol_id']/'calibration.csv'
            stored.write_text('changed', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_lock(root/'shadow', source_id='code1')


if __name__ == '__main__':
    unittest.main()
