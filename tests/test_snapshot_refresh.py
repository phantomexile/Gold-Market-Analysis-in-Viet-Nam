from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

# Các ca này bảo vệ chế độ kiểm định cũ; chế độ trực tiếp có bộ kiểm thử riêng.
from scripts.build_web_data import _build_validated_recommendations as build_recommendations
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
            "status", "probability_method", "calibration_rows", "validation_protocol_id",
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
                    "status": "validated",
                    "probability_method": "temporal_oos_empirical_laplace",
                    "calibration_rows": 120,
                    "validation_protocol_id": "locked-test-protocol",
                })
        report = {
            "snapshot_date": "2026-10-20", "protocol_id": "locked-test-protocol",
            "horizons": [{"horizon_months": months, "status": "validated", "reasons": [],
                          "checks": {name: True for name in (
                              "inputs_verified", "enough_rows", "enough_time_span", "enough_nonoverlap",
                              "mae_vs_zero", "brier_vs_baseline", "q10_coverage", "q10_pinball_vs_baseline", "probability_calibration",
                          )}} for months in (1, 3, 5)],
        }
        (modeling / "snapshot_validation_report.json").write_text(json.dumps(report), encoding="utf-8")

    def test_three_month_buy_is_reflected_in_primary_action(self) -> None:
        """Tín hiệu mua kỳ hạn ba tháng phải xuất hiện trong khuyến nghị."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            lake = Path(temp_dir)
            self._write_snapshot(lake, (False, True, False))

            recommendations = build_recommendations(lake, expected_snapshot_date="2026-10-20")

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

    def test_unvalidated_or_legacy_snapshot_cannot_recommend_buy(self) -> None:
        """Trạng thái chạy thành công không phải bằng chứng mô hình đã được kiểm định."""
        for status in ("ok", "unvalidated", "validation_failed", ""):
            with self.subTest(status=status), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
                lake = Path(folder)
                self._write_snapshot(lake, (True, True, True))
                path = lake / "modeling" / "snapshot_forecasts.csv"
                with path.open(encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                for row in rows:
                    row["status"] = status
                self._replace_rows(path, rows)
                result = build_recommendations(lake, expected_snapshot_date="2026-10-20")
                self.assertFalse(any(h["buy_signal"] for h in result["horizons"]))
                self.assertEqual(result["primary_signal"], "observe")

    def _replace_rows(self, path: Path, rows: list[dict]) -> None:
        """Ghi tình huống lỗi dưới dạng CSV thật như đầu vào dashboard."""
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def test_inconsistent_or_missing_dates_block_all_horizons(self) -> None:
        """Không được trộn dự báo cũ, kỳ hạn thiếu hoặc khác ngày với giá trên web."""
        for case in ("stale", "unknown_date", "mixed_dates", "missing_horizon", "duplicate_horizon"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
                lake = Path(folder)
                self._write_snapshot(lake, (True, True, True))
                path = lake / "modeling" / "snapshot_forecasts.csv"
                with path.open(encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                expected = "2026-10-21" if case == "stale" else "2026-10-20"
                if case == "unknown_date":
                    expected = None
                elif case == "mixed_dates":
                    rows[-1]["snapshot_date"] = "2026-10-19"
                elif case == "missing_horizon":
                    rows.pop()
                elif case == "duplicate_horizon":
                    rows[-1]["horizon_months"] = "3"
                self._replace_rows(path, rows)
                result = build_recommendations(lake, expected_snapshot_date=expected)
                self.assertEqual(result["primary_signal"], "observe")
                self.assertFalse(any(h["buy_signal"] for h in result["horizons"]))

    def test_invalid_or_uncalibrated_probability_is_not_a_buy_signal(self) -> None:
        """NaN, vô cực, xác suất sai miền và phương pháp cũ đều phải bị chặn."""
        for field, value in (("prob_return_positive", "nan"), ("prob_return_positive", "1.2"),
                             ("predicted_net_return", "inf"), ("q10_predicted_net_return", "nan"),
                             ("probability_method", "in_sample_normal"), ("calibration_rows", "0"),
                             ("prob_return_positive", "0.2"), ("q10_predicted_net_return", "-0.2")):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
                lake = Path(folder)
                self._write_snapshot(lake, (True, True, True))
                path = lake / "modeling" / "snapshot_forecasts.csv"
                with path.open(encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                rows[1][field] = value
                self._replace_rows(path, rows)
                result = build_recommendations(lake, expected_snapshot_date="2026-10-20")
                self.assertFalse(result["horizons"][1]["buy_signal"])
                # JSON trả về vẫn phải hợp lệ dù CSV đầu vào chứa NaN.
                import json
                json.dumps(result, allow_nan=False)

    def test_validated_label_needs_matching_validation_evidence(self) -> None:
        """CSV tự gắn validated không được bật mua khi báo cáo thiếu, khác ngày hoặc không đạt."""
        for case in ("missing", "wrong_date", "wrong_protocol", "failed_check", "incomplete_checks", "malformed"):
            with self.subTest(case=case), tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
                lake = Path(folder)
                self._write_snapshot(lake, (True, True, True))
                path = lake / "modeling" / "snapshot_validation_report.json"
                report = json.loads(path.read_text(encoding="utf-8"))
                if case == "missing":
                    path.unlink()
                elif case == "malformed":
                    path.write_text("[]", encoding="utf-8")
                else:
                    if case == "wrong_date":
                        report["snapshot_date"] = "2026-10-19"
                    elif case == "wrong_protocol":
                        report["protocol_id"] = "another-protocol"
                    elif case == "failed_check":
                        for item in report["horizons"]:
                            item["checks"]["mae_vs_zero"] = False
                    elif case == "incomplete_checks":
                        for item in report["horizons"]:
                            item["checks"] = {"enough_rows": True}
                    path.write_text(json.dumps(report), encoding="utf-8")
                result = build_recommendations(lake, expected_snapshot_date="2026-10-20")
                self.assertEqual(result["primary_signal"], "observe")
                self.assertFalse(any(h["buy_signal"] for h in result["horizons"]))

    def test_historical_pass_never_opens_prospective_buy_gate(self) -> None:
        """Hai mức có số mẫu riêng; đạt lịch sử chỉ được bật tín hiệu mô phỏng nghiên cứu."""
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            lake = Path(folder)
            self._write_snapshot(lake, (True, True, True))
            path = lake / 'modeling' / 'snapshot_forecasts.csv'
            with path.open(encoding='utf-8') as handle:
                rows = list(csv.DictReader(handle))
            for row in rows:
                row['status'] = 'validation_pending'
            self._replace_rows(path, rows)
            path = lake / 'modeling' / 'snapshot_validation_report.json'
            report = json.loads(path.read_text(encoding='utf-8'))
            report['policy'] = {'min_matured_rows': 120, 'min_origin_span_days': 365, 'min_nonoverlapping_windows': 6}
            for detail in report['horizons']:
                detail['status'] = 'validation_pending'
                detail['checks']['enough_rows'] = False
                detail['metrics'] = {'matured_rows': 12, 'nonoverlapping_windows': 1, 'origin_span_days': 30}
            path.write_text(json.dumps(report), encoding='utf-8')
            history = {'snapshot_date': '2026-10-20', 'protocol_id': 'locked-test-protocol',
                       'evaluation_kind': 'historical_screening', 'independent_validation': False,
                       'horizons': [{'horizon_months': horizon, 'status': 'historical_passed', 'reasons': [],
                                     'metrics': {'matured_rows': 120, 'mae': 0.02, 'zero_baseline_mae': 0.04}}
                                    for horizon in (1, 3, 5)]}
            for detail in history['horizons']:
                detail['checks'] = {name: True for name in report['horizons'][0]['checks']}
            history_path = lake/'modeling'/'snapshot_historical_report.json'
            history_path.write_text(json.dumps(history), encoding='utf-8')
            result = build_recommendations(lake, expected_snapshot_date='2026-10-20')
            self.assertEqual(result['primary_signal'], 'observe')
            for horizon in result['horizons']:
                self.assertFalse(horizon['buy_signal'])
                self.assertTrue(horizon['simulation_buy_signal'])
                self.assertEqual(horizon['historical']['status'], 'historical_passed')
                self.assertEqual(horizon['prospective']['status'], 'validation_pending')
                self.assertEqual(horizon['prospective']['metrics']['matured_rows'], 12)
            history['snapshot_date'] = '2026-10-19'
            history_path.write_text(json.dumps(history), encoding='utf-8')
            stale = build_recommendations(lake, expected_snapshot_date='2026-10-20')
            self.assertTrue(all(h['historical']['status'] == 'historical_insufficient' for h in stale['horizons']))
            self.assertFalse(any(h['simulation_buy_signal'] for h in stale['horizons']))


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
