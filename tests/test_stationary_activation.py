"""Kích hoạt RF mới chỉ cho ba tháng, không đổi nhãn kiểm định hoặc hai kỳ hạn khác."""

import bootstrap  # noqa: F401
import csv
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.analysis.stationary_activation import activate_candidate
from scripts.build_web_data import build_recommendations


class ActivationTests(unittest.TestCase):
    def test_active_three_month_model_replaces_all_forecast_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            lake = Path(folder)
            modeling = lake/'modeling'
            modeling.mkdir()
            lock = {'protocol_id': 'a'*24, 'candidate': 'rf_small', 'margin': .01, 'source_id': 'code'}
            rows = [dict(snapshot_date='2026-10-24', horizon_months=h, predicted_net_return=.1,
                         q10_predicted_net_return=-.03, prob_return_positive=.9,
                         entry_sell_price=102, status='validation_pending') for h in (1,3,5)]
            with (modeling/'snapshot_forecasts.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            (modeling/'model_frame_daily.csv').write_text('date,buy_price,sell_price\n2026-10-24,100,102\n',encoding='utf-8')
            latest = dict(snapshot_date='2026-10-24', horizon_months=3, candidate='rf_small', margin=.01,
                          predicted_net_return=-.05, q10_predicted_net_return=-.12, prob_return_positive=.3,
                          entry_sell_price=102., probability_method='sigmoid_temporal_oos',
                          calibration_rows=500, validation={'protocol_id': 'a'*24,'status':'validation_pending',
                                                           'metrics':{'matured_rows':0}})
            (modeling/'stationary_shadow').mkdir()
            (modeling/'stationary_shadow/latest.json').write_text(json.dumps(latest),encoding='utf-8')
            with patch('scripts.analysis.stationary_activation.read_lock',return_value=lock), \
                 patch('scripts.analysis.stationary_activation.record_latest') as record:
                activate_candidate(modeling)
                result=build_recommendations(lake,expected_snapshot_date='2026-10-24')
                self.assertEqual(record.call_count,1)
                self.assertEqual([h['signal'] for h in result['horizons']],['buy','sell','buy'])
                h=result['horizons'][1]
                self.assertEqual(h['predicted_net_return'],-5.)
                self.assertEqual(h['q10_predicted_net_return'],-12.)
                self.assertEqual(h['prob_return_positive'],30.)
                self.assertEqual(h['point_model'],'stationary_rf_small_3m')
                self.assertEqual(h['status'],'validation_pending')
                self.assertFalse(h['validated_buy_signal'])
                self.assertEqual(result['primary_signal'],'sell')
                # Thành tích mô phỏng của mô hình cũ không được gán cho bản mới.
                from scripts import build_web_data as builder
                old_builder=builder._build_validated_recommendations
                def old_simulation(*args,**kwargs):
                    data=old_builder(*args,**kwargs)
                    for horizon in data['horizons']:
                        horizon['simulation_buy_signal']=True
                    return data
                with patch.object(builder,'_build_validated_recommendations',side_effect=old_simulation):
                    clean=build_recommendations(lake,expected_snapshot_date='2026-10-24')
                    self.assertFalse(clean['horizons'][1]['simulation_buy_signal'])
                    self.assertTrue(clean['horizons'][0]['simulation_buy_signal'])
                # Bản mới lỗi phải Quan sát, không tự dùng số liệu/cờ mua cũ.
                latest['snapshot_date']='2026-10-23'
                (modeling/'stationary_shadow/latest.json').write_text(json.dumps(latest),encoding='utf-8')
                stale=build_recommendations(lake,expected_snapshot_date='2026-10-24')
                self.assertEqual(stale['horizons'][1]['signal'],'observe')
                self.assertIsNone(stale['horizons'][1]['predicted_net_return'])
                self.assertEqual(stale['horizons'][0]['signal'],'buy')

    def test_lock_mismatch_prevents_using_the_activated_candidate(self):
        with tempfile.TemporaryDirectory() as folder:
            modeling=Path(folder)
            lock={'protocol_id':'a'*24,'candidate':'rf_small','margin':.01,'source_id':'code'}
            with patch('scripts.analysis.stationary_activation.read_lock',return_value=lock):
                config=activate_candidate(modeling)
                self.assertEqual(config['horizon_months'],3)
                self.assertEqual(config['mode'],'direct_forecast')
            from scripts.analysis.stationary_activation import load_active_forecast
            with patch('scripts.analysis.stationary_activation.read_lock',return_value={**lock,'protocol_id':'b'*24}):
                with self.assertRaises(ValueError):
                    load_active_forecast(modeling,'2026-10-24')


if __name__=='__main__':
    unittest.main()
