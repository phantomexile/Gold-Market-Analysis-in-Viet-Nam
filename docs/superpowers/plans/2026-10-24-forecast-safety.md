# Sửa an toàn khuyến nghị và xác suất lãi

> Thực hiện trực tiếp theo yêu cầu xử lý mục 1 và 2; không commit.

**Mục tiêu:** Chặn khuyến nghị chưa kiểm định hoặc lệch ngày, thay sai số trong mẫu bằng sai số dự báo theo thời gian ngoài mẫu.

**Phạm vi:** Giữ luồng thu thập, nội dung tiếng Việt hiện có và các thay đổi đang có trong workspace. Không sửa dữ liệu tin hồi cứu hoặc thuật toán đóng sổ giao dịch.

**Thiết kế:** Dashboard yêu cầu đủ ba kỳ hạn, cùng ngày dữ liệu, trạng thái `validated`, phương pháp xác suất ngoài mẫu và số liệu hữu hạn hợp lệ. Snapshot cũ thiếu metadata bị chặn. Huấn luyện tạo dự báo ngoài mẫu theo từng năm trong ba năm gần nhất; mỗi fold chọn đặc trưng, học bộ điền thiếu và mô hình từ nhãn đã đáo hạn trước đầu fold. Xác suất dùng phân phối thực nghiệm của sai số ngoài mẫu, làm trơn Laplace; không giả định phân phối chuẩn và không trả xác suất khi thiếu mẫu. Đây là hiệu chỉnh xác suất, chưa thay thế kiểm định chất lượng độc lập; snapshot mới giữ `unvalidated`.

**Kiểm tra trọng tâm:** Snapshot cũ/thiếu kỳ hạn/lệch ngày, NaN và xác suất ngoài [0,1], nhãn chưa đáo hạn tại đầu fold, dự báo thiếu hiệu chỉnh, giao diện nhận giá trị null.

- [x] Thêm kiểm thử tái hiện lỗi khuyến nghị và xác suất, chạy để xác nhận thất bại.
- [x] Thêm mô-đun hiệu chỉnh ngoài mẫu và tích hợp vào script snapshot, giữ tiến độ cập nhật hiện có.
- [x] Thêm cổng kiểm định và ngày dữ liệu ở dashboard; hiển thị thiếu xác suất an toàn.
- [x] Chạy toàn bộ kiểm thử, huấn luyện lại bằng dữ liệu lake hiện có, đọc lại snapshot và dashboard.
- [x] Rà soát diff, UTF-8 không BOM, không thay đổi ngoài phạm vi và không commit.

## Kết quả xác minh

- Bộ Python: 41 kiểm thử, 2 kiểm thử nguồn trực tiếp bỏ qua; không có lỗi.
- JavaScript: hiển thị null an toàn; 7 tình huống cập nhật và khôi phục tiến trình đều đạt.
- Snapshot và dashboard cùng ngày 2026-10-24, cả ba kỳ hạn `unvalidated`, `buy_signal=False`, tín hiệu chính `observe`.
- Xác suất thực nghiệm 1/3/5 tháng lần lượt 6,8% / 79,2% / 83,2%; lưu 2.796 dự báo ngoài mẫu với quy tắc purge thời gian hợp lệ.
- Đã rà soát độc lập phần mã sửa, không có phát hiện cần sửa trong phạm vi.
- Giới hạn: residuals của lợi suất nhiều tháng có thể chồng lấn; dữ liệu tin hồi cứu chưa được khắc phục; chưa có đánh giá chất lượng độc lập. Không nâng trạng thái mô hình thành đã kiểm định.
