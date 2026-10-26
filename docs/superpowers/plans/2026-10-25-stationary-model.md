# Cải thiện mô hình 3 tháng bằng tỷ lệ, biến động và kiểm chứng tín hiệu

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Thực hiện kế hoạch người dùng duyệt: đầu vào gọn, đối chứng mô hình, đánh giá Mua/Bán, hiệu chỉnh xác suất/Q10 và khóa ứng viên để theo dõi dữ liệu mới.

**Spec:** Kế hoạch sáu bước trong chat ngày 25/10/2026. Ưu tiên kỳ hạn 3 tháng; giữ giao diện ba tín hiệu, không commit/deploy.

**Architecture:** Nghiên cứu độc lập đọc frame hiện tại. Đặc trưng chỉ tính từ hiện tại/quá khứ; mô hình dự báo thay đổi giá mua lại rồi đổi về lợi suất mua mới có spread. So sánh bảy ứng viên cố định, lựa chọn mô hình/ngưỡng chỉ bằng dữ liệu đã biết trước tháng. Calibrator và Q10 chỉ dùng sai số ngoài mẫu đã đáo hạn. Xuất báo cáo, bản khóa ứng viên và nhật ký shadow; không tuyên bố validated bằng lịch sử đã xem.

## Global Constraints

- UTF-8 không BOM, bình luận tiếng Việt; giữ toàn bộ thay đổi có sẵn trong checkout.
- Không sử dụng tin/sự kiện hồi cứu, không tự thu thập bên ngoài. Kiểm tra nhãn hiện có trước fit.
- Cố định bảy ứng viên: zero, no_price_change, median, Ridge alpha10, ElasticNet alpha0.001/l1_ratio0.5, RF100/depth4/leaf30, GradientBoosting Huber100/depth2/leaf30.
- Tất cả mô hình học 5 năm gần nhất; fit vào đầu tháng, chỉ nhãn exit_date < đầu tháng; imputer/scaler chỉ fit train. Baseline zero có r_buy=0, baseline no_price_change có future_buy=buy_now.
- Chọn cấu hình mỗi tháng theo MAE bình quân tháng từ 24 tháng OOS trước đã đáo hạn, tối thiểu 120 dòng/6 tháng; chỉ chọn ứng viên nếu cải thiện ít nhất 5% so zero, còn lại zero. Không bổ sung ứng viên sau khi xem kết quả.
- Thử ngưỡng 0,5%/1%/2%; lựa chọn ngưỡng bằng kết quả danh mục quá khứ đã biết; thiếu ba giao dịch hoàn tất thì giữ 1%.
- P(lãi) sigmoid học trên dự báo ngoài mẫu đã đáo hạn; Q10 so sánh GBR quantile với point + phân vị residual quá khứ. Dùng residual Q10 làm phương pháp khóa trước chạy, không chọn sau khi nhìn tập đánh giá.
- Backtest quyết định tháng, một vị thế hoặc tiền mặt, giao dịch đúng giá bán/mua, mark-to-market bằng giá mua; không bán khống. Mua-và-giữ và tiền mặt là đối chứng. Tách độ đúng Mua/Bán bằng các cửa sổ 3 tháng không chồng lấn.
- Khoảng bất định dùng bootstrap khối ba tháng trên MAE bình quân tháng, không coi mọi dòng ngày là độc lập.
- Bản khóa ở chế độ shadow; chỉ thay mô hình mặc định nếu vượt tiêu chí phát triển đã khóa và có kết luận rõ. Không đổi ngưỡng kiểm định hoặc tự thêm số mẫu tiến cứu.
- Freeze thuật toán/đặc trưng/thư viện/ngưỡng/lịch refit. Ghi dự báo mới bất biến từ ngày sau ngày khóa; snapshot cũ chỉ là bản tham chiếu, không tính bằng chứng độc lập.

## Review Focus

