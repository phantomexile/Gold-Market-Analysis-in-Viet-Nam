# Phân nhóm mã phân tích và mô hình

Các tệp giữ vị trí để bảo toàn import, CLI và bản khóa mô hình. Bảng này giúp đọc theo luồng thay vì mở ngẫu nhiên mọi script.

| Nhóm | Tệp tiêu biểu | Trách nhiệm |
|---|---|---|
| Điểm chạy cập nhật | train_latest_snapshot.py, active_snapshot.py | Dựng frame, đi vào tuyến model được registry chọn, ghi snapshot |
| Mô hình đang chọn | stationary_features.py, stationary_research.py, forecast_selection.py | Tạo biến tỷ lệ, RF, hiệu chỉnh ngoài mẫu và chọn từng kỳ hạn |
| Kiểm chứng và khóa | snapshot_validation.py, stationary_evaluation.py, stationary_shadow.py, stationary_activation.py | Theo dõi dự báo mới, chờ đáo hạn, kiểm tra chất lượng, xác minh bản khóa |
| Diễn giải/giao dịch mô phỏng | forecast_signals.py, run_rolling_paper_trading.py, export_trading_signals.py | Tín hiệu trực tiếp và sổ mô phỏng |
| Công cụ chiến dịch | run_model_research.py, run_stationary_research.py, run_forecast_repair.py | Thử nghiệm so sánh; đọc tác dụng ghi tệp trước khi chạy |
| Tuyến đối chiếu/lịch sử | snapshot_calibration.py, snapshot_historical.py, run_decision_support_analysis.py | Đối chứng và phân tích theo giao thức tương ứng |

Luồng đọc đề xuất: `train_latest_snapshot` → `active_snapshot` → `stationary_activation` → `stationary_shadow` → `stationary_research` → `snapshot_validation` → `scripts/build_web_data.py`.

**Không phải mọi script “research” đều chỉ đọc:** `run_forecast_repair.py` có thể dựng dữ liệu và kích hoạt registry; `run_stationary_research.py` có nhiều chế độ. Để thuyết trình, mở [bản mã có chú thích](../../docs/presentation/code/README.md), không chạy lại chiến dịch chỉ để xem nội dung.
