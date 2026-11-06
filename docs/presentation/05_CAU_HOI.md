# 05 — Câu hỏi thường gặp khi bảo vệ

**Vì sao dùng Random Forest?** RF mô hình hóa quan hệ phi tuyến giữa các biến tỷ lệ, xu hướng và biến động. Đây là lựa chọn được thử nghiệm, cần so với đối chứng đơn giản; tên thuật toán không tự bảo đảm độ chính xác.

**Vì sao không dùng một mô hình cho cả ba kỳ hạn?** Có thể dùng chung họ thuật toán, nhưng lợi suất 1/3/5 tháng là ba biến mục tiêu khác nhau. Dự án chọn riêng theo sai số lịch sử từng kỳ hạn. Một RF đa đầu ra là phương án khác cần đánh giá lại.

**Vì sao RF trung vị ở 1 tháng?** Trong lượt lựa chọn, nó có MAE thấp hơn RF nhỏ ở 1 tháng. Nó dùng absolute_error và học trực tiếp lợi suất ròng; không kết luận riêng loss tạo ra toàn bộ cải thiện vì target cũng khác.

**Tránh rò rỉ dữ liệu bằng cách nào?** Ghép theo thời điểm khả dụng, trễ đầu vào quốc tế, học phép điền thiếu từ train và chỉ nhận nhãn có ngày thoát trước fold. Ngày phát thuộc quá khứ chưa chắc nhãn đã đáo hạn.

**Có thể nói mô hình đã dự báo tốt không?** Chỉ nêu đúng chỉ số của lượt đánh giá và đối chứng cùng ngày. Các kết quả hiện tại còn giới hạn; không gọi một dự báo mới chưa đáo hạn là thành công, không dùng tín hiệu trực tiếp thay bằng chứng validated.

**Q10 có nghĩa chỉ có thể lỗ tới mức đó?** Không. Đó là phân vị ước lượng; mô hình có thể sai lệch hiệu chỉnh, và lợi suất thực tế có thể thấp hơn Q10.

**Sao có tin tức mà RF không dùng mọi tin?** Hiển thị bối cảnh khác với đầu vào huấn luyện. Tin hồi cứu cần bằng chứng thời điểm khả dụng, nếu không có sẽ gây nhìn trước tương lai.

**Cải thiện tiếp bằng cách nào?** Kiểm tra dữ liệu/đặc trưng, so loss trên cùng target, giảm độ phức tạp khi cần; khóa cách đánh giá trước và luôn so với zero. Muốn xác nhận thực tế cần ghi dự báo mới trước khi biết kết quả, rồi chờ đáo hạn.

**Vì sao comment mô hình nằm trong bản đọc riêng?** Bản khóa đang đóng dấu toàn bộ nội dung tệp. Bản đọc giúp giải thích từng khối mà không vô tình làm khác dấu vân tay; manifest và so sánh AST xác nhận nó giữ nguyên logic mã vận hành.
