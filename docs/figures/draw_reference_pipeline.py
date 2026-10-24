"""Vẽ sơ đồ dự án theo bố cục ảnh mẫu, xuất PNG và SVG với cùng nội dung."""

from pathlib import Path
from html import escape
import math

from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).resolve().parent
W, H, SCALE = 2000, 1660, 2
INK, MUTED, LINE = "#22384b", "#5c7080", "#587b98"
image = Image.new("RGB", (W * SCALE, H * SCALE), "white")
draw = ImageDraw.Draw(image)
svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="title desc">',
       '<title id="title">Pipeline phân tích thị trường vàng Việt Nam</title>',
       '<desc id="desc">Phần trên là chuẩn bị dữ liệu và đánh giá nghiên cứu. Phần dưới là cập nhật dữ liệu, huấn luyện snapshot, áp quy tắc và hiển thị dashboard.</desc>',
       '<rect width="2000" height="1660" fill="white"/>']


def text(x, y, value, size=23, bold=False, color=INK, center=False):
    """Ghi chữ có dấu bằng Arial; dùng cùng tọa độ cho ảnh và bản vector."""
    font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf", size * SCALE)
    # Neo theo đỉnh chữ để các hàng trong khối không lệch do dấu tiếng Việt.
    draw.text((x * SCALE, y * SCALE), value, font=font, fill=color, anchor="mt" if center else "lt")
    anchor = "middle" if center else "start"
    svg.append(f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}" text-anchor="{anchor}" dominant-baseline="text-before-edge">{escape(value)}</text>')


def rect(x, y, w, h, fill="white", stroke="#a4b6c3", radius=16, width=2):
    """Khung bo góc phân biệt nhóm xử lý với các bước nghiệp vụ bên trong."""
    draw.rounded_rectangle((x*SCALE, y*SCALE, (x+w)*SCALE, (y+h)*SCALE), radius=radius*SCALE, fill=fill, outline=stroke, width=width*SCALE)
    svg.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')


def arrow(points, dashed=False, color=LINE, head=True):
    """Mũi tên liền là luồng xử lý; nét đứt là tái sử dụng dữ liệu hoặc kết quả."""
    for a, b in zip(points, points[1:]):
        if dashed:
            length = math.dist(a, b)
            for start in range(0, int(length), 17):
                end = min(start + 10, length)
                p = tuple((a[i] + (b[i]-a[i])*start/length)*SCALE for i in (0, 1))
                q = tuple((a[i] + (b[i]-a[i])*end/length)*SCALE for i in (0, 1))
                draw.line([p, q], fill=color, width=3*SCALE)
        else:
            draw.line([(a[0]*SCALE, a[1]*SCALE), (b[0]*SCALE, b[1]*SCALE)], fill=color, width=3*SCALE)
    coords = " ".join(f"{x},{y}" for x,y in points)
    dash = ' stroke-dasharray="10 7"' if dashed else ""
    svg.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="3" stroke-linejoin="round"{dash}/>')
    if head:
        a, b = points[-2:]
        angle = math.atan2(b[1]-a[1], b[0]-a[0])
        triangle = [b] + [(b[0]-13*math.cos(angle+s), b[1]-13*math.sin(angle+s)) for s in (-.45,.45)]
        draw.polygon([(x*SCALE,y*SCALE) for x,y in triangle], fill=color)
        svg.append(f'<polygon points="{" ".join(f"{x},{y}" for x,y in triangle)}" fill="{color}"/>')


def node(x, y, w, h, title, lines, fill="white", size=22):
    """Một bước hiển thị tên nhiệm vụ và đầu vào, đầu ra hoặc quy tắc chính."""
    rect(x, y, w, h, fill)
    text(x+w/2, y+20, title, size+2, True, center=True)
    for i, line in enumerate(lines):
        text(x+w/2, y+61+i*32, line, size, center=True)


# Phần nghiên cứu dùng chung dữ liệu nhưng không phải một tác nhân LLM.
text(60, 39, "PIPELINE PHÂN TÍCH THỊ TRƯỜNG VÀNG VIỆT NAM", 38, True)
text(61, 94, "Dữ liệu SJC và yếu tố thị trường → dự báo lợi suất ròng 1, 3, 5 tháng lịch → dashboard", 25, color=MUTED)
rect(50, 165, 1900, 485, "#f7f9fb", "#a5b5c2", 24)
text(80, 190, "OFFLINE — CHUẨN BỊ DỮ LIỆU & ĐÁNH GIÁ NGHIÊN CỨU", 26, True)
node(80, 305, 270, 235, "Nguồn dữ liệu", ["Giá SJC mua / bán", "Vàng thế giới · USD/VND", "Vĩ mô · GPR · tin tức", "Lịch sự kiện · chính sách"], size=21)
node(400, 305, 285, 235, "Thu thập & chuẩn hóa", ["Collector / API → Data Lake", "Chuẩn ngày · đơn vị · giá", "Đối chiếu ngày giao dịch", "Ghép vĩ mô theo ngày có tin"], size=21)
node(740, 270, 310, 130, "Tạo đặc trưng", ["Độ trễ · biến động · premium", "Vĩ mô · sự kiện thị trường"], size=21)
node(740, 445, 310, 130, "Tạo nhãn 1 / 3 / 5 tháng", ["Giá mua khi thoát /", "giá bán khi vào − 1"], size=21)
node(1110, 300, 350, 250, "Huấn luyện & đánh giá", ["Baseline · kinh tế lượng · ML", "Walk-forward theo thời gian", "Sai số · phân vị · quy tắc", "Báo cáo so sánh mô hình"], size=22)
node(1520, 300, 350, 250, "Kho dữ liệu & kết quả", ["Các bảng master / model frame", "Kết quả · dự báo ngoài mẫu", "Tín hiệu nghiên cứu · báo cáo", "CSV · JSON · metadata nguồn"], "#edf5fb", size=21)
arrow([(350,422),(400,422)])
arrow([(685,422),(713,422),(713,335),(740,335)])
arrow([(713,422),(713,510),(740,510)])
arrow([(1050,335),(1080,335),(1080,390),(1110,390)])
arrow([(1050,510),(1080,510),(1080,460),(1110,460)])
arrow([(1460,422),(1520,422)])
text(81, 600, "Nhãn lịch sử: ngày yêu cầu = ngày giao dịch; đủ giá mua và bán hợp lệ. Kỳ hạn dùng phiên SJC đầu tiên từ ngày tròn tháng.", 21, color=MUTED)

