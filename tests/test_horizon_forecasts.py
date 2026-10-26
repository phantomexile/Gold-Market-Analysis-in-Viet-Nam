"""Baseline là đối chứng, không thay cả ba dự báo tháng lịch bằng số không."""

import bootstrap  # noqa: F401
import importlib.util
import unittest
import tempfile
import csv
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd


class HorizonForecastTests(unittest.TestCase):
    """Dự báo thử nghiệm và điều kiện đủ chuẩn phải được giữ tách biệt."""

    def test_losing_ml_still_has_a_research_forecast_not_zero(self):
        """Đối chứng thắng không được xóa đầu ra ML hoặc cấp validated cho ML."""
        self.assertIsNotNone(importlib.util.find_spec('scripts.analysis.forecast_selection'))
        from scripts.analysis.forecast_selection import select_research_forecast
        dates = pd.date_range('2023-01-01','2025-12-31')
        for horizon in (1,3,5):
            with self.subTest(horizon=horizon):
                rows=[]
                for name,prediction in [('zero',0.),('rf_small',horizon*.02),('rf_median',horizon*.03)]:
                    rows.append(pd.DataFrame({'date':dates,'exit_date':dates+pd.DateOffset(months=horizon),
                        'actual':.001,'predicted':prediction,'candidate':name}))
                p=pd.concat(rows,ignore_index=True)
                selected=select_research_forecast(p,pd.Timestamp('2026-01-01'),horizon=horizon)
                self.assertEqual(selected['candidate'],'rf_small')
                self.assertEqual(selected['benchmark_winner'],'zero')
                self.assertEqual(selected['forecast_role'],'research')
                self.assertFalse(selected['improved_over_baseline'])
                changed=p.copy()
                changed.loc[changed.exit_date.ge('2026-01-01'),'actual']=999
                self.assertEqual(selected,select_research_forecast(changed,pd.Timestamp('2026-01-01'),horizon=horizon))

    def test_missing_ml_is_an_error_not_a_fake_zero_forecast(self):
        """Thiếu dự báo ML phải báo thiếu, không giả thành dự báo lợi suất 0."""
        self.assertIsNotNone(importlib.util.find_spec('scripts.analysis.forecast_selection'))
        from scripts.analysis.forecast_selection import select_research_forecast
        dates=pd.date_range('2023-01-01','2025-12-31')
        p=pd.DataFrame({'date':dates,'exit_date':dates+pd.DateOffset(months=3),
                        'actual':.001,'predicted':0.,'candidate':'zero'})
        with self.assertRaisesRegex(ValueError,'ML'):
            select_research_forecast(p,pd.Timestamp('2026-01-01'),horizon=3)

    def test_direct_display_retains_forecasts_and_failed_benchmark_note(self):
        """Dự báo ML không bị thay bằng zero khi chưa vượt baseline, có ghi rõ giới hạn."""
        from scripts.build_web_data import build_recommendations
        with tempfile.TemporaryDirectory() as td:
            lake=Path(td);modeling=lake/'modeling';modeling.mkdir()
            rows=[dict(snapshot_date='2026-10-24',horizon_months=h,predicted_net_return=0.,
                       entry_sell_price=102.,status='validation_pending') for h in (1,3,5)]
            with (modeling/'snapshot_forecasts.csv').open('w',encoding='utf-8',newline='') as stream:
                writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
            (modeling/'model_frame_daily.csv').write_text('date,buy_price,sell_price\n2026-10-24,100,102\n',encoding='utf-8')
            (modeling/'active_prediction_model.json').write_text(json.dumps({'horizons':{str(h):{} for h in (1,3,5)}}),encoding='utf-8')
            def active(_modeling,_expected,*,horizon):
                return dict(candidate='rf_small',predicted_net_return=horizon*.01,entry_sell_price=102.,margin=.01,
                    prob_return_positive=None,q10_predicted_net_return=None,validation={'status':'validation_pending'},
                    forecast_selection={'forecast_role':'research','improved_over_baseline':False,
                                        'reason':'Chưa đạt tiêu chí tốt hơn baseline.'})
            with patch('scripts.analysis.stationary_activation.load_active_forecast',side_effect=active):
                result=build_recommendations(lake,expected_snapshot_date='2026-10-24')
            self.assertEqual([row['predicted_net_return'] for row in result['horizons']],[1.,3.,5.])
            for row in result['horizons']:
                self.assertIn('forecast_note',row)
                self.assertIn('Chưa đạt',row['forecast_note'])
                self.assertIn('thử nghiệm',row['model_label'])
                self.assertFalse(row['validated_buy_signal'])

    def test_saved_frame_preserves_the_trained_forecast(self):
        """Lưu/đọc CSV không được đổi nhánh cây do mất chữ số của số thực."""
        from datetime import datetime,timezone
        from test_stationary_model import frame
        from scripts.analysis.stationary_features import build_stationary_features
        from scripts.analysis.stationary_research import fit_predict
        from scripts.analysis import stationary_shadow as shadow
        f=frame()
        begin=f.date.max().to_period('M').start_time
        mask=f.date.ge(begin-pd.DateOffset(years=5)) & f.date.lt(begin) & f.exit_date_3m.lt(begin) & f.net_return_3m.notna()
        x=build_stationary_features(f)
        expected,_=fit_predict('rf_median',f.loc[mask],f.iloc[[-1]],x.loc[mask],x.iloc[[-1]],horizon=3)
        with tempfile.TemporaryDirectory() as td:
            modeling=Path(td);root=modeling/'stationary_shadow';identity='b'*24;folder=root/identity
            folder.mkdir(parents=True)
            (root/'active.json').write_text(json.dumps({'protocol_id':identity}),encoding='utf-8')
            f.to_csv(modeling/'model_frame_daily.csv',index=False,encoding='utf-8')
            dates=pd.date_range('2021-01-01','2023-12-31')
            pd.DataFrame({'date':dates,'sell_price':f.set_index('date').loc[dates,'sell_price'].to_numpy(),
                'predicted':0.,'probability':.5,'q10':-.1,'baseline_probability':.5,
                'baseline_q10':-.1,'sigmoid_probability':.5}).to_csv(folder/'calibration.csv',index=False,encoding='utf-8')
            lock=dict(protocol_id=identity,horizon_months=3,candidate='rf_median',margin=.01,
                created_at='2024-01-01T00:00:00+00:00',validation_start='2024-01-02',policy=shadow.load_policy())
            with patch.object(shadow,'read_lock',return_value=lock):
                shadow.record_latest(modeling,now=datetime(2024,12,31,10,tzinfo=timezone.utc))
            latest=json.loads((root/'latest.json').read_text(encoding='utf-8'))
            self.assertAlmostEqual(latest['predicted_net_return'],float(expected[0]),places=12)


if __name__=='__main__':
    unittest.main()
