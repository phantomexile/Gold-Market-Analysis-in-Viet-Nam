#!/usr/bin/env python3
"""
Lightweight Web Server for VN Gold Intelligence Terminal.
Serves static dashboard files and provides /api/data and /api/update endpoints.

Usage:
    python web/server.py
    python web/server.py --port 8080
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class RefreshJob:
    """Giữ một lượt cập nhật chung để nhiều tab cùng theo dõi, tránh chạy trùng model."""

    def __init__(self, root: Path, *, script: Path | None = None):
        self.root = root
        self.script = script or root / "scripts" / "pipeline" / "refresh_latest_forecast.py"
        self.lock = threading.Lock()
        self.state = {"status": "idle", "progress": 0, "message": "", "snapshot_date": None}
        self.started_at = None
        self.finished_at = None
        # Chỉ giữ nhật ký cuối để việc hỏi tiến trình không tích lũy bộ nhớ vô hạn.
        self.log = deque(maxlen=30)

    def snapshot(self) -> dict:
        """Trả bản sao trạng thái; thời gian đã chạy không được dùng để tự tăng phần trăm."""
        with self.lock:
            elapsed = (self.finished_at or time.monotonic()) - self.started_at if self.started_at else 0
            return {**self.state, "elapsed_seconds": int(elapsed), "log": "".join(self.log)[-1000:]}

    def start(self) -> dict:
        """Nhận yêu cầu ngay; nếu đã chạy thì trả cùng lượt cập nhật thay vì tạo lượt mới."""
        with self.lock:
            if self.state["status"] != "running":
                self.state = {"status": "running", "progress": 0, "message": "Đang khởi động cập nhật…", "snapshot_date": None}
                self.started_at = time.monotonic()
                self.finished_at = None
                self.log.clear()
                threading.Thread(target=self._run, daemon=True).start()
        return self.snapshot()

    def _run(self) -> None:
        """Đọc từng mốc từ pipeline; chỉ báo hoàn tất sau khi toàn bộ lệnh thoát thành công."""
        success = False
        try:
            # Lưu trọn nhật ký tại máy để tra được nguyên nhân gốc, kể cả khi
            # traceback của tiến trình điều phối dài hơn phần trả cho trình duyệt.
            log_path = self.root / ".cache" / "dashboard-update.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # Tắt đệm stdout để mốc huấn luyện xuất hiện ngay trên web. Giữ UTF-8
            # xuyên suốt tiến trình con để không tái phát lỗi tiếng Việt trên Windows.
            with log_path.open("w", encoding="utf-8") as output, subprocess.Popen(
                [sys.executable, str(self.script)], cwd=self.root,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                encoding="utf-8", errors="replace",
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
            ) as process:
                for line in process.stdout:
                    output.write(line)
                    output.flush()
                    with self.lock:
                        self.log.append(line)
                        if line.startswith("@@UPDATE "):
                            try:
                                event = json.loads(line[len("@@UPDATE "):])
                                # 100% dành riêng cho kết quả cuối, sau kiểm tra ngày snapshot.
                                progress = min(99, max(self.state["progress"], int(event["progress"])))
                                self.state.update(progress=progress, message=str(event["message"]))
                                if event.get("snapshot_date"):
                                    self.state["snapshot_date"] = str(event["snapshot_date"])
                            except (ValueError, KeyError, TypeError):
                                pass  # Nhật ký không hợp lệ không được làm ngắt pipeline đang chạy.
                success = process.wait() == 0
        except Exception as exc:
            # Lỗi khởi chạy/đọc tiến trình cũng phải được trả về cho trình duyệt.
            with self.lock:
                self.log.append(str(exc))
        finally:
            with self.lock:
                self.finished_at = time.monotonic()
                self.state["status"] = "ok" if success else "warning"
                self.state["message"] = (
                    "Đã cập nhật dữ liệu và dự báo 1, 3, 5 tháng!" if success
                    else "Không thể cập nhật đầy đủ dự báo"
                )
                if success:
                    self.state["progress"] = 100


UPDATE_JOB = RefreshJob(Path(__file__).resolve().parent.parent)


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        web_dir = Path(__file__).resolve().parent
        super().__init__(*args, directory=str(web_dir), **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            self.serve_api_data()
        elif self.path == "/api/update/status":
            self.send_json(UPDATE_JOB.snapshot())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/api/update":
            self.handle_api_update()
        else:
            self.send_error(404, "Endpoint not found")

    def serve_api_data(self):
        data_file = Path(__file__).resolve().parent / "data" / "gold_dashboard_data.json"
        if not data_file.exists():
            # Trigger build if file not present
            root = Path(__file__).resolve().parent.parent
            subprocess.run([sys.executable, str(root / "scripts" / "build_web_data.py")], check=False)

        if data_file.exists():
            content = data_file.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_error(500, "Dataset not generated yet")

    def handle_api_update(self):
        """HTTP 202 chỉ xác nhận đã nhận việc; kết quả thật nằm ở API tiến trình."""
        self.send_json(UPDATE_JOB.start(), status=202)

    def send_json(self, payload: dict, *, status: int = 200):
        """Không cache trạng thái để thanh tiến trình luôn phản ánh lượt đang chạy."""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Start VN Gold Terminal Web Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP (default: 127.0.0.1)")
    args = parser.parse_args()

    # Ensure dataset is generated
    data_file = Path(__file__).resolve().parent / "data" / "gold_dashboard_data.json"
    if not data_file.exists():
        root = Path(__file__).resolve().parent.parent
        subprocess.run([sys.executable, str(root / "scripts" / "build_web_data.py")], check=False)

    server_address = (args.host, args.port)
    httpd = http.server.ThreadingHTTPServer(server_address, DashboardHandler)
    url = f"http://{args.host}:{args.port}"

    print("=" * 65)
    print(" [TERMINAL] VN GOLD INTELLIGENCE TERMINAL - LOCAL SERVER")
    print("=" * 65)
    print(f" Dashboard URL: {url}")
    print(f" Directory:     {Path(__file__).resolve().parent}")
    print(" Press Ctrl+C to stop.")
    print("=" * 65)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