# Phần dưới mô tả luồng cập nhật đang tồn tại: mỗi lần cập nhật có huấn luyện lại.
text(65, 735, "CẬP NHẬT SNAPSHOT & PHỤC VỤ DASHBOARD", 27, True)
text(65, 780, "Nút Cập nhật / POST /api/update → refresh_latest_forecast.py", 22, color=MUTED)
rect(70, 850, 540, 555, "#f0f6fb", "#95b1c7", 22)
rect(730, 850, 540, 555, "#f5f2fa", "#b6a6cb", 22)
rect(1390, 850, 540, 555, "#eff8f5", "#8fb5aa", 22)
text(98, 876, "01  LỚP DỮ LIỆU MỚI NHẤT", 24, True)
text(758, 876, "02  LỚP DỰ BÁO SNAPSHOT", 24, True)
text(1418, 876, "03  LỚP QUY TẮC & HIỂN THỊ", 24, True)

node(100, 935, 480, 110, "Cập nhật đầu vào", ["Giá mới · RSS / GPR · dữ liệu nguồn"], size=22)
node(100, 1090, 480, 110, "Dựng lại bảng tham chiếu", ["Global reference → premium SJC"], size=22)
node(100, 1245, 480, 120, "Tạo model frame mới nhất", ["Đặc trưng + nhãn đã có kết quả"], size=22)
arrow([(340,1045),(340,1090)])
arrow([(340,1200),(340,1245)])

node(760, 935, 480, 110, "Huấn luyện từng kỳ hạn", ["Bù thiếu bằng median · chọn ≤120 biến"], size=22)
node(760, 1090, 480, 130, "Random Forest + Quantile GB", ["Dự báo lợi suất ròng · Q10", "Ước lượng P(lợi suất dương)"], size=22)
node(760, 1265, 480, 100, "Lưu snapshot_forecasts.csv", ["1 tháng · 3 tháng · 5 tháng"], size=22)
arrow([(1000,1045),(1000,1090)])
arrow([(1000,1220),(1000,1265)])
arrow([(580,1305),(670,1305),(670,990),(760,990)])
text(622, 1055, "Đầu vào", 19, color=MUTED)

node(1420, 935, 480, 110, "Tích hợp kết quả snapshot", ["Ngày dự báo · kỳ hạn · chỉ số dự báo"], size=22)
node(1420, 1090, 480, 130, "Áp dụng quy tắc tín hiệu", ["P(lãi) ≥ 50% và Q10 ≥ −10%", "Mua tích lũy / Không mua mới"], size=22)
node(1420, 1265, 480, 100, "Diễn giải & xuất JSON", ["Chỉ số · lý do · ngày mục tiêu"], size=22)
arrow([(1660,1045),(1660,1090)])
arrow([(1660,1220),(1660,1265)])
arrow([(1240,1315),(1330,1315),(1330,990),(1420,990)])
text(1285, 1055, "Snapshot", 19, color=MUTED)

# Nét đứt chỉ mối liên hệ dữ liệu và đầu ra phụ, không ngụ ý tự động chốt kiểm định.
arrow([(1695,550),(1695,695),(35,695),(35,825),(340,825),(340,850)], dashed=True)
rect(675, 676, 575, 39, "white", "white", 0, 0)
text(962, 683, "Tái sử dụng Data Lake cho lần cập nhật tiếp theo", 20, color=MUTED, center=True)
node(760, 1460, 480, 100, "Theo dõi paper trading", ["Sổ vị thế mô phỏng · kết quả theo dõi"], "#f7f5fb", size=22)
arrow([(1000,1365),(1000,1460)], dashed=True)
node(1420, 1460, 480, 100, "DASHBOARD THỊ TRƯỜNG VÀNG", ["Biểu đồ · lợi suất · Q10 · tín hiệu"], "#dcefe8", size=22)
arrow([(1660,1365),(1660,1460)])
arrow([(130,1505),(255,1505)], head=True)
text(275, 1491, "Luồng xử lý", 21, color=MUTED)
arrow([(130,1550),(255,1550)], dashed=True)
text(275, 1536, "Dữ liệu / kết quả dùng lại", 21, color=MUTED)
text(65, 1610, "Sơ đồ theo mã nguồn hiện tại · Nhánh đánh giá nghiên cứu tách khỏi nhánh snapshot · Q10 là phân vị 10%, không phải mức lỗ tối đa", 21, color=MUTED)

svg.append("</svg>")
svg_path = OUT / "gold-project-pipeline.svg"
svg_path.write_text("\n".join(svg) + "\n", encoding="utf-8")
image.save(OUT / "gold-project-pipeline.png", dpi=(240, 240))
print(svg_path)
print(OUT / "gold-project-pipeline.png")
