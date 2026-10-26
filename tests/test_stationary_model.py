"""Kiểm tra mô hình tỷ lệ/biến động và quyết định không nhìn kết quả tương lai."""

import bootstrap  # noqa: F401
import unittest
import numpy as np
import pandas as pd

from scripts.analysis.stationary_features import build_stationary_features
from scripts.analysis.stationary_research import run_experiment, choose_candidate
from scripts.analysis.stationary_evaluation import backtest, block_interval, evaluate_candidate, select_path, signal_diagnostics


def frame():
    """Giá biến động có spread thật để kiểm tra lợi nhuận mua mới/đang giữ."""
    dates = pd.date_range('2017-01-01', '2024-12-31')
    price = 100 * np.exp(np.arange(len(dates)) * .0001 + .03 * np.sin(np.arange(len(dates))/50))
    f = pd.DataFrame({'date': dates, 'buy_price': price, 'sell_price': price * 1.02,
                      'gold_futures_close_usd_oz': price * 10, 'usd_vnd': 24000., 'premium_pct': 3.})
    positions = dates.searchsorted(dates + pd.DateOffset(months=3))
    valid = positions < len(dates)
    f['exit_date_3m'] = pd.NaT
    f.loc[valid, 'exit_date_3m'] = dates[positions[valid]].to_numpy()
    f['net_return_3m'] = np.nan
    f.loc[valid, 'net_return_3m'] = price[positions[valid]] / (price[valid] * 1.02) - 1
    return f


