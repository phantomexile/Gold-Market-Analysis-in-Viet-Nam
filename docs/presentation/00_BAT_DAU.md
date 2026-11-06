# Bắt đầu thuyết trình dự án

Mở lần lượt các tài liệu dưới đây. Mỗi phần có điểm mở mã nguồn tương ứng; có thể trình bày toàn bộ trong khoảng 8–10 phút tùy thời lượng demo.

| Thứ tự | Tài liệu | Nội dung chính |
|---|---|---|
| 1 | [01 — Cấu trúc dự án](01_CAU_TRUC.md) | Tệp nào thu thập, xử lý, huấn luyện, kiểm định và hiển thị |
| 2 | [02 — Luồng dữ liệu](02_LUONG_DU_LIEU.md) | Đi từ báo giá tới dashboard; giải thích công thức lợi suất |
| 3 | [03 — Mô hình và kiểm định](03_MO_HINH.md) | RF trung vị/RF nhỏ, MAE, P(lãi), Q10 và giới hạn |
| 4 | [04 — Các bước demo](04_DEMO.md) | Mở dashboard, đọc ngày dữ liệu, chỉ ra mô hình và trạng thái |
| 5 | [05 — Câu hỏi thường gặp](05_CAU_HOI.md) | Cách trả lời các câu hỏi về mô hình và độ tin cậy |
| Tra mã | [code/README.md](code/README.md) | Bảy bản mã có comment tiếng Việt, theo thứ tự xử lý |

Các bản mã trong `code/` chỉ để đọc, không phải điểm chạy pipeline. Comment được đặt tại phần validation, công thức, chia tập thời gian, hiệu chỉnh và xuất dữ liệu. Có đường dẫn đến mã vận hành và manifest đối chiếu; logic của từng bản sao được kiểm tra giống mã gốc bằng cây cú pháp.

**Ba điều cần nói chính xác:** kỳ hạn là 1/3/5 tháng lịch; tín hiệu dự báo trực tiếp khác trạng thái đã kiểm định; số liệu và ngày snapshot phải đọc từ tệp/dashboard đang mở. Không có slide hoặc biểu đồ nào tự chứng minh hiệu quả giao dịch.
