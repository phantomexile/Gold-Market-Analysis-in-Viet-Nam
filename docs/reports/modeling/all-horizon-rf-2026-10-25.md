# RF cải tiến cho cả ba kỳ hạn

Đã áp dụng RF cải tiến cho 1, 3 và 5 tháng lịch. Giữ cấu hình 100 cây,
độ sâu tối đa 4, lá tối thiểu 30 mẫu, 34 đặc trưng tỷ lệ/biến động;
huấn luyện đầu tháng trên cửa sổ 5 năm và chỉ dùng nhãn đã đáo hạn.
Mỗi kỳ hạn có bộ nhãn và hiệu chỉnh sigmoid/Q10 residual riêng từ 24 tháng
dự báo ngoài mẫu đã đáo hạn. Không dùng xác suất hoặc thành tích của kỳ hạn khác.

## Snapshot 24/10/2026

| Kỳ hạn | Lợi suất mua mới | Xác suất lãi | Q10 | Tín hiệu |
|---|---:|---:|---:|---|
| 1 tháng | +0,87% | 52,98% | −7,16% | Quan sát |
| 3 tháng | +3,08% | 68,74% | −14,25% | Mua |
| 5 tháng | +8,47% | 82,14% | −26,89% | Mua |

Ngưỡng trung tính 1% giữ nguyên. Q10 là phân vị rủi ro dự báo, không phải
mức lỗ tối đa. Các con số trong bảng là dự báo, không phải lợi nhuận đã đạt.

## Kiểm tra lịch sử

| Kỳ hạn | Ngày đã đáo hạn từ 2023 | MAE (điểm %) | Cải thiện so mốc lợi suất 0 |
|---|---:|---:|---:|
| 1 tháng | 1.351 | 4,34 | −17,5% |
| 3 tháng | 1.300 | 9,33 | −4,0% |
| 5 tháng | 1.240 | 14,47 | −2,9% |

Cả ba chưa đạt đầy đủ tiêu chí chất lượng. “Cải tiến” mô tả thay đổi phương pháp;
kết quả trên chưa chứng minh độ chính xác tốt hơn mốc so sánh. Trạng thái vẫn
`validation_pending`, bắt đầu tích lũy bằng chứng mới từ 26/10/2026.

Kết quả chi tiết, dự báo ngoài mẫu và hiệu chỉnh được giữ trong
`data/lake/modeling/research/2026-10-25-all-horizon-rf-v1/`.
Registry chọn mô hình ở `data/lake/modeling/active_prediction_model.json`.
Nhật ký 3 tháng giữ đường dẫn `stationary_shadow/`; 1 và 5 tháng dùng
`stationary_shadow/1m/` và `stationary_shadow/5m/`.

Mỗi lượt dựng dashboard làm mới dự báo của cả ba kỳ hạn. Hook `--record-only`
của pipeline ghi và chấm nhật ký riêng khi dự báo đáo hạn. Kỳ hạn có lỗi
bản khóa/ngày/giá chuyển Quan sát và bỏ số liệu lỗi; các kỳ hạn còn lại tiếp tục.
`snapshot_forecasts.csv` và báo cáo kiểm định cũ được giữ làm tham chiếu;
dashboard lấy bộ point/P/Q10 mới từ từng bản khóa đang được kích hoạt.

## Dọn file

Đã xóa 157 file, tổng cộng 369.307.394 byte (khoảng 352 MiB): thư viện
LightGBM/CatBoost chỉ dùng thử nghiệm, hai lượt nghiên cứu lỗi/bị thay thế,
log/ảnh kiểm tra cũ và các bản sao phục vụ tái cấu trúc.
Danh sách chính xác nằm trong `docs/cleanup-2026-10-25.json`.
Giữ dữ liệu gốc, runtime RF, mã tái lập, báo cáo hoàn tất và nhật ký kiểm định.