class StationaryTests(unittest.TestCase):
    def test_observe_reports_missed_buy_opportunities(self):
        p = pd.DataFrame({'date': pd.to_datetime(['2023-01-01', '2023-05-01']),
                          'exit_date': pd.to_datetime(['2023-04-01', '2023-08-01']),
                          'predicted': [0., 0.], 'actual': [.1, -.1], 'buy_price': [100., 100.],
                          'sell_price': [102., 102.]})
        result = signal_diagnostics(p)
        self.assertEqual(result['observe']['missed_profitable_buy_rate'], .5)
        self.assertEqual(result['observe']['missed_beneficial_sell_rate'], .5)

    def test_features_causal_and_scale_invariant(self):
        f = frame()
        x = build_stationary_features(f)
        self.assertLessEqual(len(x.columns), 40)
        self.assertGreater(len(x.columns), 20)
        changed = f.copy()
        changed.loc[changed.date.ge('2024-01-01'), 'buy_price'] *= 5
        changed.loc[changed.date.ge('2024-01-01'), 'net_return_3m'] = 8.
        again = build_stationary_features(changed)
        pd.testing.assert_frame_equal(x.loc[f.date.lt('2024-01-01')], again.loc[f.date.lt('2024-01-01')])
        scaled = f.copy()
        scaled[['buy_price', 'sell_price']] *= 1000
        np.testing.assert_allclose(x.to_numpy(), build_stationary_features(scaled).to_numpy(), atol=1e-9, equal_nan=True)
        self.assertFalse(any('future' in c or 'target' in c for c in x))

    def test_monthly_forecasts_purge_and_calibration(self):
        f = frame()
        p = run_experiment(f, start='2022-01-01', kinds=('zero', 'median', 'ridge'), progress=None)
        self.assertEqual(p.groupby('candidate').size().nunique(), 1)
        self.assertTrue((pd.to_datetime(p.train_last_exit_date) < p.fold_start).all())
        eligible = p.calibration_last_exit_date.notna()
        self.assertTrue((p.loc[eligible, 'calibration_last_exit_date'] < p.loc[eligible, 'fold_start']).all())
        changed = f.copy()
        changed.loc[changed.date.ge('2024-01-01'), 'net_return_3m'] = .9
        q = run_experiment(changed, start='2022-01-01', kinds=('zero', 'median', 'ridge'), progress=None)
        cols = ['date', 'candidate', 'predicted', 'probability', 'q10']
        pd.testing.assert_frame_equal(p.loc[p.date.lt('2024-04-01'), cols].reset_index(drop=True),
                                      q.loc[q.date.lt('2024-04-01'), cols].reset_index(drop=True))

    def test_selection_excludes_unmatured_and_falls_back(self):
        cutoff = pd.Timestamp('2024-01-01')
        rows = []
        for d in pd.date_range('2022-01-01', '2023-01-01'):
            for name in ('zero', 'ridge'):
                rows.append(dict(date=d, exit_date=d+pd.DateOffset(months=3), candidate=name,
                                 actual=.1, predicted=0. if name == 'zero' else .1))
        p = pd.DataFrame(rows)
        c = choose_candidate(p, cutoff)
        self.assertEqual(c['candidate'], 'ridge')
        p['exit_date'] = cutoff
        self.assertEqual(choose_candidate(p, cutoff)['candidate'], 'zero')

    def test_backtest_deducts_spread_and_keeps_cash(self):
        prices = pd.DataFrame({'date': pd.to_datetime(['2024-01-01', '2024-02-01', '2024-03-01']),
                               'buy_price': [100., 100., 100.], 'sell_price': [102., 102., 102.]})
        p = prices[['date']].assign(predicted=.1)
        result = backtest(p, prices, margin=.01)
        self.assertAlmostEqual(result['total_return'], 100/102-1)
        self.assertEqual(result['buys'], 1)
        observe = backtest(p.assign(predicted=0.), prices, margin=.01)
        self.assertEqual(observe['total_return'], 0.)
        self.assertEqual(observe['buys'], 0)
        sell = p.copy()
        sell.loc[1:, 'predicted'] = -.1
        closed = backtest(sell, prices, margin=.01)
        self.assertEqual(closed['sells'], 1)
        self.assertAlmostEqual(closed['total_return'], 100/102-1)

    def test_block_interval_uses_months_not_daily_independence(self):
        p = pd.DataFrame({'date': pd.date_range('2023-01-01', '2024-12-31'), 'actual': .1, 'predicted': .05})
        result = block_interval(p)
        self.assertAlmostEqual(result['lower'], .5)
        self.assertAlmostEqual(result['upper'], .5)
        self.assertEqual(result['block_months'], 3)

    def test_historical_report_never_grants_validated(self):
        f = frame()
        dates = pd.date_range('2023-01-01', '2024-01-01')
        p = pd.DataFrame({'date': dates, 'exit_date': dates+pd.DateOffset(months=3),
                          'actual': .1, 'predicted': .05, 'probability': .8, 'raw_probability': .9,
                          'q10': -.01, 'q10_gbr': -.02, 'baseline_probability': .5, 'baseline_q10': -.1,
                          'buy_price': 100., 'sell_price': 102.})
        r = evaluate_candidate(p, f)
        self.assertEqual(r['status'], 'research_only')
        self.assertFalse(r['independent_validation'])
        self.assertIn('probability_ece', r['quality']['metrics'])
        # Ngưỡng theo từng tháng phải dùng được trong danh mục hợp nhất.
        neutral = p.copy()
        neutral['predicted'] = .015
        neutral['margin'] = .02
        self.assertEqual(backtest(neutral, f)['buys'], 0)

    def test_monthly_path_choice_is_invariant_to_future_outcomes(self):
        f = frame()
        rows = []
        for d in pd.date_range('2021-01-01', '2024-12-31'):
            for name in ('zero', 'ridge'):
                rows.append(dict(date=d, exit_date=d+pd.DateOffset(months=3), candidate=name,
                                 actual=.1, predicted=.1 if name == 'ridge' else 0., buy_price=100., sell_price=102.))
        p = pd.DataFrame(rows)
        path, choices = select_path(p, f, start='2024-01-01')
        changed = p.copy()
        changed.loc[changed.date.ge('2024-01-01'), 'actual'] = -.9
        again, _ = select_path(changed, f, start='2024-01-01')
        pd.testing.assert_series_equal(path.loc[path.date.lt('2024-04-01'), 'candidate'],
                                       again.loc[again.date.lt('2024-04-01'), 'candidate'])


if __name__ == '__main__':
    unittest.main()
