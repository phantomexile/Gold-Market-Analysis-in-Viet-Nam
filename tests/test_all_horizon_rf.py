"""RF dùng đúng nhãn, hiệu chỉnh và bản khóa riêng của từng kỳ hạn."""

import bootstrap  # noqa: F401
import tempfile
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch
import unittest
import numpy as np
import pandas as pd

from scripts.analysis.stationary_research import fit_predict, run_experiment
from scripts.analysis.stationary_shadow import create_lock, shadow_root
from scripts.analysis.stationary_activation import activate_candidate, load_active_forecast
from scripts.analysis.run_model_research import write_json


class AllHorizonTests(unittest.TestCase):
    def test_walk_forward_uses_calendar_maturity_of_each_horizon(self):
        from test_stationary_model import frame
        for horizon in (1, 5):
            with self.subTest(horizon=horizon):
                f = frame().drop(columns=['exit_date_3m', 'net_return_3m'])
                dates = pd.DatetimeIndex(f.date)
                positions = dates.searchsorted(dates+pd.DateOffset(months=horizon))
                known = positions < len(f)
                f[f'exit_date_{horizon}m'] = pd.NaT
                f.loc[known, f'exit_date_{horizon}m'] = dates[positions[known]].to_numpy()
                f[f'net_return_{horizon}m'] = np.nan
                f.loc[known, f'net_return_{horizon}m'] = f.buy_price.to_numpy()[positions[known]]/f.sell_price.to_numpy()[known]-1
                p = run_experiment(f, start='2023-01-01', kinds=('rf_small',), progress=None, horizon=horizon)
                self.assertTrue(p.horizon_months.eq(horizon).all())
                self.assertTrue((p.train_last_exit_date < p.fold_start).all())
                calibrated = p.calibration_last_exit_date.notna()
                self.assertTrue(calibrated.any())
                self.assertTrue((p.loc[calibrated, 'calibration_last_exit_date'] < p.loc[calibrated, 'fold_start']).all())
                self.assertTrue(p.actual.isna().any())
                self.assertEqual(list(p.date), list(f.loc[f.date.ge('2023-01-01'), 'date']))

    def test_malformed_activation_entry_is_a_controlled_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            modeling = Path(directory)
            write_json(modeling/'active_prediction_model.json',
                       {'mode': 'direct_forecast', 'horizons': {'1': []}})
            with patch('scripts.analysis.stationary_activation.read_lock', return_value={}), self.assertRaises(ValueError):
                load_active_forecast(modeling, '2026-10-24', horizon=1)

    def test_targets_are_separate_and_do_not_require_three_month_labels(self):
        for horizon in (1, 3, 5):
            with self.subTest(horizon=horizon):
                train = pd.DataFrame({f'net_return_{horizon}m': [.01*horizon]*300,
                                      'buy_price': [100.]*300, 'sell_price': [102.]*300})
                x = pd.DataFrame({'momentum': np.arange(300, dtype=float)})
                predicted, _ = fit_predict('rf_small', train, train.iloc[:1], x, x.iloc[:1], horizon=horizon)
                self.assertAlmostEqual(predicted[0], .01*horizon)
        with self.assertRaises(ValueError):
            fit_predict('zero', train, train, x, x, horizon=2)

    def test_activation_routes_every_horizon_to_its_own_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            modeling = Path(directory)/'modeling'
            modeling.mkdir()
            calibration = modeling/'input.csv'
            calibration.write_text('date,predicted,sell_price\n2025-01-01,0,102\n', encoding='utf-8')
            with patch('scripts.analysis.stationary_shadow.algorithm_fingerprint', return_value='test'):
                locks = {}
                for horizon in (1, 3, 5):
                    root = shadow_root(modeling, horizon)
                    locks[horizon] = create_lock(root, calibration, candidate='rf_small', margin=.01,
                                                now=datetime.now(timezone.utc), horizon=horizon)
                    write_json(root/'latest.json', dict(snapshot_date='2026-10-24', horizon_months=horizon,
                        candidate='rf_small', margin=.01, predicted_net_return=horizon/100,
                        entry_sell_price=102., validation={'protocol_id': locks[horizon]['protocol_id']}))
                config = activate_candidate(modeling, horizons=(1, 3, 5))
                self.assertEqual(set(config['horizons']), {'1', '3', '5'})
                with patch('scripts.analysis.stationary_activation.record_latest'):
                    for horizon in (1, 3, 5):
                        row = load_active_forecast(modeling, '2026-10-24', horizon=horizon)
                        self.assertEqual(row['horizon_months'], horizon)
                        self.assertEqual(row['predicted_net_return'], horizon/100)
                    # Dựng dữ liệu giao diện thật từ registry; điểm/P/Q10 phải
                    # đồng bộ từng kỳ hạn và lỗi 5 tháng không chặn 1/3 tháng.
                    pd.DataFrame([dict(snapshot_date='2026-10-24', horizon_months=h,
                        predicted_net_return=.2, entry_sell_price=102) for h in (1,3,5)]).to_csv(
                            modeling/'snapshot_forecasts.csv', index=False, encoding='utf-8')
                    (modeling/'model_frame_daily.csv').write_text(
                        'date,buy_price,sell_price\n2026-10-24,100,102\n', encoding='utf-8')
                    from scripts.build_web_data import build_recommendations
                    result = build_recommendations(modeling.parent, expected_snapshot_date='2026-10-24')
                    self.assertEqual([h['point_model'] for h in result['horizons']],
                                     [f'stationary_rf_small_{h}m' for h in (1,3,5)])
                    self.assertEqual([h['predicted_net_return'] for h in result['horizons']], [1.,3.,5.])
                    # Không được lấy dữ liệu 3 tháng cho kỳ hạn 5 tháng.
                    latest = shadow_root(modeling, 5)/'latest.json'
                    import json
                    value = json.loads(latest.read_text(encoding='utf-8'))
                    value['horizon_months'] = 3
                    write_json(latest, value)
                    with self.assertRaises(ValueError):
                        load_active_forecast(modeling, '2026-10-24', horizon=5)
                    result = build_recommendations(modeling.parent, expected_snapshot_date='2026-10-24')
                    self.assertEqual([h['signal'] for h in result['horizons']], ['observe','buy','observe'])
                    self.assertIsNone(result['horizons'][2]['predicted_net_return'])


if __name__ == '__main__':
    unittest.main()
