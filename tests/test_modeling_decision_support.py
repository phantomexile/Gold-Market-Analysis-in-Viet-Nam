from __future__ import annotations

import bootstrap  # noqa: F401

import unittest
from pathlib import Path

import pandas as pd

from gold_collectors.modeling.decision_support import LUONG_PER_OZ, ModelingConfig, _add_calendar_month_targets, build_model_frame, make_walk_forward_splits, train_baselines


class ModelingDecisionSupportTests(unittest.TestCase):
    def test_luong_conversion_constant_matches_documented_formula(self):
        """Kiểm tra bằng khối lượng chuẩn, không chép lại công thức của builder."""
        expected = 31.1034768 / 37.5
        self.assertAlmostEqual(LUONG_PER_OZ, expected, places=10)
        self.assertGreater(LUONG_PER_OZ, 0.82)
        self.assertLess(LUONG_PER_OZ, 0.84)

    def test_walk_forward_splits_are_chronological_and_non_overlapping(self):
        dates = pd.date_range("2011-07-06", "2026-07-11", freq="D").to_series()
        splits = make_walk_forward_splits(dates, initial_train_end="2022-12-31", final_test_end="2026-07-11")
        self.assertTrue(splits)
        previous_test_end = None
        for split in splits:
            self.assertLessEqual(split["train_start"], split["train_end"])
            self.assertLess(split["train_end"], split["test_start"])
            self.assertLessEqual(split["test_start"], split["test_end"])
            if previous_test_end is not None:
                self.assertEqual(split["train_end"], previous_test_end)
            previous_test_end = split["test_end"]

    def test_calendar_month_target_uses_first_quote_on_or_after_anniversary(self):
        """Ngày cuối tháng và ngày thiếu báo giá vẫn phải chọn đúng phiên thoát."""
        df = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-31", "2024-02-28", "2024-03-01", "2024-04-30", "2024-06-30"]),
                "sell_price": [100.0, 105.0, 110.0, 120.0, 130.0],
                "buy_price": [99.0, 103.0, 108.0, 117.0, 126.0],
            }
        )
        labeled = _add_calendar_month_targets(df, (1, 3, 5))
        self.assertEqual(labeled.loc[0, "target_date_1m"], pd.Timestamp("2024-02-29"))
        self.assertEqual(labeled.loc[0, "exit_date_1m"], pd.Timestamp("2024-03-01"))
        self.assertAlmostEqual(labeled.loc[0, "net_return_1m"], 108.0 / 100.0 - 1)
        self.assertEqual(labeled.loc[0, "exit_date_3m"], pd.Timestamp("2024-04-30"))
        self.assertEqual(labeled.loc[0, "exit_date_5m"], pd.Timestamp("2024-06-30"))
        self.assertTrue(pd.isna(labeled.loc[4, "net_return_1m"]))

    def test_walk_forward_training_excludes_labels_realized_after_fold_end(self):
        """Fold không được học lợi suất của giao dịch chỉ thoát trong kỳ kiểm tra."""
        frame = pd.DataFrame({
            "date": pd.to_datetime(["2023-10-01", "2023-12-01", "2024-01-01"]),
            "exit_date_1m": pd.to_datetime(["2023-11-01", "2024-01-01", "2024-02-01"]),
            "net_return_1m": [0.10, 0.90, 0.20],
        })
        config = ModelingConfig(horizons=(1,), initial_train_end="2023-12-31", test_end="2024-12-31")
        _, predictions = train_baselines(frame, config)
        mean_row = predictions[predictions["model"].eq("historical_mean_return")].iloc[0]
        self.assertAlmostEqual(mean_row["predicted_net_return"], 0.10)

    def test_local_model_frame_respects_asof_guards(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / "data" / "lake" / "gold_quotes_sjc_historical.csv").exists():
            self.skipTest("local data lake is not available")
        frame = build_model_frame(ModelingConfig(data_lake=root / "data" / "lake"))
        self.assertTrue((frame["global_feature_date"].dropna() <= frame.loc[frame["global_feature_date"].notna(), "date"]).all())
        self.assertTrue((frame["gpr_feature_date"].dropna() <= frame.loc[frame["gpr_feature_date"].notna(), "date"]).all())
        self.assertTrue((frame["macro_feature_date"].dropna() <= frame.loc[frame["macro_feature_date"].notna(), "date"]).all())
        for horizon in (1, 3, 5):
            self.assertIn(f"net_return_{horizon}m", frame.columns)
            self.assertGreater(frame[f"net_return_{horizon}m"].notna().sum(), 1000)
            # Dòng mới nhất chưa tới ngày thoát, vì vậy không được có nhãn tương lai.
            latest = frame.iloc[-1]
            self.assertEqual(latest[f"target_date_{horizon}m"], latest["date"] + pd.DateOffset(months=horizon))
            self.assertTrue(pd.isna(latest[f"net_return_{horizon}m"]))


if __name__ == "__main__":
    unittest.main()
