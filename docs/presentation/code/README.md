# Mã nguồn có chú thích để đọc khi thuyết trình

Đây là **bản đọc**, không phải điểm chạy pipeline. Mã vận hành vẫn ở vị trí gốc. Mỗi bản chỉ thêm comment tiếng Việt; generator kiểm tra AST giống nguồn trước khi ghi.

| Thứ tự | Bản có chú thích | Mã vận hành |
|---|---|---|
| 1 | [01_targets.py](01_targets.py) | [targets.py](../../../src/gold_collectors/modeling/targets.py) |
| 2 | [02_stationary_features.py](02_stationary_features.py) | [stationary_features.py](../../../scripts/analysis/stationary_features.py) |
| 3 | [03_stationary_research.py](03_stationary_research.py) | [stationary_research.py](../../../scripts/analysis/stationary_research.py) |
| 4 | [04_snapshot_validation.py](04_snapshot_validation.py) | [snapshot_validation.py](../../../scripts/analysis/snapshot_validation.py) |
| 5 | [05_refresh_pipeline.py](05_refresh_pipeline.py) | [refresh_latest_forecast.py](../../../scripts/pipeline/refresh_latest_forecast.py) |
| 6 | [06_active_snapshot.py](06_active_snapshot.py) | [active_snapshot.py](../../../scripts/analysis/active_snapshot.py) |
| 7 | [07_build_model_frame.py](07_build_model_frame.py) | [features.py](../../../src/gold_collectors/modeling/features.py) |

Các comment giải thích input/output, validation, ý nghĩa chênh lệch mua–bán, nhãn tháng lịch, chia tập, hiệu chỉnh và trạng thái. Mã server và xuất JSON được comment trực tiếp tại [web/server.py](../../../web/server.py) và [build_web_data.py](../../../scripts/build_web_data.py).

Nếu nguồn đổi, tạo lại bản đọc từ thư mục gốc:

```powershell
python scripts/reporting/prepare_presentation_sources.py
```

[manifest.json](manifest.json) lưu nguồn, SHA-256 trước/sau thêm comment và kết quả đối chiếu logic. Chỉ đọc các bản sao, không sửa chúng để thay đổi chương trình; hãy sửa mã vận hành bằng quy trình quản lý mô hình phù hợp rồi tạo lại.
