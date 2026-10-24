#!/usr/bin/env python3
"""Tạo ba hình tiếng Anh cho phần kết quả của báo cáo nghiên cứu Google Docs."""

# Tìm thư mục dự án khi chạy trực tiếp; các nhóm script đều nằm cùng độ sâu.
import sys as _sys
from pathlib import Path as _Path

if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from scripts._bootstrap import bootstrap as _bootstrap_project

_bootstrap_project()


from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "reports" / "figures"
BLUE = "#24527A"
TEAL = "#20A39E"
ORANGE = "#E8873A"
GRAY = "#607080"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Dùng phông chữ phổ biến để hình được hiển thị ổn định trong Google Docs."""
    name = "arialbd.ttf" if bold else "arial.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def canvas(title: str, subtitle: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    """Giữ cùng kích thước và thứ bậc chữ cho các hình có thể so sánh với nhau."""
    image = Image.new("RGB", (1400, 720), "white")
    draw = ImageDraw.Draw(image)
    draw.text((80, 55), title, font=font(34, True), fill=BLUE)
    draw.text((80, 112), subtitle, font=font(21), fill=GRAY)
    draw.line((80, 650, 1320, 650), fill="#D6DEE5", width=2)
    return image, draw


def snapshot() -> None:
    """Vẽ dự báo hiện hành và phân vị q10; độ dài thanh là độ lớn của giá trị âm."""
    image, draw = canvas("Latest snapshot: predicted net returns", "6 October 2026 | Percent after the quoted spread")
    values = [("21 observations", -4.29, -5.41), ("63 observations", -4.06, -5.83), ("105 observations", -11.15, -13.27)]
    for i, (label, mean, q10) in enumerate(values):
        y = 205 + i * 145
        draw.text((80, y + 18), label, font=font(22, True), fill=BLUE)
        for offset, value, color, name in [(0, mean, TEAL, "Point forecast"), (48, q10, ORANGE, "10th percentile")]:
            end = 310 + abs(value) * 58
            draw.rounded_rectangle((310, y + offset, end, y + offset + 31), radius=7, fill=color)
            draw.text((end + 14, y + offset + 1), f"{name}: {value:.2f}%", font=font(20), fill=BLUE)
    draw.text((80, 668), "All three forecasts are negative; future realised returns are not yet observed.", font=font(18), fill=GRAY)
    image.save(OUT / "report4_snapshot_en.png")


def comparison() -> None:
    """Chỉ so sánh baseline và LightGBM vì hai mô hình có cùng số ngày kiểm tra."""
    image, draw = canvas("Historical test MAE by horizon", "July 2026 walk-forward artifact | Percentage points of return")
    draw.rectangle((80, 150, 110, 180), fill=BLUE)
    draw.text((125, 151), "Historical mean", font=font(20), fill=BLUE)
    draw.rectangle((410, 150, 440, 180), fill=TEAL)
    draw.text((455, 151), "LightGBM", font=font(20), fill=BLUE)
    for i, (h, baseline, lightgbm) in enumerate([(21, 3.99, 10.15), (63, 11.00, 15.71), (105, 17.03, 11.00)]):
        x = 290 + 390 * i
        for dx, value, color in [(-80, baseline, BLUE), (20, lightgbm, TEAL)]:
            top = 590 - value * 20
            draw.rectangle((x + dx, top, x + dx + 70, 590), fill=color)
            draw.text((x + dx - 5, top - 32), f"{value:.2f}", font=font(21), fill=BLUE)
        draw.text((x - 25, 603), f"{h} observations", font=font(20), fill=BLUE)
    draw.line((120, 590, 1270, 590), fill=GRAY, width=2)
    image.save(OUT / "report4_test_mae_en.png")


def signal_rate() -> None:
    """Biểu diễn tỷ lệ bật tín hiệu để thấy chân trời 105 dòng thiếu tính chọn lọc."""
    image, draw = canvas("Historical buy-signal frequency", "July 2026 default decision rule | Percent of evaluated dates")
    draw.rectangle((80, 150, 110, 180), fill=BLUE)
    draw.text((125, 151), "Validation", font=font(20), fill=BLUE)
    draw.rectangle((300, 150, 330, 180), fill=ORANGE)
    draw.text((345, 151), "Test", font=font(20), fill=BLUE)
    for i, (h, validation, test) in enumerate([(21, 0.0, 4.9), (63, 38.7, 30.2), (105, 50.1, 99.3)]):
        x = 290 + 390 * i
        for dx, value, color in [(-80, validation, BLUE), (20, test, ORANGE)]:
            top = 590 - value * 4
            draw.rectangle((x + dx, top, x + dx + 70, 590), fill=color)
            draw.text((x + dx - 5, top - 32), f"{value:.1f}", font=font(21), fill=BLUE)
        draw.text((x - 25, 603), f"{h} observations", font=font(20), fill=BLUE)
    draw.line((120, 590, 1270, 590), fill=GRAY, width=2)
    image.save(OUT / "report4_signal_rate_en.png")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    snapshot()
    comparison()
    signal_rate()
