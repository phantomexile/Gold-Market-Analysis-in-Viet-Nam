"""Giữ lệnh RF ba kỳ hạn nhưng dùng lựa chọn mô hình có đối chứng baseline."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT, ROOT/'src'):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from scripts.analysis.run_forecast_repair import main as run_repair


def main():
    """Chuyển tiếp CLI cũ, giữ --output nhưng không còn ép RF lên cả ba kỳ hạn.

    Lệnh sửa mới dựng lại premium và so sánh RF trung vị với RF cũ và zero.
    Baseline chỉ dùng đối chứng. ML chưa có lợi thế ổn định vẫn giữ dự báo
    riêng từng kỳ hạn với nhãn thử nghiệm, không tự nhận đã cải thiện.
    """
    run_repair()


if __name__ == '__main__':
    main()
