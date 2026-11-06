# Chuẩn hóa thư mục để thuyết trình

## Phạm vi đã được yêu cầu

Sắp xếp tài liệu và thêm comment giải thích tiếng Việt. Giữ UTF-8 không BOM, giữ nhãn tiếng Việt và không commit. Dùng checkout hiện tại; không đổi vị trí nguồn/data/config để tránh ảnh hưởng đường dẫn và bản khóa.

## Thực hiện

- [x] Kiểm tra cây thư mục, entrypoint, registry và cơ chế fingerprint.
- [x] Tạo docs/presentation theo thứ tự 00–05 và bảy bản mã đọc có chú thích, kiểm tra AST giống nguồn.
- [x] Gom sáu báo cáo mô hình theo ngày vào docs/reports/modeling và sửa liên kết.
- [x] Thêm comment trực tiếp vào server và builder JSON; không đổi logic/chuỗi hiển thị.
- [x] Cập nhật README và bản đồ mã để hướng dẫn đường đọc đúng tuyến reliability_v2.
- [x] Kiểm tra link, UTF-8, AST, fingerprint và dữ liệu vận hành; chạy kiểm thử cấu trúc/web/mô hình và rà soát độc lập.

## Quyết định quan trọng

Thuật toán đang khóa theo byte nguồn. Comment trực tiếp trong các tệp được fingerprint sẽ làm không khớp bản khóa. Không đổi cơ chế hash hoặc ký lại protocol chỉ để chú thích. Thay vào đó tạo bản đọc trong docs/presentation/code bằng scripts/reporting/prepare_presentation_sources.py; manifest lưu hash và AST kiểm tra tương đương. web/server.py và scripts/build_web_data.py nằm ngoài fingerprint nên có thể chú thích trực tiếp.

Báo cáo theo ngày giữ nguyên số liệu, chỉ thay vị trí và link. Các kế hoạch cũ được cập nhật tham chiếu đường dẫn, không sửa lịch sử kết quả. Không dọn dữ liệu tạm của công cụ hoặc sản phẩm học thuật không thuộc phạm vi.

## Bằng chứng hoàn thành

- 33 kiểm thử Python đạt trong 50,02 giây: cấu trúc/import/CLI, web update, tín hiệu, snapshot refresh, stationary model và kỳ hạn.
- Hai tệp kiểm thử Node đạt, bao gồm bảy tình huống cập nhật/khôi phục và hiển thị snapshot.
- Hai fingerprint mô hình giữ nguyên; hash registry, model frame, snapshot và dashboard không đổi. Hai tệp comment trực tiếp có AST giống trước.
- Bảy bản mã đọc có AST giống nguồn và SHA-256 khớp manifest; sáu báo cáo giữ nguyên nội dung ngoài đường dẫn link đã sửa.
- Các link tài liệu mới hợp lệ, các tệp mới/sửa kiểm tra UTF-8 không BOM. Bằng chứng máy đọc: .cache/presentation-structure-verification.json.
- Review độc lập xác nhận tương đương và link. Một comment nói builder không huấn luyện là chưa đúng: active loader có thể fit RF và ghi shadow. Đã sửa comment và hướng dẫn demo để phản ánh đúng tác dụng của việc dựng JSON.
- Không chạy cập nhật, dựng lại JSON hoặc kích hoạt model trong lượt chuẩn hóa này; không commit.
