# Giữ dự báo riêng từng kỳ hạn

**Yêu cầu điều chỉnh:** baseline chỉ dùng làm đối chứng; không thay cả ba đầu ra dự báo bằng 0 khi ML chưa đạt kiểm định.

**Nguyên nhân:** `run_forecast_repair.py` dùng kết quả chọn ứng viên đủ chuẩn làm luôn nguồn dự báo trực tiếp. Khi cả ba chưa đạt, cả ba cùng chọn zero. Đầu ra RF riêng từng kỳ hạn vẫn tồn tại.

**Cách sửa:** chọn ML có MAE thấp nhất từ lịch sử đã đáo hạn riêng mỗi kỳ hạn, ưu tiên ML đủ chuẩn nếu có. Giữ benchmark winner và kết quả chưa đạt thành metadata riêng; không tự cấp validated. Hiển thị chú thích dự báo thử nghiệm và giới hạn so với baseline. Không thay đổi công thức quy đổi hoặc phương pháp hiệu chỉnh P/Q10.

## Các bước

- [x] Kiểm thử RED→GREEN cho việc baseline thắng không xóa đầu ra ML và không có ML thì báo thiếu.
- [x] Tách `forecast_selection.py`, tích hợp runner và metadata bản khóa.
- [x] Kiểm thử RED→GREEN cho dự báo trực tiếp khác nhau và ghi rõ benchmark chưa đạt.
- [x] Tái chọn từ các dự báo OOS đã lưu trên đúng model frame, tính lại snapshot với estimator không đổi; mở bản khóa mới và đồng bộ CSV/web/sổ mô phỏng.
- [x] Chạy lại cập nhật, bộ kiểm thử và UTF-8/no-BOM; ghi kết quả thực tế, chưa commit.

**Giới hạn:** thay đổi này sửa việc dùng sai baseline; không biến ML đang thua đối chứng thành mô hình tốt hơn. Các tín hiệu giống nhau nếu cùng vượt một ngưỡng vẫn được giữ nguyên.

## Kết quả

- Snapshot 24/10/2026: 1 tháng RF trung vị −0,66%/Quan sát; 3 tháng RF nhỏ +3,08%/Mua; 5 tháng RF nhỏ +8,47%/Mua. Cả ba vẫn validation_pending và ghi rõ thử nghiệm/chưa vượt baseline.
- Đã phát hiện và sửa mất chữ số khi đọc lại CSV bằng round_trip, có test RED→GREEN; snapshot khớp kết quả ML đã lưu trong sai số <1e-12.
- Lượt v3 dừng trước kích hoạt; lượt hoàn tất v4 giữ nguồn/hash của OOS v2 và bằng chứng lựa chọn riêng từng kỳ hạn.
- Rà soát độc lập không phát hiện vấn đề quan trọng trong lần điều chỉnh này. Đã chạy lại refresh --skip-collect: ba dự báo giữ nguyên, CSV/web nhất quán.
- Kiểm tra cuối: 112 tests OK, 3 skips; 2 bộ test Node đạt; git diff --check không lỗi; 83 tệp UTF-8/no-BOM không phát hiện mojibake. Chưa commit.
