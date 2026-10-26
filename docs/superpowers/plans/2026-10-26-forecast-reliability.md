# Sửa quy đổi và độ tin cậy dự báo — Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Không commit theo yêu cầu người dùng.

**Goal:** Sửa các vấn đề 1–3 đã được người dùng duyệt: quy đổi đơn vị, mô hình kém baseline, P(lãi)/Q10 chưa đáng tin.

**Architecture:** Dùng chung hằng số khối lượng; thêm RF tối ưu sai số tuyệt đối và chọn ứng viên với mốc zero làm dự phòng. Hiệu chỉnh chỉ dùng OOS đã đáo hạn; chặn công bố P/Q10 chưa qua kiểm tra riêng, đồng thời giữ số liệu nghiên cứu để không che kết quả kém.

**Tech Stack:** Python, pandas, NumPy, scikit-learn; giữ pipeline tháng lịch 1/3/5.

## Global Constraints

- UTF-8 không BOM; chú thích tiếng Việt có dấu; không commit, không tải lại dữ liệu ngoài phạm vi.
- Giữ nguyên configs/forecast_validation_policy.json; lịch sử đã xem vẫn research_only.
- Làm trong checkout hiện tại sạch để dùng được data lake và runtime modeling-deps hiện có.
- Giữ nguyên bản khóa, báo cáo và nhật ký cũ; mã thay đổi tạo bản khóa mới, không kế thừa validated.
- Không sửa các vấn đề 4–7 ngoài thay đổi nhãn mô hình cần thiết để nhận biết baseline và lý do thiếu P/Q10.

## Review Focus

- Một lượng = 37,5 g; một troy ounce = 31,1034768 g; không nhân thêm 1,205.
- Đổi nhãn chưa đáo hạn/tương lai không được đổi lựa chọn hoặc hiệu chỉnh quá khứ.
- Thất bại baseline không được ép chọn RF; fallback không được nhận nhãn cải thiện.
- P/Q10 không đủ chất lượng phải trả null với lý do, không gán 0 hoặc giấu số liệu nghiên cứu.
- Cả ba kỳ hạn có dữ liệu hiệu chỉnh và bản khóa riêng; cập nhật lại không quay về mô hình cũ.

## Tasks

- [x] 1. RED: kiểm thử đơn vị độc lập; GREEN: hằng số chung trong các builder/config/audit; dựng lại premium.
- [x] 2. RED: kiểm thử lựa chọn không ép RF và RF tối ưu MAE; GREEN: thêm rf_median, báo cáo so sánh và chọn ứng viên từng kỳ hạn, zero dự phòng.
- [x] 3. RED: kiểm thử hiệu chỉnh chỉ dùng quá khứ, kiểm tra xác suất/Q10 độc lập; GREEN: trộn xác suất theo Brier OOS, hiệu chỉnh coverage Q10 theo sai số OOS và chặn chỉ số chưa đạt.
- [x] 4. Dựng lại frame, chạy so sánh ba kỳ hạn, tạo bản khóa mới và dashboard; lưu báo cáo trước/sau trung thực.
- [x] 5. Chạy bộ kiểm thử, rà soát thay đổi độc lập, kiểm tra UTF-8/no-BOM và git diff.

## Decisions and evidence

- Người dùng đã yêu cầu sửa trực tiếp sau audit; không mở thêm vòng duyệt thiết kế.
- Không thể cam kết dự báo thắng thị trường bằng thay đổi phần mềm. Nếu không ứng viên nào đạt mức cải thiện đã khóa, dùng baseline và ghi rõ giới hạn.
- Baseline trước sửa: 95 tests, OK, 3 skips. Các test mới đã có RED rồi GREEN; xem tests/test_forecast_repair.py.
- Review độc lập phát hiện 2 lỗi quan trọng: refresh ghi đè CSV bằng RF cũ; missing P/Q10 chặn lẫn nhau. Đã sửa bằng active_snapshot.py và bộ chấm tách riêng, có test hồi quy cho cả hai.
- Lượt forecast-repair-v1 dừng trước công bố để sửa review; manifest ghi interrupted. Lượt v2 chạy lại từ mã cuối cùng, không dùng kết quả v1.
- Lượt v2 hoàn tất: cả 1/3/5 tháng chọn zero vì không ML nào đạt tiêu chí. Q10 1 tháng được công bố −8,63%; P cả ba kỳ hạn và Q10 3/5 tháng chưa đạt, giữ null và lý do. Bằng chứng mới bắt đầu 27/10/2026.
- Đã chạy refresh_latest_forecast.py --skip-collect trên dữ liệu thật: CSV/model frame/dashboard cùng snapshot 24/10/2026, vẫn chọn zero; hash frame khớp lượt nghiên cứu.
- Kiểm tra cuối: 108 tests, OK, 3 skips; 2 bộ test Node đạt; git diff --check = 0; 62 tệp thay đổi sinh mới kiểm tra UTF-8/no-BOM, không phát hiện mojibake.
- Rà soát cuối phát hiện dashboard ưu tiên enriched legacy; có test RED→GREEN và đã chuyển sang bảng premium chuẩn, tính lại quy đổi và giữ premium biểu đồ theo giá trung bình. Snapshot hiển thị tham chiếu 129.549.585, premium +10.650.415 (+8,22%).
