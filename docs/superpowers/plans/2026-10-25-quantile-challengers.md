# Đối chứng LightGBM Quantile và CatBoost MultiQuantile

**Phạm vi đã duyệt:** Thử hai thuật toán trên ba tháng, so RF đang dùng và zero; không tự kích hoạt, không đổi ngưỡng để tạo kết quả đạt, không commit/deploy.

**Thiết kế cố định trước chạy:**

- Dùng đúng frame, bộ 34 đặc trưng, năm năm train, refit đầu tháng; exit train < đầu tháng. Warmup2021, chấm2023 đến snapshot hiện có.
- LightGBM: ba mô hình quantile alpha0.1/0.5/0.9, 200cây, learning_rate0.04, depth4, leaves15, min_child40, lambda5, seed42, CPU4threads.
- CatBoost: MultiQuantile alpha0.1/0.5/0.9, 200iterations, learning_rate0.04, depth4, l2_leaf_reg5, seed42, CPU4threads, không ghi catboost_info.
- Cả hai học hold return, chuyển về lợi suất mua mới bằng bid/ask; point lấy Q50. Median imputer fit train. Sắp tăng ba phân vị nếu giao nhau, ghi số lần giao để kiểm toán; đây là hậu xử lý khóa trước chạy.
- P(lãi) giữ sigmoid OOS24tháng như RF; Q10 chính của hai ứng viên là Q10 học trực tiếp; đồng thời báo Q10 residual cùng công thức RF để tách phần ảnh hưởng phương pháp rủi ro.
- RF/zero lấy từ lượt stationary-v2 nếu hash frame, thuật toán và corelibraries khớp; kiểm tra ghép ngày/actual, không so khác tập. Q90 RF lấy phân vị residual OOS theo cùng điều kiện maturity.
- Ngưỡng Mua/Bán cố định1% cho tất cả. Chấm MAE/theo năm/bootstrap khối, Brier/ECE, Q10 pinball/coverage, Q10–Q90 coverage/độ rộng, danh mục bid/ask/cash và cửa sổ tín hiệu không chồng lấn.
- Không thử thêm cấu hình sau khi xem điểm. Lịch sử đã dùng phát triển, không cấp validated.
- Cài hai package vào .cache/challenger-deps --no-deps; không đổi thư viện mô hình đang chạy hoặc campaign đã khóa.

## Tasks

- [x] RED/GREEN adapter quantile, shape/finite/coherence và chuyển đơn vị spread.
- [x] RED/GREEN runner thời gian: purge, calibration không tương lai, cùng tập ngày, bảo vệ artifact đang chạy.
- [x] Chạy thật, lưu manifest/predictions/report và so sánh trên cùng ngày.
- [x] Rà soát độc lập, kiểm thử và kết luận; dashboard giữ RF đã kích hoạt.

## Ledger

- Hai package cài riêng không dependencies; LightGBM4.7.0/CatBoost1.2.10, corelibs giữ nguyên và fingerprint campaign không đổi.
- 4 kiểm thử mới đạt, gồm actual CPU fits cả hai thuật toán; causal unit test thay nhãn tương lai không đổi dự báo trước maturity.
- Lượt quantile-v1 hoàn tất với 2.107 dòng mỗi ứng viên, 1.300 dòng đã đáo hạn/chấm và đủ calibration. Bốn ứng viên cùng ngày/actual; tất cả train/calibration exit <foldstart.
- Kết quả MAE: RF9,33, CatBoost9,78, LightGBM9,97, zero8,97 điểm %. NativeQ10–Q90 coverage Cat15,8%/LGBM25,1% so mục tiêu80%; không chọn hai ứng viên.
- Rà soát độc lập tự chạy 4 tests và kiểm tra artifact/hash, không phát hiện lỗi quan trọng. Chỉ so toàn phương pháp, không quy mọi khác biệt cho họ thuật toán.
- Bộ 91 tests: 89pass/2skipped. Báo cáo docs/quantile-challengers-results-2026-10-25.md; giữ active model/dashboard/campaign nguyên trạng, không commit/deploy.
