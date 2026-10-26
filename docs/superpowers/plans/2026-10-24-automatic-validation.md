# Tự động kiểm định và cấp validated

> Thực hiện trực tiếp yêu cầu thêm bước tự động cấp `validated`; không commit.

**Mục tiêu:** Mỗi lần huấn luyện/cập nhật đều đánh giá bằng chứng độc lập và tự cấp, giữ chờ hoặc thu hồi trạng thái theo từng kỳ hạn.

**Thiết kế đã chọn:** Đánh giá tiến cứu với dự báo được lưu trước khi biết kết quả. Không dùng lại tập lịch sử đã xem để cấp chứng nhận. Mô hình được tái huấn luyện theo cùng thuật toán; fingerprint mã xử lý, cấu hình và phiên bản thư viện khóa thành một giao thức. Thay đổi giao thức tạo đợt đánh giá mới, không kế thừa thành tích cũ. Ngày bắt đầu luôn sau ngày khóa. Nhật ký giữ bản dự báo đầu tiên trong ngày, không ghi đè để cải thiện kết quả.

**Ngưỡng dự án mặc định:** Ít nhất 120 dự báo đáo hạn, trải ít nhất 365 ngày phát tín hiệu và 6 cửa sổ lợi suất không chồng lấn; MAE và Brier tốt hơn baseline ít nhất 5%; tỷ lệ xuyên Q10 không quá 15%; pinball Q10 không tệ hơn baseline; sai lệch hiệu chỉnh xác suất ECE không quá 10 điểm phần trăm. Đây là quy tắc dự án, không phải chứng nhận đầu tư hay chuẩn ngành. Chưa đủ mẫu thì `validation_pending`; lỗi chất lượng/nguồn thì `validation_failed`; chỉ đạt tất cả mới `validated`.

**Baseline:** Lợi suất bằng 0; xác suất lãi và Q10 hằng số được tính từ train đã đáo hạn ở thời điểm phát dự báo, lưu cùng dự báo trước khi biết kết quả.

**Khả dụng dữ liệu:** Không cấp validated khi còn sử dụng tin lịch sử hồi cứu chưa xác minh hoặc sự kiện proxy RSS không có kiểm chứng khả dụng. Không sửa bộ ghép tin trong phạm vi này.

**Đầu ra:** Giao thức khóa và nhật ký trong `data/lake/modeling/validation/`; báo cáo máy đọc `snapshot_validation_report.json`; trạng thái, nguyên nhân và protocol ID trong snapshot/dashboard. Dashboard đối chiếu báo cáo cùng ngày và cùng giao thức, không chỉ tin nhãn trong CSV.

**Phạm vi tệp:** Tạo `scripts/analysis/snapshot_validation.py`, chính sách JSON trong `configs/`, kiểm thử mới; tích hợp vào `train_latest_snapshot.py`, `build_web_data.py` và kiểm thử dashboard; giữ các thay đổi có sẵn về tiến độ, UTF-8 không BOM và nhãn tiếng Việt.

- [x] Viết kiểm thử cho cấp thành công, từ chối, thiếu mẫu, chống ghi đè và chống dùng lại kết quả giao thức cũ; quan sát thất bại trước khi sửa.
- [x] Thêm chính sách, giao thức khóa, nhật ký dự báo, tính kết quả đáo hạn và các tiêu chí đánh giá.
- [x] Tích hợp chạy tự động vào huấn luyện, nối báo cáo kiểm định với cổng dashboard.
- [x] Chạy đầy đủ kiểm thử và một lượt cập nhật mô hình với dữ liệu hiện có; đọc lại trạng thái và lý do thực tế.
- [x] Rà soát độc lập, kiểm tra UTF-8 và diff; ghi rõ các giới hạn.

## Xác minh

- 53 kiểm thử Python, trong đó 2 kiểm thử nguồn trực tiếp bỏ qua; không có lỗi.
- JavaScript: hiển thị null và escape nội dung lỗi đạt; 7 tình huống cập nhật/khôi phục đạt.
- Kiểm thử toàn luồng dùng fixture tiến cứu đi qua nhật ký → giá đáo hạn → báo cáo → tự cấp validated, thu hồi và reset khi đổi giao thức.
- Rà soát độc lập phát hiện và đã sửa: kiểm tra nguồn event fallback, nhận diện nhật ký bị mất tệp, mở rộng fingerprint đầu vào và buộc đủ chín tiêu chí boolean ở cả snapshot lẫn dashboard. Có kiểm thử tái hiện RED→GREEN cho các nhánh lỗi thực tế.
- Snapshot thật 2026-10-24: cả ba kỳ hạn `validation_failed`, cờ mua false. Giao thức mới bắt đầu nhận bằng chứng từ 2026-10-25 khi chạy Cập nhật/huấn luyện; chưa có dự báo tiến cứu đáo hạn. Hai blocker đầu vào là tin hồi cứu và proxy RSS chưa xác minh availability.
- Ngưỡng là quy tắc chất lượng của dự án. Mẫu chồng lấn vẫn được tính cho chỉ số nhưng bị ràng buộc thêm số chu kỳ không chồng lấn; trạng thái không phải bảo đảm sinh lời. Danh mục và checksum phát hiện mất/sửa tệp ngoài luồng, không phải chữ ký chống người có toàn quyền thay cả mã lẫn bằng chứng.
- Không có lịch chạy nền mới, không deploy và không commit.
