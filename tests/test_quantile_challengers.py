"""Đối chứng hai thuật toán phải giữ thời gian, đơn vị lợi suất và artifact vận hành."""

import bootstrap  # noqa: F401
import unittest
from importlib.util import find_spec
from unittest.mock import patch
import numpy as np
import pandas as pd

from scripts.analysis.quantile_challengers import ordered_net_quantiles, run_challengers, interval_metrics, fit_quantiles


class QuantileTests(unittest.TestCase):
    @unittest.skipUnless(find_spec('lightgbm') and find_spec('catboost'),'Hai thư viện thử nghiệm chưa có trong môi trường này.')
    def test_real_cpu_adapters_return_three_quantiles(self):
        rng=np.random.default_rng(42)
        x=rng.normal(size=(500,5))
        y=.03*x[:,0]+rng.normal(0,.01,size=500)
        for kind in ('lightgbm_quantile','catboost_multiquantile'):
            with self.subTest(kind=kind):
                raw=fit_quantiles(kind,x,y,x[:7])
                self.assertEqual(raw.shape,(7,3))
                net,_=ordered_net_quantiles(raw,np.full(7,100.),np.full(7,102.))
                self.assertTrue(np.isfinite(net).all())

    def test_quantiles_order_and_spread_conversion(self):
        hold=np.array([[.2,-.1,.05],[.01,.02,.03]])
        result,crossed=ordered_net_quantiles(hold,np.array([100.,100.]),np.array([102.,102.]))
        self.assertEqual(crossed,1)
        np.testing.assert_allclose(result[0],(1+np.sort(hold[0]))*100/102-1)
        self.assertTrue((np.diff(result,axis=1)>=0).all())
        with self.assertRaises(ValueError):
            ordered_net_quantiles(np.array([[float('nan'),0,1]]),np.array([100.]),np.array([102.]))

    def test_time_split_and_calibration_only_use_matured_past(self):
        dates=pd.date_range('2017-01-01','2024-12-31')
        f=pd.DataFrame({'date':dates,'buy_price':100+np.arange(len(dates))*.02})
        f['sell_price']=f.buy_price*1.02
        f['exit_date_3m']=dates+pd.DateOffset(months=3)
        f['net_return_3m']=np.sin(np.arange(len(f))/40)*.1
        def fake(kind,x,y,test):
            return np.tile(np.quantile(y,[.1,.5,.9]),(len(test),1))
        with patch('scripts.analysis.quantile_challengers.fit_quantiles',side_effect=fake):
            p=run_challengers(f,start='2023-01-01',progress=None)
            changed=f.copy()
            changed.loc[changed.date.ge('2024-01-01'),'net_return_3m']=-.8
            q=run_challengers(changed,start='2023-01-01',progress=None)
        self.assertEqual(p.groupby('candidate').size().nunique(),1)
        self.assertTrue((p.train_last_exit_date<p.fold_start).all())
        valid=p.calibration_last_exit_date.notna()
        self.assertTrue((p.loc[valid,'calibration_last_exit_date']<p.loc[valid,'fold_start']).all())
        fields=['date','candidate','predicted','q10','q90','probability']
        pd.testing.assert_frame_equal(p.loc[p.date.lt('2024-04-01'),fields].reset_index(drop=True),
                                      q.loc[q.date.lt('2024-04-01'),fields].reset_index(drop=True))

    def test_interval_coverage_uses_only_known_outcomes(self):
        p=pd.DataFrame({'actual':[0.,.2,np.nan],'q10':[-.1,-.1,-.1],'q90':[.1,.1,.1],'predicted':[0.,0.,0.]})
        result=interval_metrics(p)
        self.assertEqual(result['rows'],2)
        self.assertEqual(result['coverage'],.5)
        self.assertAlmostEqual(result['mean_width'],.2)


if __name__=='__main__':
    unittest.main()