- Thay giá/nhãn tương lai không làm thay đặc trưng, lựa chọn, calibrator hoặc dự báo trước thời điểm thông tin có thể biết.
- Mua mới âm do spread không đồng nghĩa bán vàng đang giữ; P/Q10 cùng đơn vị lợi suất ròng.
- Lợi nhuận danh mục đã tính bid/ask, có vị thế/cash và mark-to-market từng ngày; không nhân cộng các khoản lợi suất chồng lấn.
- File thiếu/hỏng, chỉ một lớp nhãn, ít hiệu chỉnh, thiếu features: biểu diễn chưa đủ bằng chứng, không bịa xác suất hoặc phát validated.
- Protocol/hash không khớp phải dừng ghi shadow; thay bản khóa không được kế thừa thành tích; dữ liệu cũ không trở thành dự báo mới.

## Tasks

- [x] Task 1: RED/GREEN `stationary_features.py`, `tests/test_stationary_model.py`: đặc trưng tỷ lệ/biến động train-only, tối đa 40 cột, invariant khi đổi nhãn/giá tương lai.
- [x] Task 2: RED/GREEN `stationary_research.py`: point/quantile/calibration, OOS tháng, lựa chọn model tháng và ngưỡng quá khứ; kiểm tra same dates và maturity.
- [x] Task 3: RED/GREEN `stationary_evaluation.py`: backtest bid/ask/cash, đánh giá riêng Mua/Bán, bootstrap và kiểm định chất lượng; không gọi lịch sử là validated.
- [x] Task 4: CLI `run_stationary_research.py`: khóa manifest, chạy thật, xuất preds/selections/report/docs; so sánh mô hình hiện tại trên cùng ngày.
- [x] Task 5: RED/GREEN `stationary_shadow.py`: bản khóa, dự báo mới bất biến, maturing; tích hợp refresh tùy chọn khi có protocol shadow, không đổi UI hoặc trạng thái model hiện tại nếu ứng viên chưa đạt.
- [x] Task 6: kiểm thử toàn bộ, rà soát độc lập, Unicode/hash/diff, chạy record-only và kết luận trung thực.

## Ledger

- Ruling: Dùng checkout hiện tại vì chứa dữ liệu/mã đã duyệt chưa commit. Chỉ thêm mô-đun độc lập và hook shadow; không reset/commit.
- Ruling: Không thể tạo ngay bằng chứng tương lai. Hoàn thiện cơ chế thu thập và báo rõ mức bằng chứng hiện có; kết quả nghiên cứu thất bại vẫn phải giữ nguyên.
- Task 1–3: complete — 34 features, 7 cấu hình, OOS từ 2021, chấm từ 2023; không thay registry sau khi xem kết quả. Mô hình học hold return và quy đổi spread theo giá test.
- Task 4: complete — v1 chạy thành công; sau sửa lỗi fingerprint, v2 chạy lại cùng mô hình/tham số và lưu report/predictions/selections/manifest. Mã/dữ liệu/artifact vận hành không đổi trong từng lượt fit.
- Final review: reviewer phát hiện fingerprint thiếu shared validation/upstream builder; đã có test RED, dùng model_source_fingerprint + stationary/helper sources, xác nhận GREEN và reviewer đồng ý. Bổ sung kiểm tra NaN/P ngoài [0,1] trước tạo journal.
- Task 5: complete — protocol cuối 9a00600ea79882241950320f, validation_start 2026-10-26. Collector record-only chạy thành công, snapshot 24/10 không thành bằng chứng mới. Hook kiểm tra bằng cả hai trường hợp có/không active lock.
- Result: RF mới MAE 9,33 điểm %, tốt hơn RF tháng cũ 10,02 khoảng 6,9%, nhưng chưa vượt zero 8,97. Brier 0,327/ECE30,53 điểm %/Q10breach17,23% chưa đạt. Danh mục +52,3% kém buy-hold +107,9%, chỉ2vòng hoàn tất. Không thay mô hình mặc định.
- Handoff: docs/stationary-model-results-2026-10-25.md. Mô hình nghiên cứu cải thiện nhưng chưa chứng minh đáng tin cậy; tiếp tục dữ liệu mới, không dùng lịch sử phát triển làm bằng chứng độc lập.
- Task 6: complete — 85 Python tests (83 pass, 2 skipped); JS hiển thị/cập nhật đạt; xác nhận 14.749 dự báo causal, paired1300rows, source/protected hashes khớp, JSON strict/UTF-8 không BOM/diff đạt. Collector record-only chạy thành công hai lần, journal vẫn0 đúng snapshot cũ.
