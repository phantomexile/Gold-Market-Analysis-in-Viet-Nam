# 04 — Các bước demo

## Chuẩn bị

Từ thư mục gốc, dùng môi trường Python đã cài các nhóm phụ thuộc trong README. Mở web bằng:

```powershell
python web/server.py --host 127.0.0.1 --port 8000
```

Sau khi server báo khởi động, mở [dashboard trên máy](http://127.0.0.1:8000). Lệnh mở web dùng JSON đã có; nếu JSON chưa tồn tại, server sẽ thử dựng lại. Nhánh dựng JSON có thể fit lại RF theo bản khóa và ghi tệp theo dõi mô hình, vì vậy nên kiểm tra tệp trước buổi demo; không coi thao tác này luôn là chỉ đọc.

## Trình bày trong 3–4 phút

| Hành động trên màn hình | Nội dung nói |
|---|---|
| Mở README và thư mục presentation | Dự án chia thu thập, xử lý, mô hình, kiểm định và giao diện |
| Mở dashboard, chỉ ngày dữ liệu | Đây là snapshot ngày đang hiển thị, không mặc định là dữ liệu hôm nay |
| Chỉ giá mua và giá bán | Nhà đầu tư mua theo giá bán của cửa hàng và thoát theo giá mua lại |
| Mở dự báo 1/3/5 tháng | Ba mục tiêu tháng lịch riêng, dùng RF trung vị ở 1 tháng và RF nhỏ ở 3/5 tháng theo registry |
| Chỉ status và P(lãi)/Q10 | Dự báo điểm và độ tin cậy kiểm định là hai phần riêng; ô thiếu không có nghĩa xác suất bằng 0 |
| Mở 01_targets.py và 03_stationary_research.py trong thư mục code | Giải thích công thức lợi suất và điều kiện nhãn phải đáo hạn trước fold |
| Mở một báo cáo có ngày | Đây là bằng chứng lịch sử, không tự động là cấu hình hiện hành |

## Nếu cần minh họa cập nhật

Nút **Cập nhật** khởi động công việc thật, có tải dữ liệu và dựng lại đầu ra. Chỉ bấm khi muốn thực hiện lượt cập nhật và có đủ thời gian; không cần bấm để demo việc đọc snapshot.

`POST /api/update` trả 202 khi nhận việc. Giao diện hỏi `GET /api/update/status`; `running` nghĩa là đang chạy, `ok` là hoàn tất và `warning` cần xem lỗi. Không nói HTTP 202 hay thanh tiến trình đã chạy đồng nghĩa dữ liệu mới đã sẵn sàng.

Mã điều phối: [05 — Pipeline có chú thích](code/05_refresh_pipeline.py). Mã server đã chú thích trực tiếp tại [web/server.py](../../web/server.py). Nhật ký lỗi đầy đủ lưu tại `.cache/dashboard-update.log`.

Các script `run_forecast_repair.py` và kích hoạt mô hình có thể ghi lại registry/snapshot. Chúng thuộc quy trình nghiên cứu/vận hành, không phải bước cần chạy để chỉ trình bày giao diện.
