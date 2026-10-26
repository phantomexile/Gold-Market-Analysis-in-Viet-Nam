# Kết quả cải tiến mô hình ba tháng

Lịch sử đã xem phục vụ phát triển; chưa chứng minh hiệu quả trên dữ liệu mới. Giao diện và mô hình đang hiển thị chưa đổi.

## Cách đánh giá

- 34 đặc trưng tỷ lệ/biến động, bảy ứng viên khóa trước chạy, train cửa sổ 5 năm.
- Fit đầu tháng, chỉ học nhãn đã đáo hạn; chọn model bằng 24 tháng OOS đã biết, tối thiểu 120 dòng/6 tháng và giảm MAE ít nhất 5% so zero.
- Ngưỡng tín hiệu chỉ thử 0,5%/1%/2%, chọn bằng danh mục quá khứ; thiếu ba giao dịch hoàn tất giữ 1%.
- P(lãi) sigmoid học OOS; Q10 chính bằng point + phân vị residual OOS. GBR Q10 và xác suất empirical là đối chứng, không tự đổi sang phương pháp thắng bảng.
- Danh mục tiền mặt/vàng, quyết định tháng, mua giá bán và bán/định giá theo giá mua; không cộng lợi suất các cửa sổ chồng lấn. Chỉ tính spread, chưa có phí lưu trữ/thuế/phí khác.

## Dự báo và danh mục

| Ứng viên | MAE (điểm %) | Cải thiện so zero | Lợi suất danh mục | Mức giảm tối đa |
|---|---:|---:|---:|---:|
| boosting | 9.46 | -5.5% | +46.5% | -29.1% |
| elasticnet | 11.44 | -27.5% | +59.1% | -29.1% |
| median | 9.01 | -0.5% | +77.1% | -29.1% |
| no_price_change | 9.68 | -7.9% | +0.0% | 0.0% |
| rf_small | 9.33 | -4.0% | +52.3% | -29.1% |
| ridge | 11.58 | -29.1% | +50.2% | -29.1% |
| zero | 8.97 | +0.0% | +0.0% | 0.0% |
| Chọn trước từng tháng | 9.81 | -9.4% | +16.6% | -29.1% |

Lợi suất danh mục là toàn kỳ nghiên cứu, không phải lợi suất năm hoặc lợi suất dự báo.

## Ứng viên khóa theo dõi

- Mô hình: **rf_small**, ngưỡng 1%.
- Đạt toàn bộ tiêu chí phát triển: **False**.
- Bản khóa là shadow, không thay mô hình mặc định và không tự cấp validated.
- Nhật ký mới chỉ nhận dự báo phát đúng ngày hiện tại và từ ngày sau ngày khóa; dự báo snapshot cũ chỉ là bản tham chiếu.

Chi tiết từng năm, xác suất, Q10, độ đúng Mua/Bán không chồng lấn, bootstrap khối và tiêu chí chưa đạt nằm trong report.json.
