# Cải tiến mô hình: kết quả bước 1–3 ngày 25/10/2026

Đã hoàn tất chẩn đoán và đối chứng trên dữ liệu đến 24/10/2026. Kết quả vẫn chưa đủ để thay mô hình đang vận hành hoặc cấp `validated`. Chỉ đánh giá dự báo lợi suất; chưa hiệu chỉnh lại xác suất và Q10.

## Phạm vi và cách làm

- Đọc lake hiện có; không thu thập thêm và không thay dữ liệu gốc.
- Huấn luyện lại vào đầu tháng, chỉ dùng nhãn có ngày thoát nhỏ hơn đầu tháng.
- Cố định 11 ứng viên trước khi chạy: lợi suất 0; trung vị toàn lịch sử/3 năm; Ridge top20 toàn lịch sử/3 năm; Ridge bỏ riêng nhóm nội địa/quốc tế/lịch; RF top20 toàn lịch sử/3 năm; RF top120 350 cây với tham số mô hình hiện tại.
- Lịch sử 2021–2022 phục vụ lựa chọn ban đầu; đánh giá nghiên cứu từ 2023 đến những dự báo đã đáo hạn tại snapshot.
- Đầu mỗi năm chọn ứng viên bằng MAE bình quân tháng trong 24 tháng trước đã đáo hạn, tối thiểu 6 tháng và 120 dòng. Cấu hình khóa cho năm đó, mô hình vẫn được fit lại hàng tháng.
- Mỗi kỳ hạn chấm các ứng viên trên cùng tập ngày. Có 1.351/1.300/1.240 ngày đánh giá và 45/15/9 cửa sổ không chồng lấn cho 1/3/5 tháng; các dòng ngày không phải thử nghiệm độc lập.
- Không tự thay mô hình dựa vào người thắng sau khi nhìn toàn bộ bảng kết quả.

## Những gì xác nhận được

1. Không phát hiện nhãn lợi suất, ngày thoát hoặc giá mua/bán không hợp lệ khi đối chiếu nội bộ model frame. Kiểm tra này chưa xác minh độc lập từng báo giá gốc và thời điểm nguồn công bố.
2. Sai số mô hình đóng băng theo năm tăng mạnh trong 2025–2026. Kỳ hạn 5 tháng năm 2026 có MAE và bias dương đều khoảng 42,08 điểm phần trăm: mô hình dự báo quá cao trong cả tập đánh giá năm này. Năm 2025 lại thiên về dự báo thấp, nên sửa bằng một hằng số bias chung không đủ giải quyết.
3. Danh sách đặc trưng lưu cũ chứa 39 tên không còn trong frame, gồm tên kỳ hạn ngày cũ. Công cụ nghiên cứu lấy schema từ builder hiện tại và lưu 658 tên vào thư mục nghiên cứu; không sửa file cũ. Lượt v1 dừng trước huấn luyện vì schema cũ; v2 là lượt hoàn tất.
4. Trong phép thử Ridge, bỏ nhóm quốc tế giảm MAE ở cả ba kỳ hạn. Đây là đóng góp thực nghiệm của phép bỏ nhóm cụ thể, chưa chứng minh dữ liệu quốc tế sai hoặc nên bỏ khỏi mọi mô hình.
5. Danh sách đặc trưng đã xác minh vẫn có phạm vi tin tức rất hẹp. Chưa có đối chứng chứng minh tin tức là nguyên nhân gây sai số chung.

## Đổi lịch huấn luyện giúp được bao nhiêu?

MAE dưới đây tính bằng **điểm phần trăm lợi suất**; càng thấp càng tốt. Cột RF tháng giữ tham số RF hiện tại, dùng schema đặc trưng hiện tại và lựa chọn train-only trong từng tháng. Không thay mô hình vận hành theo cột này.

| Kỳ hạn | RF đóng băng năm hiện tại | RF huấn luyện tháng | Mốc dự báo 0 |
|---|---:|---:|---:|
| 1 tháng | 6,23 | 5,39 | 3,70 |
| 3 tháng | 12,44 | 10,02 | 8,97 |
| 5 tháng | 16,71 | 15,06 | 14,07 |

