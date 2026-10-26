"""Bảo vệ đối chứng mô hình khỏi nhãn tương lai và kết quả nghiên cứu bị hiểu sai."""

from __future__ import annotations

import bootstrap  # noqa: F401
import unittest
import tempfile
import json
from pathlib import Path
import numpy as np
import pandas as pd

from scripts.analysis.model_diagnostics import audit_targets, diagnose_history
from scripts.analysis.model_research import Candidate, run_monthly, select_annual, summarize_research
from scripts.analysis.run_model_research import prepare_output, write_json, resolve_features


def sample_frame():
    """Chuỗi giá thật giả lập có tháng nhuận và nhãn tháng lịch để kiểm tra purge."""
    dates = pd.date_range('2018-01-01', '2024-12-31')
    f = pd.DataFrame({'date': dates, 'buy_price': 100 + np.arange(len(dates)) * .02,
                      'sell_price': 102 + np.arange(len(dates)) * .02,
                      'x': np.sin(np.arange(len(dates)) / 30)})
    for h in (1, 3, 5):
        positions = dates.searchsorted(dates + pd.DateOffset(months=h))
        valid = positions < len(dates)
        f[f'exit_date_{h}m'] = pd.NaT
        f.loc[valid, f'exit_date_{h}m'] = dates[positions[valid]].to_numpy()
        f[f'net_return_{h}m'] = np.nan
        f.loc[valid, f'net_return_{h}m'] = f.buy_price.to_numpy()[positions[valid]] / f.sell_price[valid] - 1
    return f


