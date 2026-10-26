#!/usr/bin/env python3
"""Cập nhật dữ liệu và tạo lại dự báo 1/3/5 tháng lịch cho dashboard."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"

# Windows có thể dùng cp1252 khi server thu stdout qua pipe. Nhật ký tiếng Việt
# phải giữ UTF-8 ở cả tiến trình này và mọi script con, nếu không luồng sẽ dừng
# ngay trước bước thu thập dù dữ liệu nguồn vẫn truy cập được.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8")


def run_step(script: Path, *arguments: str) -> None:
    """Chạy một bước từ thư mục dự án và dừng ngay nếu bước đó thất bại."""
    print(f"Đang chạy {script.relative_to(ROOT)} {' '.join(arguments)}", flush=True)
    subprocess.run(
        [sys.executable, str(script), *arguments], cwd=ROOT, check=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def report_progress(progress: int, message: str, **details) -> None:
    """Xuất mốc công việc có cấu trúc để server đọc mà không đoán từ thời gian chạy."""
    print("@@UPDATE " + json.dumps({"progress": progress, "message": message, **details}, ensure_ascii=False), flush=True)


def refresh(*, to_date: str | None = None, skip_collect: bool = False) -> str:
    """Nối các bước giá và sự kiện để model đọc cùng bộ đầu vào mới nhất."""
    if not skip_collect:
        arguments = ["--to", to_date] if to_date else []
        report_progress(3, "Đang thu thập giá vàng SJC và dữ liệu thị trường…")
        run_step(ROOT / "scripts" / "pipeline" / "update_incremental.py", *arguments)
        # Tin RSS và GPR có ngày nguồn riêng; lỗi tải phải dừng luồng để tránh
        # dashboard báo đã cập nhật khi thực tế chỉ có giá vàng được làm mới.
        report_progress(18, "Đang cập nhật tin tức và chỉ số GPR…")
        run_step(ROOT / "scripts" / "collection" / "refresh_event_inputs.py")

    # Bảng global chuẩn phải được dựng lại trước khi tính premium và đặc trưng.
    report_progress(32, "Đang xử lý dữ liệu tham chiếu quốc tế…")
    run_step(ROOT / "scripts" / "processing" / "build_master_panel.py", "--tables", "global_reference_daily")
    global_panel = LAKE / "global_reference_daily.csv"
    if not global_panel.exists():
        raise FileNotFoundError(global_panel)
    # Builder ghi tên chuẩn; model hiện đọc tên pipeline_output vì tương thích
    # với data lake cũ. Sao chép từ bản vừa dựng sang tên tương thích đó.
    shutil.copyfile(global_panel, LAKE / "pipeline_output_global_reference.csv")

    # Giữ metadata về nguồn proxy và độ trễ khi ghép vàng thế giới với SJC.
    report_progress(42, "Đang tính chênh lệch giá vàng trong nước và thế giới…")
    run_step(ROOT / "scripts" / "processing" / "improve_premium_coverage.py")
    report_progress(50, "Đang chuẩn bị dữ liệu huấn luyện mô hình…")
    run_step(ROOT / "scripts" / "analysis" / "train_latest_snapshot.py")

    # Ứng viên nghiên cứu đã khóa được theo dõi riêng sau mỗi lần cập nhật.
    # Không có bản khóa thì bỏ qua; lỗi nhật ký/mã thay đổi phải lộ ra để
    # người dùng biết bằng chứng mới chưa được ghi, không tự hợp thức hóa.
    if (LAKE / 'modeling' / 'stationary_shadow' / 'active.json').exists():
        report_progress(96, 'Đang ghi dự báo thử nghiệm của mô hình cải tiến…')
        run_step(ROOT / 'scripts' / 'analysis' / 'run_stationary_research.py', '--record-only')

    report_progress(98, "Đang kiểm tra snapshot và dữ liệu dashboard…")
    snapshot = pd.read_csv(LAKE / "modeling" / "snapshot_forecasts.csv")
    frame = pd.read_csv(LAKE / "modeling" / "model_frame_daily.csv", usecols=["date"])
    dashboard = json.loads((ROOT / "web" / "data" / "gold_dashboard_data.json").read_text(encoding="utf-8"))
    snapshot_date = str(snapshot["snapshot_date"].iloc[0])
    # Chỉ báo thành công khi cả model, dữ liệu SJC và dashboard cùng một ngày.
    if snapshot["horizon_months"].tolist() != [1, 3, 5]:
        raise ValueError("Snapshot không có đủ kỳ hạn 1, 3 và 5 tháng lịch.")
    if snapshot_date != str(frame["date"].iloc[-1]) or snapshot_date != dashboard["summary"]["end_date"]:
        raise ValueError("Ngày snapshot, model frame và dashboard không khớp.")
    report_progress(99, "Đã kiểm tra dữ liệu và dự báo mới.", snapshot_date=snapshot_date)
    return snapshot_date


def main() -> int:
    parser = argparse.ArgumentParser(description="Cập nhật dữ liệu và dự báo vàng theo tháng lịch.")
    parser.add_argument("--to", dest="to_date", help="Ngày cuối cần thu thập, định dạng YYYY-MM-DD.")
    parser.add_argument("--skip-collect", action="store_true", help="Dùng dữ liệu lake hiện có để dựng lại model.")
    args = parser.parse_args()
    print(f"Đã cập nhật snapshot {refresh(to_date=args.to_date, skip_collect=args.skip_collect)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
