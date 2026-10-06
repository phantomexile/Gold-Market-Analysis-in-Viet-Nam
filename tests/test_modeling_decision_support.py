from __future__ import annotations

import bootstrap  # noqa: F401

import unittest
from pathlib import Path

import pandas as pd

from gold_collectors.modeling.decision_support import LUONG_PER_OZ, ModelingConfig, build_model_frame, make_walk_forward_splits


class ModelingDecisionSupportTests(unittest.TestCase):
    def test_luong_conversion_constant_matches_documented_formula(self):
        expected = (31.1034768 / 1.205) / 37.5
        self.assertAlmostEqual(LUONG_PER_OZ, expected, places=10)
        self.assertGreater(LUONG_PER_OZ, 0.68)
        self.assertLess(LUONG_PER_OZ, 0.70)

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

    def test_horizon_target_uses_future_buy_over_current_sell(self):
        df = pd.DataFrame(
            {
                "sell_price": [100.0, 110.0, 120.0],
                "buy_price": [99.0, 108.0, 117.0],
            }
        )
        label = df["buy_price"].shift(-1) / df["sell_price"] - 1
        self.assertAlmostEqual(label.iloc[0], 0.08)
        self.assertAlmostEqual(label.iloc[1], 117.0 / 110.0 - 1)

    def test_local_model_frame_respects_asof_guards(self):
        root = Path(__file__).resolve().parents[1]
        if not (root / "data" / "lake" / "gold_quotes_sjc_historical.csv").exists():
            self.skipTest("local data lake is not available")
        frame = build_model_frame(ModelingConfig(data_lake=root / "data" / "lake"))
        self.assertTrue((frame["global_feature_date"].dropna() <= frame.loc[frame["global_feature_date"].notna(), "date"]).all())
        self.assertTrue((frame["gpr_feature_date"].dropna() <= frame.loc[frame["gpr_feature_date"].notna(), "date"]).all())
        self.assertTrue((frame["macro_feature_date"].dropna() <= frame.loc[frame["macro_feature_date"].notna(), "date"]).all())
        for horizon in (21, 63, 105):
            self.assertIn(f"net_return_{horizon}d", frame.columns)
            self.assertGreater(frame[f"net_return_{horizon}d"].notna().sum(), 1000)


if __name__ == "__main__":
    unittest.main()
