# Kết quả cải thiện mô hình ba tháng — 25/10/2026

Đã triển khai đủ luồng nghiên cứu: đặc trưng tỷ lệ/biến động, đối chứng hữu hạn, đánh giá Mua/Bán/Quan sát, sigmoid ngoài mẫu và Q10, khóa ứng viên và tự ghi dự báo mới khi cập nhật. Chất lượng đã cải thiện so với RF cũ nhưng chưa đủ bằng chứng để thay mô hình đang hiển thị hoặc gọi mô hình đáng tin cậy.

## Thay đổi đã thực hiện

- 34 đặc trưng từ biến động vàng nội địa, volatility, khoảng cách giá trung bình, drawdown, spread, premium, thay đổi tỷ giá/vàng thế giới/DXY/lợi suất và mùa trong năm. Không dùng tin/sự kiện hồi cứu hoặc nhãn tương lai.
- Bảy ứng viên cố định: zero, giá mua lại không đổi, trung vị, Ridge, ElasticNet, RF nhỏ và Gradient Boosting Huber. Không bổ sung cấu hình sau khi xem kết quả.
- Mô hình ML học biến động giá mua lại, chuyển về lợi suất mua mới theo giá bán/mua thực tế. Mua mới âm do spread không tự biến thành Bán cho người đang giữ vàng.
- Fit đầu tháng trên năm năm gần nhất, chỉ nhãn đã đáo hạn trước đầu tháng. Điền thiếu/scaler chỉ học train.
- Chọn model theo 24 tháng OOS đã đáo hạn, tối thiểu 120 dòng/6 tháng, giảm MAE ít nhất 5% so với zero. Ngưỡng 0,5%/1%/2% chỉ chọn bằng danh mục quá khứ; thiếu ba giao dịch hoàn tất giữ 1%.
- Xác suất sigmoid và phân vị residual 10% chỉ học dự báo OOS đã đáo hạn. So sánh thêm xác suất empirical và Q10 Gradient Boosting; không chọn phương pháp thắng sau khi xem toàn bộ lịch sử.

## Kết quả có thể so sánh

Trên cùng 1.300 ngày dự báo ba tháng đã đáo hạn từ năm 2023:

| Phương pháp | MAE, điểm phần trăm |
|---|---:|
| RF cũ, báo cáo đóng băng theo năm | 12,44 |
| RF cũ, đối chứng huấn luyện theo tháng từ lượt nghiên cứu trước | 10,02 |
| RF mới, đặc trưng tỷ lệ/biến động và train 5 năm | 9,33 |
| Mốc luôn dự báo lợi suất 0 | 8,97 |

RF mới giảm MAE khoảng 25,0% so với báo cáo RF năm và 6,9% so với đối chứng RF tháng. Đã ghép từng ngày giữa CSV đối chứng cũ và lượt mới, xác nhận cả 1.300 nhãn actual khớp trong sai số 1e-10. Đây là cải thiện của toàn bộ cách làm mới, chưa tách riêng hiệu ứng đặc trưng, cửa sổ train và thuật toán.

Chuỗi chọn ứng viên trước từng tháng có MAE **9,81**, vẫn kém mốc 8,97. Việc chọn cấu hình tốt từ quá khứ chưa ổn định trong giai đoạn mới.

## Xác suất và Q10 của RF mới

| Chỉ số | Kết quả | Điều kiện dự án |
|---|---:|---|
| Brier sigmoid | 0,327 | Cần tốt hơn baseline train ít nhất 5%; baseline hiện là 0,253 |
| Brier empirical đối chứng | 0,343 | Chưa đạt |
| Sai lệch hiệu chỉnh ECE | 30,53 điểm % | Không quá 10 điểm % |
| Tỷ lệ xuyên Q10 residual | 17,23% | Không quá 15% |
| Pinball Q10 | 0,02375 | Không kém baseline 0,02315 |

So với báo cáo mô hình cũ, Brier giảm từ 0,435 và tỷ lệ xuyên Q10 giảm từ 21,31%; vẫn không đạt các điều kiện đã khóa. Không đổi ngưỡng để tạo kết quả đạt.

## Hiệu quả tín hiệu và mức bất định

- Danh mục một vị thế hoặc tiền mặt, quyết định đầu tháng, mua giá bán và bán/định giá giá mua. Không cộng các khoản lợi suất ba tháng chồng lấn.
- RF mới: lợi suất danh mục toàn kỳ nghiên cứu **+52,3%**, so với mua-và-giữ **+107,9%** và tiền mặt 0%. Mức giảm tài sản tối đa đều khoảng **29,1%**. Chưa tính các phí ngoài spread vì chưa có dữ liệu phí đó.
- RF mới chỉ có **hai vòng mua–bán hoàn tất**, một vị thế cuối kỳ định giá theo giá mua; quá ít để kết luận ổn định.
- Trong 15 cửa sổ ba tháng không chồng lấn: 9 Mua, 2 Bán, 4 Quan sát. Hai cửa sổ Bán đều không tốt hơn tiếp tục giữ; mẫu rất nhỏ. Quan sát bỏ lỡ cơ hội mua có lãi trên 1% ở 3/4 cửa sổ này.
- Bootstrap khối ba tháng, 43 tháng đánh giá, khoảng 90% của mức cải thiện MAE bình quân tháng so với zero: **−20,7% đến +9,5%**. Chưa có bằng chứng chắc chắn mô hình thắng baseline; khoảng này cũng chỉ mô tả lịch sử đã dùng phát triển.
- RF mới tốt hơn zero trong 2023 và 2025, kém trong 2024 và 2026; chưa đạt yêu cầu ổn định ít nhất ba năm.

