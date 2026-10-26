"""Bảo vệ luồng cập nhật trên Windows và phản hồi lỗi cho dashboard."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class WebUpdateTests(unittest.TestCase):
    """Lỗi môi trường phải được báo rõ và không làm mất kết nối với trình duyệt."""

    def test_refresh_steps_write_vietnamese_with_windows_pipe_encoding(self):
        """Cả tiến trình điều phối và script con cần UTF-8 khi stdout là pipe."""
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            script = Path(folder) / "step.py"
            script.write_text("print('Giá vàng cập nhật')\n", encoding="utf-8")
            code = (
                "from pathlib import Path; "
                "from scripts.pipeline.refresh_latest_forecast import run_step; "
                f"run_step(Path({str(script)!r}))"
            )
            result = subprocess.run(
                [sys.executable, "-c", code], cwd=ROOT,
                env={**os.environ, "PYTHONIOENCODING": "cp1252"},
                capture_output=True, encoding="utf-8", errors="replace",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Đang chạy", result.stdout)
        self.assertIn("Giá vàng cập nhật", result.stdout)

    def test_process_start_error_returns_status_instead_of_dropping_connection(self):
        """Tiến trình nền thất bại vẫn lưu lỗi để trình duyệt đọc được."""
        from web.server import RefreshJob
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            job = RefreshJob(Path(folder))
            with patch("web.server.subprocess.Popen", side_effect=OSError("Python unavailable")):
                job.start()
                self._wait(job)
            response = job.snapshot()
        self.assertEqual(response["status"], "warning")
        self.assertIn("Python unavailable", response["log"])

    def _wait(self, job):
        """Chờ có giới hạn để kiểm thử không bị treo nếu tiến trình nền gặp lỗi."""
        deadline = time.monotonic() + 5
        while job.snapshot()["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertNotEqual(job.snapshot()["status"], "running")

    def test_real_process_progress_and_success(self):
        """Chỉ đạt 100% sau khi script báo mốc công việc và thoát thành công."""
        from web.server import RefreshJob
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            script = Path(folder) / "refresh.py"
            script.write_text(
                'print(\'@@UPDATE {"progress": 40, "message": "Đang xử lý"}\', flush=True)\n'
                'print(\'@@UPDATE {"progress": 99, "message": "Đã kiểm tra", "snapshot_date": "2026-10-24"}\', flush=True)\n',
                encoding="utf-8",
            )
            job = RefreshJob(Path(folder), script=script)
            job.start()
            self._wait(job)
            result = job.snapshot()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["progress"], 100)
        self.assertEqual(result["snapshot_date"], "2026-10-24")

    def test_failure_keeps_last_real_progress(self):
        """Lỗi giữa chừng không được lấp đầy thanh tiến trình hoặc báo thành công."""
        from web.server import RefreshJob
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            script = Path(folder) / "refresh.py"
            script.write_text(
                'print(\'@@UPDATE {"progress": 40, "message": "Đang xử lý"}\', flush=True)\n'
                'raise RuntimeError("Nguồn không phản hồi")\n', encoding="utf-8",
            )
            job = RefreshJob(Path(folder), script=script)
            job.start()
            self._wait(job)
            result = job.snapshot()
        self.assertEqual(result["status"], "warning")
        self.assertEqual(result["progress"], 40)
        self.assertIn("Nguồn không phản hồi", result["log"])

    def test_two_tabs_share_one_running_process(self):
        """Hai lần bấm lúc đang chạy phải dùng chung một tiến trình huấn luyện."""
        from web.server import RefreshJob
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            gate = Path(folder) / "continue"
            script = Path(folder) / "refresh.py"
            script.write_text(
                'import time\nfrom pathlib import Path\n'
                f'while not Path({str(gate)!r}).exists(): time.sleep(0.01)\n',
                encoding="utf-8",
            )
            job = RefreshJob(Path(folder), script=script)
            with patch("web.server.subprocess.Popen", wraps=subprocess.Popen) as launch:
                self.assertEqual(job.start()["status"], "running")
                self.assertEqual(job.start()["status"], "running")
                gate.touch()
                self._wait(job)
            self.assertEqual(launch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
