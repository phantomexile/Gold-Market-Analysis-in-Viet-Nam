from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_web_data import build_recommendations
from scripts.analysis import run_rolling_paper_trading


class SnapshotRecommendationTests(unittest.TestCase):
    """Kiểm tra khuyến nghị phản ánh đúng tín hiệu của snapshot được cung cấp."""

    def _write_snapshot(self, lake: Path, signals: tuple[bool, bool, bool]) -> None:
        """Tạo ba kỳ hạn tối thiểu để kiểm tra nội dung, không phụ thuộc dữ liệu thật."""
        modeling = lake / "modeling"
        modeling.mkdir(parents=True)
        path = modeling / "snapshot_forecasts.csv"
        fields = [
            "snapshot_date", "horizon_months", "horizon_label", "predicted_net_return",
            "q10_predicted_net_return", "prob_return_positive", "buy_signal",
        ]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for months, label, signal in zip((1, 3, 5), ("1 tháng", "3 tháng", "5 tháng"), signals):
                writer.writerow({
                    "snapshot_date": "2026-10-20",
                    "horizon_months": months,
                    "horizon_label": label,
                    "predicted_net_return": 0.03 if signal else -0.04,
                    "q10_predicted_net_return": -0.04 if signal else -0.12,
                    "prob_return_positive": 0.75 if signal else 0.20,
                    "buy_signal": signal,
                })

    def test_three_month_buy_is_reflected_in_primary_action(self) -> None:
        """Tín hiệu mua kỳ hạn ba tháng phải xuất hiện trong khuyến nghị."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            lake = Path(temp_dir)
            self._write_snapshot(lake, (False, True, False))

            recommendations = build_recommendations(lake)

        self.assertIn("3 THÁNG", recommendations["primary_action"])
        self.assertIn("2026-10-20", recommendations["executive_summary"])
        self.assertNotIn("KHÔNG MỞ VỊ THẾ MUA MỚI ở tất cả", recommendations["executive_summary"])

    def test_no_buy_summary_does_not_claim_fixed_market_values(self) -> None:
        """Lời giải thích chỉ dựa vào snapshot, tránh giá và premium cũ viết cứng."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            lake = Path(temp_dir)
            self._write_snapshot(lake, (False, False, False))

            recommendations = build_recommendations(lake)

        all_text = recommendations["executive_summary"] + " ".join(
            horizon["rationale"] for horizon in recommendations["horizons"]
        )
        self.assertIn("2026-10-20", all_text)
        self.assertNotIn("144 triệu", all_text)
        self.assertNotIn("41 triệu", all_text)
        self.assertNotIn("Premium >40", all_text)


class PaperTradingRefreshTests(unittest.TestCase):
    """Kiểm tra bước ghi tín hiệu mô phỏng sau khi tạo snapshot."""

    def test_build_ledger_and_summary_records_new_open_signal(self) -> None:
        """Tín hiệu mua mới chưa tới ngày thoát phải được ghi là vị thế mở."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            root = Path(temp_dir)
            forecast = root / "forecast.csv"
            prices = root / "prices.csv"
            ledger_path = root / "ledger.csv"
            summary_path = root / "summary.json"
            forecast.write_text(
                "snapshot_date,horizon_months,predicted_net_return,q10_predicted_net_return,prob_return_positive,buy_signal\n"
                "2026-10-20,3,0.03,-0.04,0.75,True\n",
                encoding="utf-8",
            )
            prices.write_text("date,buy,sell\n2026-10-20,139600000,142600000\n", encoding="utf-8")

            ledger, summary = run_rolling_paper_trading.build_ledger_and_summary(
                forecast, prices, ledger_path, summary_path, after="2026-10-20"
            )

            self.assertEqual(ledger.iloc[0]["exit_status"], "open")
            self.assertEqual(summary["open_rows"], 1)
            self.assertTrue(ledger_path.exists())
            self.assertTrue(summary_path.exists())

    def test_exit_target_uses_calendar_months_and_first_available_quote(self) -> None:
        """Ba tháng từ cuối tháng Một đến cuối tháng Tư, rồi chọn báo giá đầu tiên."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            root = Path(temp_dir)
            forecast = root / "forecast.csv"
            prices = root / "prices.csv"
            forecast.write_text(
                "snapshot_date,horizon_months,predicted_net_return,q10_predicted_net_return,prob_return_positive,buy_signal\n"
                "2024-01-31,3,0.03,-0.04,0.75,True\n",
                encoding="utf-8",
            )
            prices.write_text(
                "date,buy,sell\n2024-01-31,99,100\n2024-05-01,110,112\n",
                encoding="utf-8",
            )
            ledger, _ = run_rolling_paper_trading.build_ledger_and_summary(
                forecast, prices, root / "ledger.csv", root / "summary.json", after="2024-01-31"
            )
            self.assertEqual(ledger.iloc[0]["target_exit_date"], "2024-04-30")
            self.assertEqual(ledger.iloc[0]["exit_date"], "2024-05-01")
            self.assertAlmostEqual(ledger.iloc[0]["realized_net_return"], 0.10)


if __name__ == "__main__":
    unittest.main()
