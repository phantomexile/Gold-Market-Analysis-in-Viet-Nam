"""Xuất sơ đồ tiếng Anh rút gọn, chỉ giữ luồng dữ liệu đến dashboard."""

from html import escape
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
W, H, S = 1800, 920, 2
image = Image.new("RGB", (W*S, H*S), "white")
draw = ImageDraw.Draw(image)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<title>Vietnam Gold Market Analysis Pipeline</title>',
       f'<rect width="{W}" height="{H}" fill="white"/>']


def label(x, y, value, size=24, bold=False, color="#263e50"):
    """Căn giữa nhãn, dùng phông Unicode để giữ đúng mọi ký tự khi xuất ảnh."""
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf", size*S)
    draw.text((x*S, y*S), value, fill=color, font=font, anchor="mt")
    svg.append(f'<text x="{x}" y="{y}" font-family="Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" text-anchor="middle" dominant-baseline="text-before-edge" fill="{color}">{escape(value)}</text>')


def box(x, y, w, h, fill, border="#a5bac9", radius=18):
    """Khung màu nhạt nhóm các bước cùng nhiệm vụ để sơ đồ dễ đọc."""
    draw.rounded_rectangle((x*S,y*S,(x+w)*S,(y+h)*S),radius*S,fill, border, 2*S)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{border}" stroke-width="2"/>')


def arrow(x1, y1, x2, y2):
    """Nối các bước theo hướng thực thi, chỉ dùng đoạn ngang hoặc dọc."""
    color = "#5b7b95"
    draw.line((x1*S,y1*S,x2*S,y2*S),fill=color,width=3*S)
    points = [(x2,y2),(x2-13,y2-7),(x2-13,y2+7)] if y1 == y2 else [(x2,y2),(x2-7,y2-13),(x2+7,y2-13)]
    draw.polygon([(x*S,y*S) for x,y in points], fill=color)
    svg.append(f'<path d="M{x1} {y1} L{x2} {y2}" stroke="{color}" stroke-width="3" fill="none"/>')
    svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in points)}" fill="{color}"/>')


def step(x, y, title, subtitle):
    """Mỗi bước chỉ giữ tên hành động và một dòng nội dung chính."""
    box(x, y, 410, 118, "white")
    label(x+205, y+24, title, 25, True)
    label(x+205, y+70, subtitle, 21, color="#607484")


label(900, 48, "VIETNAM GOLD MARKET ANALYSIS", 38, True)
label(900, 108, "Data → Forecast → Decision Support", 25, color="#607484")

# Ba cột giữ bố cục giống mẫu nhưng bỏ hoàn toàn khu vực offline.
groups = [
    (60, "DATA PROCESSING", "#eff6fb", "#9db9ce", [
        ("Collect Data", "SJC · Global gold · FX · Macro · News"),
        ("Clean & Integrate", "Validate prices and align dates"),
        ("Build Features", "Lags · Volatility · Premium · Events")]),
    (660, "FORECASTING", "#f4f1fa", "#b7a7cc", [
        ("Train Models", "Random Forest · Quantile Boosting"),
        ("Generate Forecasts", "1, 3 and 5 calendar months"),
        ("Save Forecast Results", "Net return · Q10 · P(profit)")]),
    (1260, "DECISION SUPPORT", "#edf7f3", "#95b9aa", [
        ("Load Forecast Results", "Latest snapshot by horizon"),
        ("Apply Signal Rules", "P(profit) ≥ 50% and Q10 ≥ −10%"),
        ("Display Dashboard", "Charts · Signals · Key metrics")]),
]
for x, heading, fill, border, steps in groups:
    box(x, 200, 480, 610, fill, border, 22)
    label(x+240, 232, heading, 26, True)
    for y, (title, subtitle) in zip((310, 478, 646), steps):
        step(x+35, y, title, subtitle)
    arrow(x+240,428,x+240,478)
    arrow(x+240,596,x+240,646)

# Mũi tên giữa các cột biểu diễn thứ tự ba giai đoạn chính.
arrow(540,505,660,505)
arrow(1140,505,1260,505)
svg.append("</svg>")
(OUT / "gold-project-pipeline-simple.svg").write_text("\n".join(svg)+"\n", encoding="utf-8")
image.save(OUT / "gold-project-pipeline-simple.png", dpi=(240,240))
print("Created simplified PNG and SVG.")
