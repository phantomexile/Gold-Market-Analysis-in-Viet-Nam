# 03 — Mô hình đang dùng và ý nghĩa kiểm định

Nguồn xác nhận cấu hình là [active_prediction_model.json](../../data/lake/modeling/active_prediction_model.json). Tại lần chuẩn hóa ngày 06/11/2026, registry chọn `reliability_v2`:

| Kỳ hạn | Ứng viên | Điểm cần giải thích |
|---|---|---|
| 1 tháng | rf_median | Tiêu chí sai số tuyệt đối, học trực tiếp lợi suất ròng |
| 3 tháng | rf_small | Tiêu chí bình phương, học biến động giá mua lại rồi đổi sang lợi suất ròng |
| 5 tháng | rf_small | Huấn luyện và nhãn riêng cho kỳ hạn 5 tháng |

Cả hai cấu hình RF có 100 cây, độ sâu tối đa 4 và ít nhất 30 mẫu mỗi lá. “Nhỏ” không có nghĩa RF này ít cây hơn RF trung vị. Chọn riêng từng kỳ hạn vì sai số trên lịch sử phát triển khác nhau; không phải quy luật RF trung vị luôn tốt nhất ở ngắn hạn.

## Ba loại đầu ra cần tách biệt

| Giá trị | Ý nghĩa | Không được diễn giải thành |
|---|---|---|
| Dự báo lợi suất | Ước lượng mức lãi/lỗ theo kỳ hạn | Lợi nhuận chắc chắn |
| P(lãi) | Xác suất ước lượng lợi suất lớn hơn 0 | Độ chính xác của toàn mô hình |
| Q10 | Ước lượng phân vị thấp 10% của lợi suất | Mức lỗ tối đa được bảo đảm |

MAE là trung bình trị tuyệt đối của sai số lợi suất. Dự báo 5%, thực tế 2% thì sai số là 3 **điểm phần trăm**. Đối chứng zero luôn dự báo lợi suất 0%; nếu RF không vượt được đối chứng này, chưa thể khẳng định độ phức tạp tạo ra giá trị.

## Trạng thái và điều kiện công bố

- `validation_pending`: chưa đủ bằng chứng kiểm định tiến cứu.
- `validated`: cần đúng giao thức và vượt mọi phép kiểm tra bắt buộc, không chỉ có một nhãn trạng thái.
- `research_only`: kết quả phục vụ nghiên cứu, không phải xác nhận giao dịch.
- Chỉ số P(lãi)/Q10 không đạt tiêu chí có thể để trống. Không đọc số đối chứng hoặc số nghiên cứu thay cho giá trị đã được phép công bố.

Snapshot CSV đang lưu ngày **04/11/2026** có cả ba kỳ hạn `validation_pending`. Khi demo phải đọc lại ngày/status trực tiếp vì đây là dữ liệu có thể thay đổi.

Tín hiệu Mua/Bán/Quan sát trên chế độ dự báo trực tiếp là cách diễn giải dự báo điểm. Trạng thái kiểm định được trình bày riêng. Xem [build_web_data.py](../../scripts/build_web_data.py) và [báo cáo điều chỉnh từng kỳ hạn](../reports/modeling/horizon-forecasts-2026-10-26.md).

Mở [03 — Mã mô hình có chú thích](code/03_stationary_research.py) để giải thích loss/target và điều kiện ngày thoát; mở [04 — Kiểm định](code/04_snapshot_validation.py) để giải thích vì sao backtest chưa thay thế dự báo mới.
