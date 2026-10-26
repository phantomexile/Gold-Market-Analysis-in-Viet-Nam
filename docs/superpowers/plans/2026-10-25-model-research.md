# Cải tiến mô hình: chẩn đoán và đối chứng theo thời gian

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thực hiện bước 1–3 đã duyệt: chẩn đoán sai số và chạy đối chứng lợi suất với lựa chọn cấu hình chỉ dùng kết quả quá khứ.

**Architecture:** Công cụ nghiên cứu độc lập đọc model frame và báo cáo lịch sử hiện có. Không sửa snapshot, giao thức tiến cứu, ngưỡng validated, dashboard hoặc sổ giao dịch. Lịch sử đã xem chỉ phục vụ phát triển.

**Tech Stack:** Python, pandas, NumPy, scikit-learn có sẵn.

**Spec:** Kế hoạch 5 bước trong chat; người dùng duyệt triển khai bước 1–3 ngày 2026-10-25.

## Global Constraints

- UTF-8 không BOM, bình luận tiếng Việt; không commit/deploy.
- Tận dụng checkout hiện tại chứa các thay đổi đã được duyệt; không chuyển sang checkout thiếu các tệp chưa commit.
- Không thêm dữ liệu ngoài lake, không điều chỉnh chính sách kiểm định để tạo kết quả đạt.
- Chỉ dùng danh sách feature_columns; từ chối cột nhãn, tương lai, ngày hoặc mục tiêu lọt vào danh sách.
- Huấn luyện vào đầu mỗi tháng; train có exit_date < fold_start, lựa chọn và điền thiếu chỉ fit train.
- Cố định danh sách ứng viên trước khi chạy. Mỗi năm chọn ứng viên bằng dự báo ngoài mẫu 24 tháng trước đã đáo hạn, tối thiểu 6 tháng và 120 dòng; thiếu thì dùng lợi suất 0.
- So sánh cùng tập ngày. Báo cáo theo năm/tháng, độ lệch có dấu và số cửa sổ không chồng lấn; không coi dòng ngày là độc lập.
- Bước 4–5 chưa triển khai: chưa hiệu chỉnh lại xác suất/Q10, chưa thay mô hình sản xuất.

## Review Focus

- Nhãn tương lai hoặc thay đổi nhãn năm đánh giá không làm đổi lựa chọn cấu hình năm đó hoặc dự báo trước ngày nhãn đáo hạn.
- Cuối tháng, năm nhuận, khoảng trống báo giá: đối chiếu đúng tháng lịch và phiên đầu tiên đủ điều kiện.
- Nhãn NaN, vô hạn, thiếu cột, ngày trùng và danh sách đặc trưng chứa mục tiêu: báo lỗi hoặc loại có thống kê rõ.
- Các ứng viên được chấm trên cùng ngày; thiếu feature/không đủ train không được âm thầm làm đẹp MAE.
- Báo cáo mới không ghi validated, không ghi đè artifact sản xuất; manifest gắn hash dữ liệu/mã/cấu hình và phiên bản thư viện.

## Task 1: Chẩn đoán dữ liệu và lỗi hiện tại

**Files:** Create `scripts/analysis/model_diagnostics.py`, `tests/test_model_research.py`.
- [x] Viết kiểm thử RED: nhãn sai, báo giá thiếu, sai số theo năm, nhóm xác suất, lợi suất quá khứ.
- [x] Thêm audit_targets(frame, horizons), diagnose_history(predictions, frame) trả cấu trúc JSON hữu hạn.
- [x] Kiểm thử GREEN: lỗi nhãn được phát hiện, ECE tính có trọng số, thống kê tách kỳ hạn.

## Task 2: Khung đối chứng và lựa chọn cấu hình

