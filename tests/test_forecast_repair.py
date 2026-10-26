"""Kiểm tra các lỗi nghiệp vụ từ audit: khối lượng, baseline và độ tin cậy."""

import bootstrap  # noqa: F401
import unittest
import inspect
import tempfile
import csv
import json
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
from scripts.analysis import stationary_research as research
from scripts.analysis import stationary_shadow as shadow
from scripts.processing import improve_premium_coverage as premium


class ForecastRepairTests(unittest.TestCase):
    """Dùng dữ liệu tính tay để tránh khóa luôn lỗi cũ trong kỳ vọng kiểm thử."""

    def test_global_conversion_uses_grams_without_extra_factor(self):
        """Giá một ounce nhân số ounce trong 37,5 gram, không nhân thêm 1,205."""
        self.assertAlmostEqual(4150 * 25892 / premium.LUONG_PER_OZ, 129549584.63035876)

    def test_dashboard_prefers_rebuilt_premium_over_legacy_copy(self):
        """Một bản enriched cũ không được làm web tiếp tục hiển thị phép đổi sai."""
        from scripts import build_web_data as builder
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); lake = root/'data/lake'; (lake/'gold_prices').mkdir(parents=True)
            row = dict(date='2026-10-24',buy_consensus=138700000.,sell_consensus=141700000.,
                spread_abs=3000000.,global_gold_usd_oz=4150.,usd_vnd=25892.,
                global_gold_vnd_per_luong=129549584.63,premium=12150415.37,premium_pct=.09379)
            old = {**row,'date':'2026-10-20','global_gold_vnd_per_luong':156107249.,'premium':-14407249.}
            for path,data in [(lake/'pipeline_output_premium_enriched.csv',row),(lake/'gold_prices/gold_daily_enriched.csv',old)]:
                with path.open('w',encoding='utf-8',newline='') as stream:
                    writer=csv.DictWriter(stream,fieldnames=list(data));writer.writeheader();writer.writerow(data)
            with patch.object(builder,'__file__',str(root/'scripts/build_web_data.py')), \
                    patch.object(builder,'build_recommendations',return_value={}):
                builder.main()
            summary = json.loads((root/'web/data/gold_dashboard_data.json').read_text(encoding='utf-8'))['summary']
            self.assertEqual(summary['end_date'],'2026-10-24')
            self.assertAlmostEqual(summary['latest_global_vnd'],129549585.,delta=1.)
            self.assertAlmostEqual(summary['latest_premium'],10650415.,delta=1.)

    def test_rf_median_optimizes_net_mae(self):
        """RF mới phải học trung vị lợi suất ròng, phù hợp chỉ số MAE đang chấm."""
        self.assertIn('rf_median', research.KINDS)
        estimator = research.make_model('rf_median')[-1]
        self.assertEqual(estimator.criterion, 'absolute_error')
        train = pd.DataFrame({'net_return_3m': [0.] * 200 + [10.] * 20,
                              'buy_price': 100., 'sell_price': 102.})
        x = pd.DataFrame({'x': np.arange(len(train), dtype=float) % 2})
        pred, _ = research.fit_predict('rf_median', train, train.iloc[:1], x, x.iloc[:1])
        self.assertLess(abs(pred[0]), .01)

    def test_no_forced_learning_candidate_when_baseline_wins(self):
        """Không được chọn RF kém hơn chỉ để giữ một mô hình ML trên dashboard."""
        self.assertTrue(hasattr(research, 'select_deployable_candidate'))
        dates = pd.date_range('2023-01-01', '2025-12-31')
        rows = []
        for name, prediction in [('zero', 0.), ('rf_small', .2), ('rf_median', .1)]:
            rows.append(pd.DataFrame({'date': dates, 'exit_date': dates + pd.DateOffset(months=3),
                                     'actual': .01, 'predicted': prediction, 'candidate': name}))
        p = pd.concat(rows, ignore_index=True)
        result = research.select_deployable_candidate(p, pd.Timestamp('2026-01-01'), horizon=3)
        self.assertEqual(result['candidate'], 'zero')
        self.assertFalse(result['improved_over_baseline'])
        # Nhãn có ngày thoát chưa tới cutoff không được ảnh hưởng lựa chọn.
        changed = p.copy()
        changed.loc[changed.exit_date.ge('2026-01-01'), 'actual'] = 999
        self.assertEqual(result, research.select_deployable_candidate(changed, pd.Timestamp('2026-01-01'), horizon=3))

    def test_legacy_rf_entrypoint_uses_guarded_selection(self):
        """Lệnh cũ không được kích hoạt lại RF thua baseline sau khi đã sửa."""
        from scripts.analysis import run_all_horizon_rf as entrypoint
        self.assertTrue(hasattr(entrypoint, 'run_repair'))
        with patch.object(entrypoint, 'run_repair') as run:
            entrypoint.main()
            run.assert_called_once_with()

    def test_unreliable_probability_and_q10_are_not_published(self):
        """Giữ chỉ số nghiên cứu để kiểm toán nhưng không công bố độ tin cậy giả."""
        self.assertTrue(hasattr(shadow, 'publication_quality'))
        dates = pd.date_range('2023-01-01', '2024-12-31')
        p = pd.DataFrame({'date': dates, 'exit_date': dates + pd.DateOffset(months=3),
                          'actual': np.tile([-.1, .1], len(dates)//2+1)[:len(dates)],
                          'predicted': .05, 'probability': .99, 'q10': -.01,
                          'baseline_probability': .5, 'baseline_q10': -.1})
        result = shadow.publication_quality(p, pd.Timestamp('2025-05-01'), horizon=3)
        self.assertFalse(result['probability_qualified'])
        self.assertFalse(result['q10_qualified'])
        self.assertGreater(result['metrics']['q10_breach_rate'], .15)
        changed = p.copy()
        changed.loc[changed.exit_date.ge('2024-01-01'), 'actual'] = 999
        earlier = shadow.publication_quality(p, pd.Timestamp('2024-01-01'), horizon=3)
        self.assertEqual(earlier, shadow.publication_quality(changed, pd.Timestamp('2024-01-01'), horizon=3))

    def test_probability_and_quantile_missing_data_are_independent(self):
        """Thiếu P không làm mất Q10 hợp lệ; thiếu Q10 không làm mất P hợp lệ."""
        dates = pd.date_range('2023-01-01', '2025-12-31')
        actual = np.resize([-.1, .1], len(dates))
        p = pd.DataFrame({'date':dates,'exit_date':dates+pd.DateOffset(months=3),
                          'actual':actual,'predicted':0.,'probability':np.where(actual>0,.95,.05),
                          'q10':-.1,'baseline_probability':.5,'baseline_q10':-.1})
        no_p = p.copy(); no_p.loc[0,'probability'] = np.nan
        result = shadow.publication_quality(no_p,pd.Timestamp('2026-05-01'),horizon=3)
        self.assertTrue(result['q10_qualified'])
        self.assertFalse(result['probability_qualified'])
        self.assertTrue(any('thiếu' in reason.lower() for reason in result['probability_reasons']))
        no_q = p.copy(); no_q.loc[0,'q10'] = np.nan
        result = shadow.publication_quality(no_q,pd.Timestamp('2026-05-01'),horizon=3)
        self.assertTrue(result['probability_qualified'])
        self.assertFalse(result['q10_qualified'])

    def test_normal_training_routes_active_pipeline_before_legacy_fit(self):
        """Cập nhật thường ngày phải ghi dự báo đang dùng trước khi gọi sổ mô phỏng."""
        from scripts.analysis import train_latest_snapshot as trainer
        self.assertTrue(hasattr(trainer,'refresh_active_pipeline'))
        with tempfile.TemporaryDirectory() as td:
            f = pd.DataFrame({'date':pd.to_datetime(['2026-10-24']),'x':[1.]})
            f.attrs['feature_columns'] = ['x']
            with patch.object(trainer,'ROOT',Path(td)), patch.object(trainer,'build_model_frame',return_value=f), \
                    patch.object(trainer,'refresh_active_pipeline',return_value=True) as refresh, \
                    patch.object(trainer,'make_point_model') as legacy:
                trainer.main()
                refresh.assert_called_once_with(Path(td)/'data/lake')
                legacy.assert_not_called()

    def test_publisher_and_repeated_refresh_use_same_active_forecasts(self):
        """CSV và đầu vào sổ mô phỏng phải giữ mô hình đã chọn ở các lượt cập nhật sau."""
        from scripts.analysis import active_snapshot as publisher
        with tempfile.TemporaryDirectory() as td:
            lake = Path(td); modeling = lake/'modeling'; modeling.mkdir()
            (modeling/'active_prediction_model.json').write_text(json.dumps(
                {'mode':'direct_forecast','forecast_pipeline':'reliability_v2'}),encoding='utf-8')
            (modeling/'model_frame_daily.csv').write_text('date\n2026-10-24\n',encoding='utf-8')
            def latest(_modeling, expected, *, horizon):
                return dict(snapshot_date=expected,horizon_months=horizon,candidate='zero',predicted_net_return=0.,
                    prob_return_positive=None,q10_predicted_net_return=None,probability_method='temporal_oos_brier_weighted_v2',
                    calibration_rows=600,entry_sell_price=102.,baseline_probability=.5,baseline_q10=-.1,
                    validation={'protocol_id':str(horizon)*24,'validation_start':'2026-10-27',
                                'status':'validation_pending','horizon_months':horizon,'checks':{},'metrics':{},'reasons':[]})
            def ledger(snapshot_path,*args,**kwargs):
                rows = pd.read_csv(snapshot_path)
                self.assertTrue(rows.point_model.str.contains('zero').all())
                self.assertTrue(rows.prob_return_positive.isna().all())
                return [],{}
            with patch.object(publisher,'load_active_forecast',side_effect=latest), \
                    patch('scripts.analysis.run_rolling_paper_trading.build_ledger_and_summary',side_effect=ledger) as book, \
                    patch('scripts.build_web_data.main') as dashboard:
                self.assertTrue(publisher.refresh_active_pipeline(lake))
                self.assertTrue(publisher.refresh_active_pipeline(lake))
                self.assertEqual(book.call_count,2)
                self.assertEqual(dashboard.call_count,2)
            report = json.loads((modeling/'snapshot_validation_report.json').read_text(encoding='utf-8'))
            rows = pd.read_csv(modeling/'snapshot_forecasts.csv')
            self.assertTrue(rows.validation_protocol_id.eq(report['protocol_id']).all())
            self.assertEqual(len(set(report['horizon_protocols'].values())),3)

    def test_calibration_uses_prequential_errors_and_baseline(self):
        """Xác suất sai trên OOS phải lùi về prior; Q10 thiếu coverage phải hạ xuống."""
        self.assertIn('baseline_probability', inspect.signature(research.calibrate).parameters)
        dates = pd.date_range('2021-01-01', '2023-12-31')
        past = pd.DataFrame({'date': dates, 'exit_date': dates + pd.DateOffset(months=3),
            'actual': np.tile([-.2, .2], len(dates)//2+1)[:len(dates)], 'predicted': 0.,
            'sigmoid_probability': .99, 'baseline_probability': .5, 'q10': .02})
        result = research.calibrate(past, np.array([.1]), baseline_probability=.5,
                                    cutoff=pd.Timestamp('2024-01-01'))
        self.assertEqual(result['probability_weight'], 0.)
        self.assertAlmostEqual(result['probability'][0], .5)
        self.assertLess(result['q10'][0], -.2)
        changed = past.copy()
        changed.loc[changed.exit_date.ge('2024-01-01'), 'actual'] = 999
        again = research.calibrate(changed, np.array([.1]), baseline_probability=.5,
                                   cutoff=pd.Timestamp('2024-01-01'))
        np.testing.assert_allclose(result['q10'], again['q10'])
        np.testing.assert_allclose(result['probability'], again['probability'])

    def test_baseline_and_withheld_metrics_have_visible_explanations(self):
        """Người xem phải biết đang dùng baseline và vì sao P/Q10 còn thiếu."""
        from scripts.build_web_data import build_recommendations
        with tempfile.TemporaryDirectory() as td:
            lake = Path(td); modeling = lake/'modeling'; modeling.mkdir()
            rows = [dict(snapshot_date='2026-10-24', horizon_months=h, predicted_net_return=0.,
                         entry_sell_price=102., status='validation_pending') for h in (1,3,5)]
            with (modeling/'snapshot_forecasts.csv').open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            (modeling/'model_frame_daily.csv').write_text('date,buy_price,sell_price\n2026-10-24,100,102\n',encoding='utf-8')
            (modeling/'active_prediction_model.json').write_text(json.dumps({'horizons':{'3':{}}}),encoding='utf-8')
            active = dict(candidate='zero', predicted_net_return=0., entry_sell_price=102., margin=.01,
                          prob_return_positive=None, q10_predicted_net_return=None,
                          research_prob_return_positive=.6243, research_q10_predicted_net_return=-.1234,
                          calibration_quality={'probability_qualified':False, 'q10_qualified':False,
                                               'reasons':['Brier chưa đạt.']}, validation={'status':'validation_pending'})
            with patch('scripts.analysis.stationary_activation.load_active_forecast', return_value=active):
                result = build_recommendations(lake, expected_snapshot_date='2026-10-24')
            h = result['horizons'][1]
            self.assertIn('tham chiếu', h['model_label'])
            self.assertIn('Brier', h['calibration_note'])
            self.assertIsNone(h['prob_return_positive'])
            self.assertEqual(h['research_prob_return_positive'], 62.43)
            self.assertEqual(h['research_q10_predicted_net_return'], -12.34)

    def test_q10_respects_maximum_possible_loss(self):
        """Mua vàng không vay không thể có lợi suất thấp hơn âm 100%."""
        dates = pd.date_range('2021-01-01', '2022-12-31')
        past = pd.DataFrame({'date':dates, 'exit_date':dates+pd.DateOffset(months=1),
                              'actual':np.resize([-.5,.5],len(dates)), 'predicted':2.})
        result = research.calibrate(past, np.array([-.9]))
        self.assertGreaterEqual(result['q10'][0], -1.)

    def test_journal_keeps_raw_metrics_when_publication_is_blocked(self):
        """Không xóa dự báo nghiên cứu khỏi bằng chứng tiến cứu khi UI trả null."""
        from test_stationary_model import frame
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as td:
            modeling = Path(td)
            root = modeling/'stationary_shadow'
            identity = 'a'*24
            folder = root/identity
            folder.mkdir(parents=True)
            (root/'active.json').write_text(json.dumps({'protocol_id':identity}),encoding='utf-8')
            f = frame()
            f.to_csv(modeling/'model_frame_daily.csv',index=False,encoding='utf-8')
            dates = pd.date_range('2021-01-01','2023-12-31')
            entries = f.set_index('date').loc[dates, 'sell_price'].to_numpy()
            pd.DataFrame({'date':dates,'sell_price':entries,'predicted':0.,'probability':.5,
                          'q10':-.1,'baseline_probability':.5,'baseline_q10':-.1,
                          'sigmoid_probability':.5}).to_csv(folder/'calibration.csv',index=False,encoding='utf-8')
            lock = dict(protocol_id=identity,horizon_months=3,candidate='zero',margin=.01,
                        created_at='2024-01-01T00:00:00+00:00',validation_start='2024-01-02',
                        policy=shadow.load_policy())
            blocked = dict(status='research_only',probability_qualified=False,q10_qualified=False,
                           checks={},metrics={},reasons=['Chưa đạt kiểm tra.'])
            with patch.object(shadow,'read_lock',return_value=lock), patch.object(shadow,'publication_quality',return_value=blocked):
                shadow.record_latest(modeling,now=datetime(2024,12,31,10,tzinfo=timezone.utc))
            latest = json.loads((root/'latest.json').read_text(encoding='utf-8'))
            records = shadow.read_records(root,lock)
            self.assertIsNone(latest['prob_return_positive'])
            self.assertIsNone(latest['q10_predicted_net_return'])
            self.assertEqual(len(records),1)
            self.assertIsNotNone(records[0]['prob_return_positive'])
            self.assertIsNotNone(records[0]['q10_predicted_net_return'])


if __name__ == '__main__':
    unittest.main()
