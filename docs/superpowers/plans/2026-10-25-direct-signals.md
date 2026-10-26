# Tín hiệu trực tiếp Mua / Bán / Quan sát

Người dùng duyệt tín hiệu phản ánh trực tiếp dự báo dù mô hình chưa đạt kiểm định. Chỉ thay cách quyết định/hiển thị tín hiệu, giữ dự báo điểm hiện tại vì chưa có ứng viên nghiên cứu vượt baseline đủ điều kiện. Không tự ghi lệnh giao dịch hoặc nâng trạng thái validated.

## Thiết kế

- Dùng lợi suất ròng mua mới đã tính chênh lệch mua/bán: r_buy = future_buy / sell_now − 1.
- Với vàng đang giữ, so bán ngay với tiếp tục giữ: r_hold = future_buy / buy_now − 1 = (1+r_buy) * sell_now / buy_now − 1. Không coi lợi suất mua mới âm là lý do bán nếu giá mua lại tương lai vẫn cao hơn bán ngay.
- Mặc định vùng trung tính 1%: Mua nếu r_buy > 1%; Bán nếu r_hold < −1%; còn lại Quan sát. Biên bằng đúng ±1% là Quan sát. Đây là tham số nghiệp vụ đề xuất, chưa tối ưu theo lịch sử.
- Giữ ba kỳ hạn 1/3/5 tháng; tín hiệu chính lấy kỳ hạn 3 tháng, ghi rõ trên giao diện. Không có kỳ hạn chính thì Quan sát.
- Điểm kiểm định, xác suất và Q10 là chi tiết tham khảo, không chặn tín hiệu trực tiếp. Không sửa báo cáo kiểm định để tạo validated.
- Vẫn yêu cầu đúng ngày dữ liệu, đủ ba kỳ hạn duy nhất, giá hợp lệ, dự báo hữu hạn và nguồn giá đầu vào khớp giá bán ghi trong snapshot. Sai thì Quan sát cùng lý do dữ liệu.
- Giao diện chính: tín hiệu + một câu giải thích mỗi kỳ hạn. Chỉ số, hai mức kiểm định và quy tắc nằm trong mục Chi tiết đóng mặc định. Bán được ghi rõ áp dụng cho vàng đang giữ.
- UTF-8 không BOM, bình luận tiếng Việt; giữ thay đổi có sẵn, không commit/deploy.

## Các bước

- [x] RED/GREEN hàm tín hiệu: mua, bán, vùng spread quan sát, biên 1%, NaN/giá sai.
- [x] RED/GREEN API: chưa validated vẫn mua/bán trực tiếp; ngày sai/thiếu giá vẫn quan sát; giữ API kiểm định cũ bằng mode riêng.
- [x] Rút gọn UI; kiểm thử DOM escape/null, Chi tiết đóng mặc định và tín hiệu Bán.
- [x] Dựng lại JSON từ snapshot hiện có, chạy kiểm thử và kiểm tra giao diện 1440/390px.
- [x] Rà soát độc lập và kiểm tra UTF-8/diff; không huấn luyện lại hoặc ghi vào sổ giao dịch.

## Kết quả và quyết định

- Public `build_recommendations` mặc định direct; `signal_mode='validated'` giữ chế độ cũ để đối chiếu. Bộ kiểm thử cũ nhập hàm chế độ cũ, bộ trực tiếp kiểm tra API công khai mới.
- Tín hiệu hiển thị có `signal`, `buy_signal`, `sell_signal`; cờ mua qua kiểm định cũ nằm trong `validated_buy_signal`. Status và báo cáo lịch sử/tiến cứu không bị đổi thành validated.
- Snapshot ngày 2026-10-24: 1 tháng Quan sát (mua mới −2,31%, giữ thêm so bán ngay −0,20%); 3 tháng Mua (+10,18%); 5 tháng Mua (+14,97%). Tín hiệu chính Mua theo 3 tháng. Đây là dự báo, không phải lợi nhuận thực tế.
- Không chọn mô hình nghiên cứu tốt nhất sau khi xem lịch sử; dùng dự báo RF hiện có, không chạy huấn luyện lại chỉ để đổi giao diện.
- Rà soát độc lập tìm thấy giá đầu vào thiếu vẫn có thể phát tín hiệu. Đã thêm kiểm thử RED cho trường rỗng/sai/NaN/âm, bắt buộc giá đầu vào hữu hạn/dương/khớp frame và xác nhận GREEN.
- Bộ 72 kiểm thử Python: 70 đạt, 2 bài nguồn trực tiếp bỏ qua. JavaScript hiển thị thiếu số liệu/escape/legacy/direct/Chi tiết đóng và 7 tình huống cập nhật đạt.
- Chrome thực ở 1440/390px: ba tín hiệu đúng, chi tiết đóng mặc định, mở được, không tràn ngang; đã xem ảnh `.cache/direct-signals-1440.png` và `.cache/direct-signals-390.png`. Chỉ kiểm tra phần tín hiệu, không phải toàn bộ biểu đồ CDN.
- Chỉ dựng lại web/data/gold_dashboard_data.json; giữ snapshot_forecasts.csv, báo cáo kiểm định và paper_trading_ledger.csv. Không commit/deploy.
