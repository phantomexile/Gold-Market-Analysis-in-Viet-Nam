# Mở rộng RF cải tiến và dọn file không cần thiết

Yêu cầu: dùng RF cải tiến cho cả 1/3/5 tháng; xóa file thừa. Không commit.

- [x] Kiểm thử thất bại trước khi mở rộng API; kiểm thử nhãn riêng và tuyến kích hoạt riêng.
- [x] Giữ tham số RF 100 cây, sâu 4, lá tối thiểu 30; dùng 34 đặc trưng tỷ lệ.
- [x] Cửa sổ huấn luyện 5 năm, fit đầu tháng, loại nhãn chưa đáo hạn từng kỳ hạn.
- [x] Hiệu chỉnh sigmoid và residual Q10 theo 24 tháng dự báo ngoài mẫu riêng.
- [x] Registry kích hoạt tất cả kỳ hạn; lỗi riêng chuyển Quan sát, không ghép số cũ.
- [x] Huấn luyện ngoài mẫu, khóa mới và áp dụng thật; không kế thừa nhãn validated.
- [x] Dọn thư viện thử nghiệm, bản chạy lỗi/bị thay thế, log/ảnh kiểm tra cũ.
- [x] Kiểm tra Python/JavaScript, dữ liệu dashboard và rà soát độc lập.

Quyết định phạm vi: giữ dữ liệu gốc, nhật ký kiểm định, báo cáo thí nghiệm hoàn tất
và mã tái lập. Chỉ xóa tài nguyên có thể tạo lại hoặc bản chạy thất bại/bị thay thế.
Chi phí của việc giữ các báo cáo là dung lượng nhỏ còn lại, giúp truy nguyên kết quả.

## Xác nhận

- 95 bài Python: 92 đạt, 3 bỏ qua (2 collector trực tiếp và 1 adapter dùng hai thư viện đã dọn).
- Kiểm tra JavaScript hiển thị dữ liệu thiếu, tín hiệu trực tiếp và 7 tình huống cập nhật đạt.
- Giao diện 1440/390px: đủ ba thẻ, 12 chỉ số hiển thị sẵn, không tràn ngang; đã xem ảnh 390px.
- Rà soát độc lập phát hiện entry cấu hình sai kiểu có thể gây lỗi dashboard;
  đã tái hiện RED, sửa kiểm tra kiểu và chạy GREEN cùng toàn bộ bộ kiểm thử.
- Test walk-forward 1/5 tháng xác nhận cả train và calibration chỉ dùng ngày thoát trước đầu tháng.
- Dọn 157 file/369.307.394 byte; giữ runtime RF và bằng chứng gốc. Không commit/deploy.