**Files:** Create `scripts/analysis/model_research.py`; mở rộng `tests/test_model_research.py`.
- [x] RED: purge nhãn, lựa chọn đặc trưng train-only, cấu hình chỉ dùng kết quả đã biết, baseline khi thiếu bằng chứng.
- [x] Thêm registry cố định: 0, trung vị toàn lịch sử/3 năm; Ridge top20 toàn lịch sử/3 năm; Ridge bỏ từng nhóm nội địa/quốc tế/lịch; RF top20 toàn lịch sử/3 năm; RF gốc top120/350 cây làm đối chứng.
- [x] Huấn luyện tháng từ 2021 phục vụ lựa chọn; chấm nghiên cứu từ 2023. Tính điểm lựa chọn bằng trung bình MAE theo tháng để tháng nhiều dòng không lấn át.
- [x] GREEN: kiểm tra chống nhìn tương lai và cùng tập mẫu, báo cáo từng ứng viên cùng chuỗi lựa chọn thực tế theo năm.

## Task 3: Chạy và xuất báo cáo nghiên cứu

**Files:** Create `scripts/analysis/run_model_research.py`, `docs/model-research-2026-10-25.md`; outputs dưới `data/lake/modeling/research/`.
- [x] RED: xuất manifest, bảo vệ thư mục đã tồn tại, JSON không NaN và trạng thái nghiên cứu.
- [x] CLI chụp hash trước chạy, ghi cấu hình và phiên bản thư viện, lưu audit/diagnostics/predictions/selections/report.
- [x] Chạy thật lake hiện có, ghi kết quả kể cả thất bại; so sánh cùng lịch tháng, tách khỏi RF đóng băng năm hiện tại.
- [x] Kiểm thử toàn bộ, kiểm tra Unicode/diff, rà soát độc lập và kết luận bước 4 nên giải quyết gì.

## Ledger

- Ruling: Làm trong checkout đang chứa mô hình đã duyệt; chỉ tạo công cụ/artifact nghiên cứu riêng, giữ toàn bộ thay đổi có sẵn. Không commit theo yêu cầu người dùng.
- Ruling: Huấn luyện tháng chỉ áp dụng trong nghiên cứu; chuyển vận hành sang lịch tháng là bước thay mô hình sau khi có kết quả và được duyệt.
- Ruling: Khóa ứng viên trước chạy; không thêm cấu hình sau khi xem kết quả nhằm ép đạt.
- Task 1: complete — nhãn 1/3/5 tháng không sai ngày thoát/lợi suất; sai số mô hình cũ tăng mạnh ở 2025–2026, đặc biệt bias dương 42,08 điểm % cho 5 tháng năm 2026.
- Task 2: complete — 11 kiểm thử mới đạt, gồm purge, feature selection, selection theo năm, 119/120 dòng, 5/6 tháng, ngày thoát 31/12 và 01/01, JSON và output độc quyền.
- Ruling: Danh sách feature_columns.json cũ có 39 cột không còn trong frame. Thí nghiệm v1 dừng trước fit với KeyError; đã thêm regression test và resolve_features dùng schema builder hiện tại, xuất 658 tên trong thư mục nghiên cứu. Không sửa danh sách cũ hoặc mã sản xuất. v2 là lần chạy hoàn chỉnh dự kiến.
- Final review: reviewer độc lập không phát hiện lỗi quan trọng; hai đề nghị test biên đã bổ sung và đạt. Mã nguồn được giữ nguyên trong lúc chạy để đối chiếu hash cuối.
- Task 3: complete — v2 hoàn tất, hash trước/sau của dữ liệu/mã/chính sách và snapshot/validation report/ledger/dashboard khớp. 69 tests OK, 2 skipped; 11 tests nghiên cứu mới đạt.
- Result: RF tháng có MAE 5,39/10,02/15,06 so với RF năm 6,23/12,44/16,71. Chuỗi lựa chọn trước năm có MAE 3,77/11,12/13,88, chưa đạt giảm 5% so với baseline 3,70/8,97/14,07. Không thay mô hình vận hành hoặc nới ngưỡng.
- Handoff: xem docs/model-research-2026-10-25.md; ưu tiên nghiên cứu đặc trưng dạng tỷ lệ/biến động và độ thích ứng trước khi đưa xác suất/Q10 mới vào vận hành. Chưa chạy thêm cấu hình sau khi xem kết quả.
