# Sửa quy đổi và độ tin cậy dự báo — 26/10/2026

**Điều chỉnh sau phản hồi:** baseline không còn thay cả ba dự báo bằng 0. Trạng thái hiện tại và dự báo riêng từng kỳ hạn nằm trong [báo cáo điều chỉnh](horizon-forecasts-2026-10-26.md). Các bảng chọn zero dưới đây ghi lại lượt v2 trước điều chỉnh, không phải cấu hình đang hiển thị.

**Điều chỉnh sau phản hồi:** baseline không còn thay cả ba dự báo bằng 0. Trạng thái hiện tại và dự báo riêng từng kỳ hạn nằm trong [báo cáo điều chỉnh](horizon-forecasts-2026-10-26.md). Các bảng chọn zero dưới đây ghi lại lượt v2 trước điều chỉnh, không phải cấu hình đang hiển thị.

Phạm vi: các vấn đề 1–3 trong audit. Dùng lại dữ liệu lake, snapshot 24/10/2026; không tải thêm báo giá hoặc thay ngưỡng kiểm định.

## 1. Quy đổi khối lượng

Giá thế giới VND/lượng = giá USD/troy ounce × tỷ giá USD/VND × 37,5 / 31,1034768.
Một lượng bằng 37,5 gram; một chỉ bằng 3,75 gram. Đã bỏ hệ số nhân thừa 1,205 và dùng hằng số chung trong `src/gold_collectors/units.py` cho builder, cấu hình và audit.
Nguồn đối chiếu: [Công báo, trang 53](https://congbaocdn.chinhphu.vn/CongBaoCP/CongBao/2024/9/42697/51713-1-1041-1042.pdf#page=53).

Với 4.150 USD/oz và 25.892 VND/USD, giá quy đổi đúng là **129.549.584,63 VND/lượng**, thay cho 156.107.249,48 VND/lượng. Premium biểu đồ theo giá SJC trung bình đổi từ **−14.407.249** thành **+10.650.415 VND/lượng (+8,22%)**.
Premium đặc trưng mô hình dùng giá SJC bán ra, còn biểu đồ giữ định nghĩa theo giá mua/bán trung bình; hai giá trị phải được đọc đúng mẫu số. Dashboard ưu tiên bảng premium vừa dựng cùng model frame, không đọc bản sao enriched cũ trước.

## 2. Đối chứng mô hình

Thêm RF học trung vị lợi suất ròng bằng sai số tuyệt đối để phù hợp MAE, so sánh với RF cũ và mốc lợi suất 0. Chỉ chọn ML khi MAE cải thiện ít nhất 5%, tốt hơn zero ở ít nhất ba năm và cận dưới bootstrap khối 90% dương; chỉ dùng nhãn đáo hạn trước cutoff đầu tháng.
Đây là lựa chọn trên lịch sử phát triển đã xem, không phải một tập kiểm định độc lập mới.

| Kỳ hạn | RF cũ trước sửa, MAE | RF trung vị, MAE | Zero, MAE | Đang dùng |
|---|---:|---:|---:|---|
| 1 tháng | 4.34 điểm % | 4.18 điểm % | 3.70 điểm % | zero |
| 3 tháng | 9.33 điểm % | 10.31 điểm % | 8.97 điểm % | zero |
| 5 tháng | 14.47 điểm % | 14.58 điểm % | 14.07 điểm % | zero |

**Không ứng viên ML nào đạt tiêu chí thay baseline.** Hệ thống dùng mốc lợi suất 0 cho cả ba kỳ hạn. Đây là phương án dự phòng ít sai số hơn RF đang dùng trước sửa, không phải bằng chứng ML có lợi thế giao dịch.

## 3. Xác suất và Q10

Xác suất sigmoid được trộn với prior huấn luyện bằng trọng số chọn từ Brier của những xác suất OOS đã phát trước đó, với mỗi tháng có trọng số ngang nhau. Q10 được hiệu chỉnh bằng sai số Q10 OOS đã đáo hạn, giới hạn lợi suất tối thiểu −100%.
Hiệu chỉnh coverage không tự chứng minh Q10 tốt hơn: vẫn chấm pinball để tránh đưa phân vị xuống quá thấp rồi gọi là an toàn.

Đối chiếu trên cùng RF cũ (giữ nguyên kỳ hạn và tập ngày đánh giá):

| Kỳ hạn | Brier trước → sau | Xuyên Q10 trước → sau | Pinball Q10 trước → sau |
|---|---:|---:|---:|
| 1 tháng | 0.2730 → 0.2721 | 16.95% → 15.03% | 0.01148 → 0.01097 |
| 3 tháng | 0.3270 → 0.2908 | 17.23% → 12.15% | 0.02375 → 0.02524 |
| 5 tháng | 0.2990 → 0.2636 | 19.11% → 14.27% | 0.04791 → 0.04957 |

Brier và mức bao phủ cải thiện; pinball kỳ hạn 3 và 5 tháng còn kém hơn trước. Do đó hệ thống không công bố các chỉ số chỉ dựa trên một tiêu chí đẹp.

| Kỳ hạn đang dùng | P(lãi) công bố | Q10 công bố | Trạng thái |
|---|---|---|---|
| 1 tháng | Chưa đạt | -8.63% | validation_pending |
| 3 tháng | Chưa đạt | Chưa đạt | validation_pending |
| 5 tháng | Chưa đạt | Chưa đạt | validation_pending |

P(lãi) và Q10 được chấm riêng; thiếu một chỉ số không chặn chỉ số còn lại. Nhật ký giữ nguyên dự báo nghiên cứu gốc ngay cả khi UI trả null, nên vẫn có thể chấm tiến cứu sau khi đáo hạn.
Bản khóa mới riêng từng kỳ hạn bắt đầu từ **27/10/2026**; không kế thừa trạng thái validated hoặc thành tích của bản khóa cũ.

## Luồng cập nhật và bằng chứng

- `scripts/analysis/active_snapshot.py` công bố cùng dự báo cho CSV, báo cáo kiểm định, sổ mô phỏng và dashboard.
- Luồng cập nhật đã được chạy lại với `refresh_latest_forecast.py --skip-collect`; snapshot/model frame/dashboard cùng ngày 24/10/2026. Cập nhật lại giữ nguyên mô hình zero và các cổng P/Q10, không quay về RF cũ.
- Hash model frame sau cập nhật khớp đúng frame dùng trong lượt nghiên cứu hoàn tất.
- Báo cáo đầy đủ: `data/lake/modeling/research/2026-10-26-forecast-repair-v2/report.json`; tất cả dự báo OOS và các kết quả không đạt được giữ cùng thư mục.
- Lượt v1 dừng trước kích hoạt để sửa phát hiện review; manifest ghi interrupted. Chỉ lượt v2 được dùng công bố.

## Kiểm tra

Đã có kiểm thử RED → GREEN cho quy đổi, baseline dự phòng, RF trung vị, không dùng nhãn tương lai, hiệu chỉnh OOS, giới hạn Q10, chỉ số P/Q10 tách riêng, bản sao dữ liệu web cũ, bảo toàn nhật ký và cập nhật lặp lại. Bộ kiểm thử cuối chạy 108 ca: không lỗi, 3 ca bỏ qua; hai bộ kiểm thử Node đạt. `git diff --check` không lỗi; 62 tệp thay đổi/sinh mới được kiểm tra UTF-8 không BOM, không phát hiện mojibake. Chưa commit.
