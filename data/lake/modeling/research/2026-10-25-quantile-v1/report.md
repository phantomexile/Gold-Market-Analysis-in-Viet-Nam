# Đối chứng LightGBM Quantile và CatBoost MultiQuantile

Kỳ hạn ba tháng, cùng frame/34 đặc trưng/train5năm/refittháng/ngưỡng1%. Lịch sử đã xem để phát triển; không cấp validated hoặc đổi mô hình đang chạy.

| Mô hình | MAE (điểm %) | So zero | Brier | ECE (điểm %) | Xuyên Q10 |
|---|---:|---:|---:|---:|---:|
| catboost_multiquantile | 9.78 | -9.0% | 0.341 | 31.34 | 32.46% |
| lightgbm_quantile | 9.97 | -11.1% | 0.332 | 30.97 | 26.69% |
| rf_small | 9.33 | -4.0% | 0.327 | 30.53 | 17.23% |
| zero | 8.97 | +0.0% | 0.290 | 23.74 | 18.85% |

## Khoảng dự báo và danh mục

| Mô hình | Độ phủ Q10–Q90 | Độ rộng (điểm %) | Lợi suất toàn kỳ | Giảm tối đa | Đủ tiêu chí phát triển |
|---|---:|---:|---:|---:|---|
| catboost_multiquantile | 15.8% | 5.40 | +61.4% | -29.1% | False |
| lightgbm_quantile | 25.1% | 6.78 | +61.4% | -29.1% | False |
| rf_small | 58.6% | 20.80 | +52.3% | -29.1% | False |
| zero | 65.4% | 18.56 | +0.0% | 0.0% | False |

Khoảng Q10–Q90 có mục tiêu độ phủ 80%; phải xét cả độ rộng và pinball, không chỉ đẩy khoảng rộng để đạt độ phủ.
Lợi suất danh mục là toàn kỳ, đã tính spread, chưa tính các phí khác. Không phải lợi suất năm hoặc lợi suất tương lai.
LightGBM/CatBoost lấy Q50 làm point và Q10 học trực tiếp; RF dùng point hồi quy và Q10 residual. Đây là so sánh toàn phương pháp, không tách riêng tác động họ thuật toán.
P(lãi) dùng cùng sigmoid OOS24tháng. report.json có thêm Q10 residual cho hai ứng viên để đối chiếu cùng công thức RF.
Không thử thêm cấu hình sau khi xem kết quả. Dashboard/active model/campaign giữ nguyên.
