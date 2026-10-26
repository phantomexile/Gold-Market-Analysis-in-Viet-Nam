# Khôi phục dự báo riêng cho ba kỳ hạn

## Nguyên nhân ba kỳ hạn cùng bằng 0

Lượt sửa trước dùng `select_deployable_candidate` để chọn luôn nguồn dự báo trực tiếp. Khi cả ba ML chưa vượt baseline, cả ba cùng chọn `zero`. Đây là thay dự báo bằng đối chứng, không phải cải thiện mô hình dự báo.

## Cách sửa

- `forecast_selection.py` chọn ML riêng từng kỳ hạn từ các nhãn đã đáo hạn trước đầu tháng dự báo. Ưu tiên ML đạt tiêu chí nếu có; nếu chưa có, chọn ML có MAE thấp nhất để hiển thị dưới nhãn thử nghiệm.
- Giữ riêng `benchmark_winner`, `point_comparison` và kết quả chưa đạt. Baseline zero tiếp tục là mốc đánh giá, không xóa đầu ra ML và không tự cấp validated.
- CSV, dashboard và sổ mô phỏng cùng lấy mô hình đang kích hoạt. Dashboard hiển thị rõ giới hạn so với baseline.
- Giữ nguyên quy đổi đơn vị đã sửa và hai cổng P/Q10 riêng biệt. Không tạo xác suất hay Q10 để điền vào ô trống khi chất lượng chưa đạt.

## Snapshot 24/10/2026 sau điều chỉnh

| Kỳ hạn | Mô hình | Lợi suất ròng dự báo | Tín hiệu trực tiếp | Kiểm định |
|---|---|---:|---|---|
| 1 tháng | RF học trung vị lợi suất ròng | −0,66% | Quan sát | validation_pending |
| 3 tháng | RF nhỏ | +3,08% | Mua | validation_pending |
| 5 tháng | RF nhỏ | +8,47% | Mua | validation_pending |

Hai kỳ hạn cùng ra Mua là kết quả áp dụng cùng quy tắc lên hai dự báo khác nhau; không ép các tín hiệu phải khác nhau. Các con số là dự báo nghiên cứu, không phải lợi nhuận đã đạt hoặc bằng chứng ML thắng baseline.

## Bằng chứng và tính tái lập

Tái sử dụng các dự báo OOS đã lưu ở lượt `2026-10-26-forecast-repair-v2`, trên đúng model frame có hash khớp. Không thay estimator, đặc trưng, nhãn hoặc phương pháp hiệu chỉnh để làm kết quả khác đi. Snapshot của mô hình được chọn được fit/tính lại và khớp dự báo đã lưu tới sai số số thực nhỏ hơn 1e-12.

Trong kiểm tra này phát hiện đọc CSV mặc định có thể mất chữ số ở đầu vào và làm RF chọn nhánh khác. Đã sửa đọc frame/hiệu chỉnh bằng chế độ `round_trip`, có kiểm thử RED→GREEN so sánh kết quả trước/sau lưu CSV.

Lượt `2026-10-26-horizon-forecasts-v3` dừng trước kích hoạt khi phát hiện chênh lệch số thực. Lượt hoàn tất dùng công bố là `2026-10-26-horizon-forecasts-v4`; các bản khóa cũ được giữ nguyên, bản mới không kế thừa thành tích.

Báo cáo hiện tại: `data/lake/modeling/research/2026-10-26-horizon-forecasts-v4/report.json`. File ghi nguồn và hash của từng CSV OOS, ứng viên được chọn, đối chứng và trạng thái hiệu chỉnh/kiểm định. Lệnh dựng lại toàn bộ `run_forecast_repair.py --output <thu-muc-moi>` đã dùng cùng quy tắc lựa chọn mới.

Đã chạy lại luồng cập nhật không thu thập mới: CSV và dashboard vẫn giữ đúng ba dự báo trên, cùng snapshot 24/10/2026. Bộ kiểm thử cuối: 112 ca không lỗi, 3 ca bỏ qua; hai bộ kiểm thử Node đạt. Chưa commit.
