# Tách đánh giá lịch sử và kiểm chứng thực tế

**Mục tiêu đã được chấp thuận:** Thực hiện bước 1–3 của kế hoạch trong chat, giữ nguyên ngưỡng kiểm chứng thực tế. Không commit/deploy, không xóa tin hiển thị, không thay nhãn tiếng Việt ngoài phần trạng thái được yêu cầu.

**Đầu vào:** Lọc sự kiện trước khi tạo tổng số, rolling và đặc trưng: chỉ giữ lịch biết trước từ nguồn lịch tin cậy; loại toàn bộ proxy RSS và sự kiện nghiên cứu hồi cứu chưa có bằng chứng khả dụng. Tin chỉ vào mô hình khi có nhãn `strict_realtime_verified` và availability không sớm hơn cả ngày đăng lẫn ngày thu thập; ghép theo ngày khả dụng trễ một ngày, không theo event_date. Không dùng body_text chưa có phiên bản thời gian. Tin chưa xác minh và sentiment fallback không vào mô hình; vẫn giữ dữ liệu gốc/dashboard. Diagnostics ghi rõ số dòng loại và phạm vi đã xác minh.

**Lịch sử:** Tạo các fold đóng băng theo năm; chọn đặc trưng, imputation và mô hình chỉ học nhãn đã đáo hạn trước đầu fold. Xác suất của năm đánh giá chỉ dùng residuals các năm trước đã đáo hạn tại đầu fold. Đánh giá từ 2023, tạo fold trước đó phục vụ hiệu chỉnh. Q10 và baseline được fit riêng trong train. Lưu từng dự báo, thời điểm train/calibration và báo cáo MAE/Brier/Q10/ECE. Dùng cùng các ngưỡng chất lượng hiện có, nhưng trạng thái là `historical_passed/failed/insufficient`; không nâng thành `validated`.

**Dashboard:** Mỗi kỳ hạn có hai mức riêng: đánh giá lịch sử và kiểm chứng thực tế, kèm số dự báo đáo hạn/cửa sổ/thời gian so với yêu cầu. Tín hiệu giả định được ghi rõ “mô phỏng nghiên cứu”; không dùng để mở cờ mua thực tế hoặc ghi vị thế. Báo cáo lịch sử thiếu/sai ngày/sai giao thức thì hiển thị chưa đủ dữ liệu. Giữ cổng mua thực tế và chính sách 120/365/6, MAE/Brier/Q10/ECE nguyên trạng.

**Giới hạn:** Lịch sử đã xem để điều chỉnh mô hình, nên báo cáo mới vẫn là sàng lọc nghiên cứu. Lần đầu chạy lại dùng lake hiện có; không tự thu thập dữ liệu ngoài phạm vi.

- [x] Kiểm thử lọc tin/sự kiện, kể cả đặc trưng phái sinh; thấy RED trước khi sửa.
- [x] Lọc đầu vào ở builder; chẩn đoán kiểm chứng chỉ xét nguồn thực sự dùng; chạy bộ kiểm thử.
- [x] Kiểm thử chia train/calibration/evaluation lịch sử và trạng thái không thể thành validated; thêm module đánh giá, tích hợp snapshot.
- [x] Kiểm thử và bổ sung hai mức trạng thái/progress/tín hiệu mô phỏng trên dashboard.
- [x] Chạy lại mô hình, rà soát độc lập, kiểm tra dữ liệu thực tế và giao diện, UTF-8 không BOM, diff.

## Kết quả thực hiện

- Chạy lại toàn bộ snapshot trên lake đến 2026-10-24, không gọi thu thập bên ngoài.
- Loại 3.402 tin không đủ bằng chứng, giữ 490 tin đã xác minh chỉ từ ngày khả dụng; loại 502 sự kiện chưa xác minh, giữ 1.786 dòng lịch biết trước. Dữ liệu gốc và tin trên dashboard không bị xóa.
- Lưu 3.891 dự báo đánh giá lịch sử, đối chiếu train_last_exit_date/calibration_last_exit_date < fold_start <= ngày dự báo và ngày thoát không sau snapshot.
- Cả ba kỳ hạn historical_failed. MAE 1/3/5 tháng: 6,23 / 12,44 / 16,71 điểm phần trăm; baseline 3,70 / 8,97 / 14,07. Đây là kết quả sàng lọc lịch sử đã xem, không chứng minh khả năng đầu tư.
- Cả ba kỳ hạn validation_pending ở mức thực tế, inputs_verified=True, 0 dự báo tiến cứu đáo hạn. Dashboard giữ observe và cờ mua false; không dùng số mẫu lịch sử làm tiến độ thực tế.
- Chính sách thực tế không đổi: SHA-256 074C86659F254A2F2C12AF3407BDD6B983D7BA9131E65BC1856D10F837D73C96.
- 58 kiểm thử Python (2 bài nguồn trực tiếp bỏ qua); JavaScript null/HTML/hai mức và 7 tình huống cập nhật đạt.
- Rà soát độc lập phát hiện metadata event_date không cần thiết vẫn làm mất tin hợp lệ; đã có kiểm thử RED→GREEN và sửa. Phần tích hợp không có phát hiện cần sửa.
- Kiểm tra phần đánh giá bằng DOM/CSS thật trong Chrome ở 1440px và 390px, ảnh xem lại trực tiếp; đủ ba kỳ hạn, hai mức riêng và không tràn nội dung. Kiểm tra này tách khỏi CDN biểu đồ, không thay thế kiểm thử biểu đồ toàn trang.
- Chỉ sửa/lưu các tệp thuộc phạm vi đã duyệt; giữ thay đổi có sẵn, UTF-8 không BOM, không commit/deploy.
