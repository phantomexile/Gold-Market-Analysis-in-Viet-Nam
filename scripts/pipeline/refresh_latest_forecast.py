#!/usr/bin/env python3
"""Cập nhật dữ liệu và tạo lại dự báo 1/3/5 tháng lịch cho dashboard."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"


def run_step(script: Path, *arguments: str) -> None:
    """Chạy một bước từ thư mục dự án và dừng ngay nếu bước đó thất bại."""
    print(f"Đang chạy {script.relative_to(ROOT)} {' '.join(arguments)}", flush=True)
    subprocess.run([sys.executable, str(script), *arguments], cwd=ROOT, check=True)


def refresh(*, to_date: str | None = None, skip_collect: bool = False) -> str:
    """Nối các bước giá và sự kiện để model đọc cùng bộ đầu vào mới nhất."""
    if not skip_collect:
        arguments = ["--to", to_date] if to_date else []
        run_step(ROOT / "scripts" / "pipeline" / "update_incremental.py", *arguments)
        # Tin RSS và GPR có ngày nguồn riêng; lỗi tải phải dừng luồng để tránh
        # dashboard báo đã cập nhật khi thực tế chỉ có giá vàng được làm mới.
        run_step(ROOT / "scripts" / "collection" / "refresh_event_inputs.py")

    # Bảng global chuẩn phải được dựng lại trước khi tính premium và đặc trưng.
    run_step(ROOT / "scripts" / "processing" / "build_master_panel.py", "--tables", "global_reference_daily")
    global_panel = LAKE / "global_reference_daily.csv"
    if not global_panel.exists():
        raise FileNotFoundError(global_panel)
    # Builder ghi tên chuẩn; model hiện đọc tên pipeline_output vì tương thích
    # với data lake cũ. Sao chép từ bản vừa dựng sang tên tương thích đó.
    shutil.copyfile(global_panel, LAKE / "pipeline_output_global_reference.csv")

    # Giữ metadata về nguồn proxy và độ trễ khi ghép vàng thế giới với SJC.
    run_step(ROOT / "scripts" / "processing" / "improve_premium_coverage.py")
    run_step(ROOT / "scripts" / "analysis" / "train_latest_snapshot.py")

    snapshot = pd.read_csv(LAKE / "modeling" / "snapshot_forecasts.csv")
    frame = pd.read_csv(LAKE / "modeling" / "model_frame_daily.csv", usecols=["date"])
    dashboard = json.loads((ROOT / "web" / "data" / "gold_dashboard_data.json").read_text(encoding="utf-8"))
    snapshot_date = str(snapshot["snapshot_date"].iloc[0])
    # Chỉ báo thành công khi cả model, dữ liệu SJC và dashboard cùng một ngày.
    if snapshot["horizon_months"].tolist() != [1, 3, 5]:
        raise ValueError("Snapshot không có đủ kỳ hạn 1, 3 và 5 tháng lịch.")
    if snapshot_date != str(frame["date"].iloc[-1]) or snapshot_date != dashboard["summary"]["end_date"]:
        raise ValueError("Ngày snapshot, model frame và dashboard không khớp.")
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
