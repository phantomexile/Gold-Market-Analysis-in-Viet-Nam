# Kết quả nghiên cứu mô hình lợi suất

Đây là sàng lọc trên lịch sử đã xem. Chưa đánh giá lại xác suất/Q10, chưa cấp validated và chưa thay mô hình vận hành.

Huấn luyện đầu mỗi tháng, chỉ dùng nhãn đã đáo hạn trước tháng. Chọn cấu hình vào đầu năm bằng MAE bình quân tháng của 24 tháng trước đã đáo hạn, tối thiểu 6 tháng/120 dòng.

## Tính nhất quán nhãn

| Kỳ hạn | Nhãn sai lợi suất | Ngày thoát sai | Giá không hợp lệ |
|---|---:|---:|---:|
| 1 tháng | 0 | 0 | 0 |
| 3 tháng | 0 | 0 | 0 |
| 5 tháng | 0 | 0 | 0 |

Kiểm tra trên model frame, chưa đối chiếu độc lập từng báo giá nguồn.

## Chẩn đoán mô hình đóng băng theo năm hiện tại

| Kỳ hạn | MAE (điểm %) | Bias dự báo − thực tế (điểm %) |
|---|---:|---:|
| 1 tháng | 6.23 | -1.81 |
| 3 tháng | 12.44 | -3.55 |
| 5 tháng | 16.71 | -5.53 |

## Đối chứng cùng lịch huấn luyện tháng

| Kỳ hạn | Ứng viên | MAE (điểm %) | Cải thiện so với 0 |
|---|---|---:|---:|
| 1 tháng | zero | 3.70 | +0.0% |
| 1 tháng | median_all | 3.71 | -0.4% |
| 1 tháng | median_3y | 3.82 | -3.2% |
| 1 tháng | ridge20_without_global | 4.08 | -10.4% |
| 1 tháng | ridge20_without_calendar | 4.11 | -11.3% |
| 1 tháng | ridge20_all | 4.13 | -11.7% |
| 1 tháng | ridge20_without_domestic | 4.27 | -15.5% |
| 1 tháng | ridge20_3y | 4.55 | -23.1% |
| 1 tháng | rf20_all | 4.70 | -27.2% |
| 1 tháng | rf20_3y | 5.28 | -42.9% |
| 1 tháng | rf120_reference | 5.39 | -45.8% |
| 3 tháng | zero | 8.97 | +0.0% |
| 3 tháng | ridge20_without_global | 9.08 | -1.2% |
| 3 tháng | median_all | 9.12 | -1.7% |
| 3 tháng | ridge20_3y | 9.41 | -4.9% |
| 3 tháng | median_3y | 9.48 | -5.6% |
| 3 tháng | rf20_3y | 9.66 | -7.7% |
| 3 tháng | ridge20_all | 9.71 | -8.2% |
| 3 tháng | ridge20_without_calendar | 9.71 | -8.2% |
| 3 tháng | ridge20_without_domestic | 9.84 | -9.7% |
| 3 tháng | rf120_reference | 10.02 | -11.7% |
| 3 tháng | rf20_all | 10.57 | -17.9% |
| 5 tháng | ridge20_without_global | 13.43 | +4.5% |
| 5 tháng | zero | 14.07 | +0.0% |
| 5 tháng | rf20_all | 14.13 | -0.4% |
| 5 tháng | median_all | 14.19 | -0.8% |
| 5 tháng | rf20_3y | 14.36 | -2.1% |
| 5 tháng | median_3y | 14.68 | -4.4% |
| 5 tháng | rf120_reference | 15.06 | -7.0% |
| 5 tháng | ridge20_3y | 15.37 | -9.2% |
| 5 tháng | ridge20_all | 15.55 | -10.5% |
| 5 tháng | ridge20_without_calendar | 15.55 | -10.5% |
| 5 tháng | ridge20_without_domestic | 15.55 | -10.5% |

Bảng trên đã xem toàn kỳ nghiên cứu, không dùng người thắng bảng này làm bằng chứng độc lập.

## Chuỗi lựa chọn cấu hình trước từng năm

| Kỳ hạn | MAE (điểm %) | Cải thiện so với 0 | Cửa sổ không chồng lấn |
|---|---:|---:|---:|
| 1 tháng | 3.77 | -1.9% | 45 |
| 3 tháng | 11.12 | -24.0% | 15 |
| 5 tháng | 13.88 | +1.3% | 9 |

Chi tiết theo năm, nhóm đặc trưng, nhóm xác suất và tháng sai nhiều nằm trong các file JSON kèm theo.

Chỉ số này chưa đủ kết luận mô hình đạt toàn bộ chất lượng: Brier, ECE, Q10 và bằng chứng tiến cứu vẫn phải kiểm tra riêng.