## Khóa ứng viên và thu thập bằng chứng mới

- Ứng viên `rf_small`, ngưỡng 1%, ở chế độ **shadow**. Chọn bằng điểm OOS trước đầu tháng hiện tại; chưa đủ chuẩn thay mô hình hiển thị.
- Protocol cuối: `9a00600ea79882241950320f`, bắt đầu nhận bằng chứng từ **26/10/2026** theo giờ Việt Nam.
- Snapshot hiện tại 24/10/2026 là tham chiếu trước protocol: **0 dự báo mới được tính, 0 đáo hạn**. Không nhập 1.300 dòng lịch sử vào tiến độ thực tế.
- Mỗi lần cập nhật, hook gọi `run_stationary_research.py --record-only`. Fit theo lịch tháng đã khóa, ghi dự báo ngày hiện tại và giữ bản đầu tiên, đánh giá khi đủ giá đáo hạn.
- Khóa cả thuật toán, shared maturity/scoring, mã tạo frame/collection/processing/configs, dữ liệu OOS ban đầu, lịch refit, ngưỡng và phiên bản thư viện. Mã hoặc dữ liệu hiệu chỉnh bị sửa sẽ dừng ghi cho protocol cũ; dữ liệu thị trường mới được phép tăng.
- Nhật ký/index có checksum để phát hiện file mất/thêm/sửa, không phải chứng thư chống sửa đổi bởi người toàn quyền kiểm soát máy.
- Chưa kích hoạt ứng viên trên dashboard; ba tín hiệu và phần lý do/chi tiết hiện tại giữ nguyên. Không ghi lệnh giao dịch, không commit hoặc deploy.

## Bằng chứng và kiểm tra

- Lượt cuối: [báo cáo nghiên cứu](../data/lake/modeling/research/2026-10-25-stationary-v2/report.md), `report.json`, `predictions.csv`, `selected_path.csv`, `selections.json`, `manifest.json` trong cùng thư mục.
- `target_audit.json`: không phát hiện lỗi nhãn lợi suất/ngày thoát/giá trong frame; chưa xác minh độc lập mọi báo giá nguồn.
- Thư mục `data/lake/modeling/stationary_shadow/`: `active.json`, protocol đã khóa, OOS ban đầu, `latest.json` và nhật ký dự báo mới. Đã chạy thành công `--record-only` trên snapshot hiện tại.
- V1 giữ để kiểm toán. Sau rà soát, fingerprint được mở rộng để bao gồm mã dùng chung; v2 chạy lại cùng mô hình/tham số và là bản cuối. Không dùng protocol v1 cho bằng chứng mới.
- Rà soát độc lập không còn lỗi quan trọng sau sửa fingerprint. Kiểm thử kiểm tra causal features, purge, hiệu chỉnh, lựa chọn chỉ dùng quá khứ, bid/ask/cash, bỏ lỡ cơ hội khi Quan sát, fingerprint, xác suất sai, nhật ký bất biến và hook có/không bản khóa.
- Bộ 85 bài kiểm thử Python: 83 đạt, 2 bài nguồn trực tiếp bỏ qua. Kiểm thử JavaScript hiển thị và 7 tình huống cập nhật đạt. Đối chiếu hash mã/dữ liệu/artifact bảo vệ, JSON nghiêm ngặt, UTF-8 không BOM và diff đều đạt.
- Kiểm tra thực tế 14.749 dự báo của bảy ứng viên: cùng tập ngày, train/calibration exit trước đầu tháng, không trùng ngày/ứng viên; 1.300 dòng RF đã đáo hạn. `comparison_with_monthly_rf.json` lưu hash hai CSV và mức cải thiện 6,92% trên các nhãn ghép khớp.
- Đã kiểm tra hook bằng unit test và chạy trực tiếp collector; chưa chạy lại toàn bộ thu thập mạng/huấn luyện ba kỳ hạn chỉ để kiểm tra hook tùy chọn.

**Kết luận:** Hoàn thành đợt cải thiện và cơ chế kiểm chứng mới; chưa chứng minh được mô hình đáng tin cậy. Hướng tiếp theo cần ưu tiên chất lượng dữ liệu nguồn và khả năng thích ứng với các giai đoạn biến động, đồng thời giữ nguyên bộ bằng chứng mới để theo dõi khách quan.
