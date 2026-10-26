# Kết quả thử LightGBM Quantile và CatBoost MultiQuantile

Đã chạy thực tế hai thuật toán cho kỳ hạn ba tháng. Với cấu hình cố định của lượt này, cả hai chưa cải thiện so với RF đang áp dụng. Không đổi mô hình mặc định hoặc campaign.

## Điều kiện so sánh

- LightGBM4.7.0 và CatBoost1.2.10 cài vào `.cache/challenger-deps`, không nâng cấp các thư viện của RF đang chạy.

Ghi chú dọn dẹp 25/10/2026: đã xóa thư viện thử nghiệm trong `.cache/challenger-deps` sau khi hoàn tất so sánh. Mã chạy và kết quả bên dưới vẫn được giữ để tái lập; muốn chạy lại cần cài lại đúng hai phiên bản trên. RF đang áp dụng không phụ thuộc hai thư viện này.
- Cùng frame đến 24/10/2026, 34 đặc trưng, cửa sổ train năm năm, huấn luyện đầu tháng và chỉ dùng nhãn đã đáo hạn trước đầu tháng.
- Warmup từ 2021; đánh giá từ 2023. Mỗi phương pháp có 2.107 dự báo, trong đó 1.300 đã đáo hạn để chấm, cùng ngày và cùng nhãn actual.
- LightGBM ba mô hình Q10/Q50/Q90, CatBoost một mô hình MultiQuantile. Point của hai ứng viên là Q50; RF là hồi quy với Q10 residual. Vì vậy đây là đối chứng toàn phương pháp, chưa tách riêng tác động họ thuật toán.
- Cùng cách hiệu chỉnh P(lãi) sigmoid trên 24 tháng OOS đã đáo hạn. Ngưỡng Mua/Bán cố định1%, tính đúng spread và bối cảnh mua mới/đang giữ.
- Cấu hình khóa trước chạy: 200 cây/iterations, depth4, learning_rate0,04, seed42; LightGBM15leaves/min_child40/lambda5, CatBoostl2=5. Không dò thêm tham số sau khi xem kết quả.

## Kết quả trên cùng 1.300 ngày

| Phương pháp | MAE, điểm % | Brier | ECE, điểm % | Tỷ lệ xuyên Q10 |
|---|---:|---:|---:|---:|
| RF đang dùng | **9,33** | **0,327** | **30,53** | **17,23%** |
| CatBoost MultiQuantile | 9,78 | 0,341 | 31,34 | 32,46% |
| LightGBM Quantile | 9,97 | 0,332 | 30,97 | 26,69% |
| Mốc lợi suất0 | 8,97 | 0,290 | 23,74 | 18,85% |

Cả hai chưa thắng RF hoặc mốc0 về MAE, cũng chưa đạt điều kiện Brier/ECE/Q10 hiện có. RF vẫn chưa đủ chuẩn đáng tin cậy; việc hai ứng viên kém hơn không làm RF tự đạt kiểm định.

## Khoảng dự báo và tín hiệu

| Phương pháp | Độ phủ Q10–Q90 | Độ rộng bình quân, điểm % | Lợi suất danh mục toàn kỳ |
|---|---:|---:|---:|
| RF | 58,6% | 20,80 | +52,3% |
| CatBoost | 15,8% | 5,40 | +61,4% |
| LightGBM | 25,1% | 6,78 | +61,4% |

Khoảng Q10–Q90 có mục tiêu độ phủ80%; hai ứng viên cho khoảng quá hẹp so với kết quả thực tế trong giai đoạn đánh giá. Đã sắp thứ tự phân vị theo quy tắc định trước; vẫn ghi lại 47 dòng CatBoost và 236 dòng LightGBM có phân vị giao nhau trong 1.300 dòng đã đáo hạn.

Lợi suất danh mục đã tính spread, chưa tính phí khác và là toàn kỳ nghiên cứu, không phải lãi năm hoặc lãi tương lai. Cả hai vẫn kém mốc mua-và-giữ khoảng +107,9%, nên không chọn chỉ vì +61,4% cao hơn RF.

Nếu dùng cùng công thức Q10 residual như RF, tỷ lệ xuyên Q10 giảm còn CatBoost15,15% và LightGBM14,85%; tuy nhiên pinball khoảng0,0283/0,0282 vẫn kém RF0,0237. Đây là đối chứng đã khai báo, chưa thay Q10 native bằng phương pháp khác sau khi xem điểm.

## Kết luận

- Giữ RF cải tiến đang áp dụng cho ba tháng; 1/5 tháng không đổi.
- Hai cấu hình đã thử chưa tạo mô hình đáng tin cậy. Kết quả này không khẳng định mọi cấu hình LightGBM/CatBoost đều kém; chỉ phản ánh lượt thử đã khóa.
- Chưa chọn thêm cấu hình hoặc hạ ngưỡng để làm đẹp kết quả. Hướng nghiên cứu tiếp theo nên kiểm tra khả năng thay đổi phân phối/nguồn dữ liệu và hiệu chỉnh khoảng dự báo, thay vì mặc định thuật toán phức tạp hơn sẽ thắng.
- Báo cáo chi tiết: [report.md](../data/lake/modeling/research/2026-10-25-quantile-v1/report.md); cùng thư mục có `report.json`, `predictions.csv`, `manifest.json` và audit nhãn.
- 91 bài kiểm thử: 89 đạt, 2 bài nguồn trực tiếp bỏ qua; gồm chạy thật cả hai adapter CPU. Rà soát độc lập không phát hiện lỗi quan trọng.
- Hash dữ liệu, reference, active model, dashboard và các file campaign giữ nguyên. Không commit/deploy hoặc kích hoạt hai ứng viên.
