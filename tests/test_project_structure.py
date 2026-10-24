"""Kiểm tra các điểm chạy cũ vẫn hoạt động sau khi tách file theo trách nhiệm."""

from __future__ import annotations

import bootstrap  # noqa: F401

import importlib
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectStructureTests(unittest.TestCase):
    """Bảo vệ import và CLI để người dùng không phải đổi toàn bộ lệnh đã lưu."""

    def test_modeling_modules_keep_legacy_api(self):
        """API cũ phải trỏ tới đúng hàm mới, kể cả hàm tạo nhãn tháng lịch."""
        legacy = importlib.import_module("gold_collectors.modeling.decision_support")
        exports = {
            "config": "ModelingConfig",
            "features": "build_model_frame",
            "targets": "_add_calendar_month_targets",
            "training": "train_baselines",
            "evaluation": "make_walk_forward_splits",
            "reporting": "write_report",
        }
        for module_name, symbol in exports.items():
            with self.subTest(module=module_name):
                module = importlib.import_module(f"gold_collectors.modeling.{module_name}")
                self.assertIs(getattr(legacy, symbol), getattr(module, symbol))

    def test_script_imports_remain_compatible(self):
        """Import lệnh cũ và mới cùng trả một module, tránh hai bản trạng thái riêng."""
        for old, new in (
            ("scripts.pipeline.refresh_event_inputs", "scripts.collection.refresh_event_inputs"),
            ("scripts.pipeline.build_master_panel", "scripts.processing.build_master_panel"),
            ("scripts.pipeline.quality_report", "scripts.reporting.quality_report"),
            ("scripts.pipeline.recover_widest_csv", "scripts.maintenance.recover_widest_csv"),
        ):
            with self.subTest(module=new):
                self.assertIs(importlib.import_module(old), importlib.import_module(new))

    def test_old_and_new_cli_help_match_outside_project_directory(self):
        """Lệnh trực tiếp phải tự tìm thư mục gốc dù chạy từ thư mục tests."""
        old_path = ROOT / "scripts/pipeline/refresh_event_inputs.py"
        new_path = ROOT / "scripts/collection/refresh_event_inputs.py"
        outputs = []
        for path in (old_path, new_path):
            result = subprocess.run(
                [sys.executable, str(path), "--help"], cwd=ROOT / "tests",
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs.append(result.stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_module_cli_still_works(self):
        """Cách chạy Python theo package cũng phải hỗ trợ trợ giúp mà không tải dữ liệu."""
        result = subprocess.run(
            [sys.executable, "-m", "scripts.collection.refresh_event_inputs", "--help"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--help", result.stdout)


if __name__ == "__main__":
    unittest.main()
