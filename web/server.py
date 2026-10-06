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
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        web_dir = Path(__file__).resolve().parent
        super().__init__(*args, directory=str(web_dir), **kwargs)

    def do_GET(self):
        if self.path == "/api/data":
            self.serve_api_data()
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
        root = Path(__file__).resolve().parent.parent
        print("[API] Running incremental data update...")

        # 1. Run incremental update
        res1 = subprocess.run(
            [sys.executable, str(root / "scripts" / "pipeline" / "update_incremental.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        # 2. Rebuild dashboard JSON bundle
        res2 = subprocess.run(
            [sys.executable, str(root / "scripts" / "build_web_data.py")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        success = res1.returncode == 0 and res2.returncode == 0
        response_payload = {
            "status": "ok" if success else "warning",
            "message": "Dữ liệu thị trường vàng đã được cập nhật thành công!" if success else "Cập nhật hoàn tất với cảnh báo",
            "log": res1.stdout[-300:] if res1.stdout else "",
        }

        body = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
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
