# Script theo trách nhiệm

Chạy lệnh từ thư mục gốc của dự án. Các thư mục ở đây có cùng độ sâu để đường dẫn dữ liệu giữ nguyên sau khi chuyển file.

| Thư mục | Trách nhiệm | Điểm chạy tiêu biểu |
|---|---|---|
| `collection/` | Tải dữ liệu giá, thị trường, tin tức và nguồn chính sách | `refresh_event_inputs.py`, `crawl_raw_gold_history.py` |
| `processing/` | Ghép bảng, tạo sự kiện, premium và dữ liệu vĩ mô | `build_master_panel.py`, `build_premium_decomposition.py` |
| `pipeline/` | Điều phối nhiều bước cập nhật liên tiếp | `refresh_latest_forecast.py`, `update_incremental.py` |
| `analysis/` | Huấn luyện, đánh giá, tín hiệu và giao dịch mô phỏng | `run_decision_support_analysis.py`, `train_latest_snapshot.py` |
| `reporting/` | Kiểm toán nguồn, chất lượng và tạo báo cáo/biểu đồ | `quality_report.py`, `build_full_report.py` |
| `maintenance/` | Phục hồi, backup, sửa dữ liệu/mã và công cụ lịch sử | `recover_widest_csv.py`, `recovery_hash_backup.py` |

`build_web_data.py` chuyển đầu ra data lake thành JSON cho dashboard.
`_bootstrap.py` thiết lập import thư mục gốc và `src` dùng chung.
`_compat.py` chuyển tiếp các điểm chạy cũ sang module mới.

## Các lệnh chính

```powershell
python scripts/pipeline/refresh_latest_forecast.py
python scripts/collection/refresh_event_inputs.py --help
python scripts/processing/build_master_panel.py --help
python scripts/analysis/run_decision_support_analysis.py --help
python scripts/reporting/quality_report.py --help
python scripts/maintenance/recover_widest_csv.py --help
python web/server.py
```

Các CLI có parser cũng có thể chạy theo package, ví dụ:

```powershell
python -m scripts.collection.refresh_event_inputs --help
```

## Tương thích và thêm mã mới

Các file chuyển tiếp trong `pipeline/` và `analysis/` chỉ giữ đường dẫn cũ cho lệnh đã lưu và import hiện có. Sửa logic ở file đích trong nhóm chức năng; không đặt thêm logic vào file chuyển tiếp. Ví dụ `scripts/pipeline/build_master_panel.py` chuyển tới `scripts/processing/build_master_panel.py`.

Một số công cụ lịch sử chạy ngay khi mở bằng Python và không hỗ trợ `--help`, đặc biệt trong `maintenance/`. Chỉ chạy chúng khi có nhu cầu cụ thể; không dùng chúng như bước kiểm tra import hoặc bước cập nhật hằng ngày.

Dữ liệu trong `data/lake/`, báo cáo và JSON dashboard vẫn dùng vị trí hiện có. Cấu trúc đầy đủ và ranh giới module được mô tả trong [bản đồ mã nguồn](../docs/SOURCE_CODE_MAP.md).