class ResearchTests(unittest.TestCase):
    def test_selection_minimum_rows_months_and_exit_boundary(self):
        """120 dòng chưa đủ nếu chỉ có 5 tháng; nhãn thoát đúng ngày chốt chưa được dùng."""
        def history(months, days, last_exit='2022-12-31'):
            rows = []
            for month in range(1, months + 1):
                for day in range(1, days + 1):
                    for name, prediction in [('zero', 0.), ('better', .1)]:
                        rows.append({'date': pd.Timestamp(2022, month, day),
                                     'exit_date': pd.Timestamp(last_exit), 'horizon_months': 1,
                                     'candidate': name, 'actual': .1, 'predicted': prediction})
            for name in ('zero', 'better'):
                rows.append({'date': pd.Timestamp('2023-01-02'), 'exit_date': pd.Timestamp('2023-02-02'),
                             'horizon_months': 1, 'candidate': name, 'actual': .1, 'predicted': 0.})
            return pd.DataFrame(rows)
        enough = history(6, 20)
        self.assertEqual(select_annual(enough)[0]['candidate'], 'better')
        short = enough.loc[enough.date.ne(pd.Timestamp('2022-01-01'))]
        self.assertEqual(select_annual(short)[0]['candidate'], 'zero')
        self.assertEqual(select_annual(history(5, 24))[0]['candidate'], 'zero')
        self.assertEqual(select_annual(history(6, 20, '2023-01-01'))[0]['candidate'], 'zero')

    def test_feature_schema_uses_current_builder_not_legacy_manifest(self):
        f = sample_frame()
        f['deposit_return_1m'] = .003
        from gold_collectors.modeling.features import _add_lagged_features
        from gold_collectors.modeling import ModelingConfig
        built, expected = _add_lagged_features(f, ModelingConfig())
        got = resolve_features(built)
        self.assertEqual(got, expected)
        self.assertIn('deposit_return_1m_lag_1d', got)
        self.assertNotIn('net_return_1m', got)

    def test_output_is_exclusive_and_json_rejects_nan(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'research'
            prepare_output(root, {'status': 'research_only'})
            with self.assertRaises(FileExistsError):
                prepare_output(root, {})
            with self.assertRaises(ValueError):
                write_json(root / 'invalid.json', {'mae': float('nan')})
            self.assertEqual(json.loads((root / 'manifest.json').read_text(encoding='utf-8'))['status'], 'research_only')

    def test_ridge_features_are_selected_without_test_labels(self):
        f = sample_frame()
        f['z'] = np.cos(np.arange(len(f)) / 11)
        specs = [Candidate('zero', 'zero'), Candidate('ridge', 'ridge', top_k=1)]
        first = run_monthly(f, ['x', 'z'], 1, specs, start='2024-09-01')
        changed = f.copy()
        changed.loc[changed.date.ge('2024-09-01'), 'net_return_1m'] = -8.
        again = run_monthly(changed, ['x', 'z'], 1, specs, start='2024-09-01')
        cols = ['date', 'candidate', 'predicted', 'selected_features']
        pd.testing.assert_frame_equal(first.loc[first.date.lt('2024-10-01'), cols].reset_index(drop=True),
                                      again.loc[again.date.lt('2024-10-01'), cols].reset_index(drop=True))

    def test_incomplete_candidate_comparison_rejected(self):
        f = sample_frame()
        p = run_monthly(f, ['x'], 1, [Candidate('zero', 'zero'), Candidate('median', 'median')], start='2024-01-01')
        p = p.drop(p.index[-1])
        with self.assertRaises(ValueError):
            summarize_research(p, select_annual(p), evaluation_start=2024)

    def test_target_audit_detects_wrong_return_and_exit(self):
        f = sample_frame()
        good = audit_targets(f, (1, 3, 5))
        self.assertEqual(sum(v['return_mismatches'] + v['exit_mismatches'] for v in good), 0)
        f.loc[0, 'net_return_1m'] = .8
        f.loc[1, 'exit_date_3m'] = pd.Timestamp('2018-01-02')
        bad = audit_targets(f, (1, 3, 5))
        self.assertEqual(bad[0]['return_mismatches'], 1)
        self.assertEqual(bad[1]['exit_mismatches'], 1)

    def test_audit_handles_gaps_and_unmatured_labels(self):
        f = sample_frame()
        # Bỏ một ngày đích rồi dựng lại nhãn theo phiên có thật đầu tiên.
        f = f.loc[f.date.ne('2020-02-29')].copy().reset_index(drop=True)
        from gold_collectors.modeling.targets import _add_calendar_month_targets
        f = _add_calendar_month_targets(f, (1,))
        a = audit_targets(f, (1,))[0]
        self.assertEqual(a['exit_mismatches'], 0)
        self.assertEqual(a['return_mismatches'], 0)
        self.assertGreater(a['pending_rows'], 0)

    def test_monthly_training_cannot_use_unknown_outcomes(self):
        f = sample_frame()
        specs = [Candidate('zero', 'zero'), Candidate('median', 'median')]
        p = run_monthly(f, ['x'], 3, specs, start='2023-01-01')
        self.assertTrue((p.train_last_exit_date < p.fold_start).all())
        self.assertTrue((p.exit_date <= f.date.max()).all())
        changed = f.copy()
        changed.loc[changed.date.ge('2023-01-01'), 'net_return_3m'] = -.9
        q = run_monthly(changed, ['x'], 3, specs, start='2023-01-01')
        fields = ['date', 'candidate', 'predicted']
        pd.testing.assert_frame_equal(p.loc[p.date.lt('2023-04-01'), fields].reset_index(drop=True),
                                      q.loc[q.date.lt('2023-04-01'), fields].reset_index(drop=True))
        self.assertEqual(p.groupby('candidate').size().nunique(), 1)

    def test_feature_leakage_and_duplicate_dates_rejected(self):
        f = sample_frame()
        for cols in (['net_return_1m'], ['future_buy_1m'], ['date'], ['unknown']):
            with self.assertRaises(ValueError):
                run_monthly(f, cols, 1, [Candidate('zero', 'zero')], start='2024-01-01')
        with self.assertRaises(ValueError):
            run_monthly(pd.concat([f, f.iloc[[0]]]), ['x'], 1, [Candidate('zero', 'zero')])

    def test_selection_only_uses_matured_previous_predictions(self):
        f = sample_frame()
        p = run_monthly(f, ['x'], 1, [Candidate('zero', 'zero'), Candidate('median', 'median')], start='2021-01-01')
        s = select_annual(p, evaluation_start=2023)
        altered = p.copy()
        altered.loc[altered.date.ge('2023-01-01'), 'actual'] = 9.
        t = select_annual(altered, evaluation_start=2023)
        self.assertEqual(s[0]['candidate'], t[0]['candidate'])
        self.assertLess(pd.Timestamp(s[0]['selection_last_exit_date']), pd.Timestamp('2023-01-01'))
        empty = select_annual(p.loc[p.date.ge('2023-01-01')], evaluation_start=2023)
        self.assertEqual(empty[0]['candidate'], 'zero')
        report = summarize_research(p, s, evaluation_start=2023)
        self.assertFalse(report['independent_validation'])
        self.assertEqual(report['status'], 'research_only')

    def test_diagnostics_calibration_and_bias(self):
        f = sample_frame()
        p = pd.DataFrame([{'date': pd.Timestamp('2023-01-01') + pd.Timedelta(days=i),
                           'horizon_months': 1, 'actual': -.1, 'predicted': .1,
                           'prob_return_positive': .8, 'q10_predicted_net_return': -.05,
                           'baseline_probability': .5} for i in range(10)])
        d = diagnose_history(p, f)
        self.assertAlmostEqual(d['by_horizon'][0]['bias'], .2)
        self.assertAlmostEqual(d['by_horizon'][0]['ece'], .8)
        self.assertAlmostEqual(d['by_horizon'][0]['q10_breach_rate'], 1.)


if __name__ == '__main__':
    unittest.main()
