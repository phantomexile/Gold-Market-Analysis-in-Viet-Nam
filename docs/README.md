# Tài liệu dự án

Nếu chuẩn bị thuyết trình, bắt đầu tại [00 — Bắt đầu ở đây](presentation/00_BAT_DAU.md).

| Thư mục/tài liệu | Nội dung | Khi nào mở |
|---|---|---|
| [presentation/](presentation/00_BAT_DAU.md) | Thứ tự trình bày, luồng xử lý, mô hình, demo, câu hỏi và bản mã có chú thích | Thuyết trình và đọc mã |
| [reports/](reports/README.md) | Báo cáo học thuật và kết quả từng chiến dịch mô hình | Tra bằng chứng/số liệu |
| [SOURCE_CODE_MAP.md](SOURCE_CODE_MAP.md) | Bản đồ module chi tiết | Tìm hàm triển khai |
| [PIPELINE_GUIDE.md](PIPELINE_GUIDE.md) | Các bước cập nhật dữ liệu | Vận hành pipeline |
| [DATA_DICTIONARY.md](DATA_DICTIONARY.md) | Ý nghĩa các cột dữ liệu | Giải thích biến đầu vào/đầu ra |
| [DATA_INVENTORY_REPORT.md](DATA_INVENTORY_REPORT.md) | Kiểm kê dữ liệu theo thời điểm của báo cáo | Tra phạm vi dữ liệu |
| [modeling.md](modeling.md) | Tài liệu mô hình tổng quát | Đọc bối cảnh nghiên cứu |
| [superpowers/](superpowers/) | Thiết kế và kế hoạch triển khai theo ngày | Tra lịch sử thay đổi |
| [figures/](figures/) | Hình minh họa dùng trong tài liệu | Minh họa sơ đồ/biểu đồ |

Báo cáo có ngày trong tên là kết quả tại thời điểm đó. Cấu hình thực tế phải đọc từ [registry](../data/lake/modeling/active_prediction_model.json), dữ liệu đang hiển thị từ [snapshot](../data/lake/modeling/snapshot_forecasts.csv). Một kết quả nghiên cứu tốt hơn trên lịch sử không tự động trở thành cấu hình vận hành.