Huấn luyện thường xuyên hơn giảm sai số so với cách đóng băng năm, nhưng riêng thay đổi này chưa đủ vượt baseline.

## Lựa chọn cấu hình bằng thông tin có trước từng năm

| Kỳ hạn | MAE chuỗi được chọn | MAE mốc 0 | Cải thiện so với mốc 0 |
|---|---:|---:|---:|
| 1 tháng | 3,77 | 3,70 | −1,9% |
| 3 tháng | 11,12 | 8,97 | −24,0% |
| 5 tháng | 13,88 | 14,07 | +1,3% |

Không kỳ hạn nào đạt ngưỡng giảm MAE ít nhất 5%. Với 3 tháng, lựa chọn Ridge bỏ nhóm nội địa cho năm 2026 dựa vào kết quả trước đó lại có MAE 24,33 so với mốc 10,89 trong năm 2026; kết quả này cho thấy rủi ro của việc tin rằng ứng viên tốt trong quá khứ sẽ tiếp tục tốt.

Nếu nhìn toàn bộ giai đoạn rồi chọn ứng viên tốt nhất, Ridge bỏ nhóm quốc tế ở kỳ hạn 5 tháng có MAE 13,43, tốt hơn mốc 14,07 khoảng 4,5%. Vẫn chưa đạt 5%, và lựa chọn sau khi xem kết quả không phải bằng chứng độc lập.

## Quyết định sau nghiên cứu

- Giữ mô hình đang vận hành và trạng thái kiểm định hiện tại; không quảng bá ứng viên nghiên cứu thành mô hình đã được xác nhận.
- Chưa ưu tiên đưa bộ hiệu chỉnh xác suất/Q10 mới vào vận hành khi dự báo lợi suất và việc chọn cấu hình còn chưa ổn định.
- Đề xuất lượt nghiên cứu tiếp theo giới hạn trước các đặc trưng dạng tỷ lệ/biến động thay cho mức giá tuyệt đối, và kiểm tra lịch chọn cấu hình có thích ứng sớm hơn với giai đoạn mới. Đây là đề xuất cho lượt sau, chưa triển khai hoặc thử thêm sau khi xem bảng hiện tại.
- Kết quả 2023–2026 vẫn là lịch sử phát triển đã xem. Nếu chọn phiên bản mới sau này, phải khóa phiên bản và thu thập bằng chứng tiến cứu mới; không nhập các số mẫu này vào tiến độ thực tế.

## Bằng chứng và chạy lại

- Báo cáo đầy đủ: [report.md](../data/lake/modeling/research/2026-10-25-monthly-v2/report.md).
- `manifest.json`: cấu hình khóa, hash dữ liệu/mã/chính sách, phiên bản thư viện, thời điểm bắt đầu/kết thúc và xác nhận artifact vận hành giữ nguyên.
- `target_audit.json`, `input_quality.json`, `historical_diagnostics.json`: kiểm tra nhãn, phạm vi đầu vào, lỗi theo năm/xu hướng, nhóm xác suất và tháng sai nhiều.
- `predictions_1m.csv`, `predictions_3m.csv`, `predictions_5m.csv`: từng dự báo, mốc train, số mẫu train và tên đặc trưng được chọn.
- `selections.json`, `report.json`: lựa chọn trước mỗi năm, điểm từng ứng viên/theo năm, phép bỏ nhóm và chuỗi được chọn.

Chạy `scripts/analysis/run_model_research.py` với Python có pandas/NumPy/scikit-learn và thư viện dự án. Mỗi lần chạy phải dùng thư mục mới bên trong `data/lake/modeling/research`; công cụ từ chối ghi đè một lần chạy có sẵn.

Kiểm tra: bộ 69 bài kiểm thử toàn dự án có 67 bài đạt và 2 bài nguồn trực tiếp được bỏ qua; 11 bài mới kiểm tra purge, schema, lựa chọn đặc trưng, ngưỡng 119/120 dòng và 5/6 tháng, ngày thoát đúng ngày chốt, dữ liệu so sánh cùng ngày, JSON và bảo vệ thư mục. Rà soát độc lập không phát hiện lỗi quan trọng. Không commit hoặc deploy.
