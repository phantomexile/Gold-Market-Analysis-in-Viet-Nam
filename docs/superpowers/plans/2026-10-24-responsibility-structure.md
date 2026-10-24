# Kế hoạch tách file theo trách nhiệm

**Mục tiêu:** Tổ chức lại mã hiện có theo phương án người dùng đã chọn, giữ nguyên nghiệp vụ và các điểm chạy cũ.

**Kiến trúc:** `src/gold_collectors/modeling` chứa các module cấu hình, dữ liệu/đặc trưng, nhãn tháng lịch, huấn luyện, đánh giá và báo cáo. `decision_support.py` giữ API tương thích và điều phối. Script được nhóm trong `collection`, `processing`, `pipeline`, `analysis`, `reporting`, `maintenance`; đường dẫn cũ có lớp chuyển tiếp.

**Công nghệ:** Python, unittest, dashboard HTML/CSS/JavaScript hiện có; không thêm dependency.

**Thiết kế đã duyệt:** Phương án “tách theo trách nhiệm” trong cuộc hội thoại ngày 24/10/2026.

## Ràng buộc

- UTF-8 không BOM, bảo toàn tiếng Việt và quy tắc nghiệp vụ hiện có.
- Giữ kỳ hạn 1/3/5 tháng lịch, dữ liệu đầu vào/đầu ra và cách đánh giá hiện tại.
- Không thu thập lại dữ liệu, huấn luyện dài hoặc tạo lại báo cáo thật chỉ để kiểm tra việc chuyển file.
- Không commit, không triển khai; dùng checkout hiện tại đang sạch.

## Trọng tâm kiểm tra

- Import từ API cũ và module mới; không tạo vòng phụ thuộc.
- Chạy CLI trực tiếp và qua `python -m`; xử lý `_bootstrap` sau khi chuyển file.
- Đường dẫn tương đối và thư mục gốc không đổi khi script chuyển sang thư mục cùng cấp.
- File chuyển tiếp không thực thi công việc khi chỉ được import.
- Kết quả dựng đặc trưng, nhãn và dự báo baseline không đổi.

## Công việc

- [x] 1. Chạy kiểm thử ban đầu; thêm kiểm tra import và tương thích CLI cho cấu trúc mới.
- [x] 2. Tách `decision_support.py` bằng cách giữ nguyên thân hàm; khai báo import rõ ràng, thêm chú thích tiếng Việt cho trách nhiệm chính.
- [x] 3. Chuyển script theo nhóm chức năng, giữ lớp tương thích tại vị trí cũ; cập nhật bootstrap và các lời gọi nội bộ.
- [x] 4. Cập nhật README, bản đồ mã nguồn, hướng dẫn pipeline và launcher Windows cho vị trí mới.
- [x] 5. Chạy toàn bộ kiểm thử, kiểm tra import/CLI, cú pháp, UTF-8, diff và dữ liệu không thay đổi.

## Tiến độ và bằng chứng

- Đã kiểm tra working tree ban đầu: sạch. Những file lớn được ưu tiên tách là `decision_support.py` (1.144 dòng) và nhóm script pipeline.
- Bộ kiểm thử trước thay đổi: 26 bài, 2 bỏ qua. Sau thay đổi: 30 bài, 2 bỏ qua như trước.
- Đối chiếu AST: 31 hàm/lớp mô hình giữ nguyên; không có tham chiếu biến toàn cục bị thiếu.
- Đối chiếu dữ liệu thực: bảng đặc trưng 5.570 dòng × 826 cột và toàn bộ bảng kết quả/dự báo baseline giống bản gốc.
- 23 cặp CLI cũ/mới qua `--help` thành công (46 lần chạy). Hai CLI NHNN thiếu Playwright giống bản gốc; không thêm dependency trong việc tách file.
- 40 script nghiệp vụ và bootstrap dùng chung đã chuyển vị trí; các điểm chạy cũ chuyển tiếp sang module mới.
- Không chạy công cụ bảo trì, không huấn luyện lại mô hình nặng, không ghi lại dữ liệu/báo cáo/dashboard. Các hình mới xuất hiện đồng thời trong `docs/figures/` thuộc công việc khác và được giữ nguyên.
- Rà soát độc lập không phát hiện lỗi đáng kể do thay đổi import, bootstrap, đường dẫn hoặc điều phối.
