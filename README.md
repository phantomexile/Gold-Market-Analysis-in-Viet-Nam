# VN Gold Market Analysis

Pipeline thu thập và xử lý dữ liệu giá vàng Việt Nam (SJC) và các yếu tố vĩ mô toàn cầu để dự báo đa kỳ hạn (1, 3, 5 tháng).

**Nguyên tắc cốt lõi**: Một record chỉ được chấp nhận làm dữ liệu huấn luyện lịch sử khi `requested_date == business_date` và cả giá mua/bán đều hợp lệ. Nguồn current-only KHÔNG bao giờ được trộn vào nhãn huấn luyện lịch sử.

**Kỳ hạn dự báo hiện tại**: 1, 3 và 5 **tháng lịch** từ ngày snapshot. Nhãn huấn luyện dùng giá SJC mua vào của phiên hợp lệ đầu tiên vào hoặc sau ngày tròn tháng, chia cho giá SJC bán ra tại ngày dự báo, rồi trừ 1. Các độ trễ 21/63/105 trong đặc trưng vẫn là số dòng quá khứ; các backtest đã lưu trước khi đổi định nghĩa kỳ hạn là kết quả lịch sử và không xác nhận model tháng lịch mới.

**Mô hình dashboard đang áp dụng**: giữ dự báo ML riêng cho 1/3/5 tháng, chọn từ RF cũ và RF học trung vị lợi suất ròng trên các nhãn đã đáo hạn. Mốc lợi suất 0 chỉ làm đối chứng, không thay cả ba dự báo bằng 0 khi ML chưa đạt. Dự báo trực tiếp chưa vượt đối chứng có nhãn thử nghiệm và ghi rõ giới hạn; không tự cấp validated. Registry nằm ở `data/lake/modeling/active_prediction_model.json`. P(lãi) và Q10 vẫn được kiểm tra riêng trước khi công bố; chỉ số chưa đạt để trống kèm lý do, số liệu nghiên cứu được giữ để kiểm toán. Xem [kết quả sửa độ tin cậy](docs/forecast-reliability-2026-10-26.md); [báo cáo RF 25/10](docs/all-horizon-rf-2026-10-25.md) là tham chiếu trước sửa.

**Quy đổi giá thế giới**: `USD/oz × USD/VND × 37,5 / 31,1034768`, dùng hằng số chung trong `src/gold_collectors/units.py`. Một lượng bằng 37,5 gram; không nhân thêm hệ số 1,205. Kết quả lịch sử dựng trước khi sửa đơn vị cần được đọc theo phiên bản của báo cáo đó.

**Điều chỉnh dự báo riêng kỳ hạn:** baseline không thay đầu ra ML bằng 0. Snapshot 24/10/2026 hiện có lợi suất dự báo 1/3/5 tháng lần lượt −0,66% / +3,08% / +8,47%; vẫn `validation_pending`. Xem [nguyên nhân và kết quả sửa](docs/horizon-forecasts-2026-10-26.md).

Để dựng lại premium và so sánh mô hình trên dữ liệu lake hiện có, chạy `python scripts/analysis/run_forecast_repair.py --output data/lake/modeling/research/<ten-luot-moi>`. Mỗi lượt dùng thư mục mới, giữ kết quả cũ. Lệnh `run_all_horizon_rf.py --output ...` chuyển tiếp cùng quy trình có đối chứng. Sau khi registry chọn `forecast_pipeline = reliability_v2`, cập nhật thường ngày ghi cùng dự báo đang dùng vào CSV, sổ mô phỏng và dashboard; không chạy RF cũ đè lên snapshot.

Để cập nhật dữ liệu và dự báo cùng một lượt, chạy `python scripts/pipeline/refresh_latest_forecast.py`. Nếu dữ liệu lake đã mới và chỉ cần dựng lại model, dùng `python scripts/pipeline/refresh_latest_forecast.py --skip-collect`. Nút **Cập nhật** của dashboard gọi cùng luồng này.

Dashboard hiển thị thanh tiến trình theo các mốc thực tế, tên bước và thời gian đã chạy. Phần trăm thể hiện tiến độ theo bước, không phải ước lượng thời gian còn lại. Lượt cập nhật chạy nền và dùng chung giữa các tab; tải lại trang sẽ tiếp tục theo dõi lượt đang chạy. API `POST /api/update` trả HTTP 202 khi nhận việc, còn `GET /api/update/status` trả trạng thái `idle`, `running`, `ok` hoặc `warning`. Chỉ đạt 100% khi toàn bộ pipeline và kiểm tra ngày snapshot thành công.

Bước cập nhật sự kiện tải tin RSS có ngày xuất bản và chỉ số GPR ngày từ nguồn Caldara–Iacoviello. Tin mới được ghi vào `news_raw_headlines_vietnam_gold.csv`; event proxy từ tiêu đề được ghi vào `pipeline_output_event_regime.csv`. Metadata tách ngày đăng và ngày thu thập ở `data/lake/manifests/event_inputs_refresh.json`. Bảng chính sách NHNN chính thức chỉ được cập nhật khi có bài từ nguồn NHNN được xác minh; event proxy từ RSS không được coi là quyết định chính thức.

---

## Cấu trúc thư mục

```text
Gold-Market-Analysis-in-Viet-Nam/
├── pyproject.toml                 # Cấu hình package và dependency
├── requirements.txt
├── run_all_pipelines.bat          # Launcher Windows, dùng thư mục hiện tại của dự án
├── configs/                      # Danh sách và cấu hình nguồn dữ liệu
├── src/gold_collectors/           # Thư viện nghiệp vụ dùng chung
│   ├── collectors.py             # Thu thập giá từ các nguồn
│   ├── parsing.py                # Chuẩn hóa ngày và số
│   ├── http.py                   # HTTP, cache và giới hạn tần suất
│   ├── reliability.py            # Kiểm tra độ tin cậy của nguồn
│   ├── models.py                 # Cấu trúc bản ghi giá vàng
│   ├── full_pipeline.py          # Ghi data lake và tiện ích pipeline
│   └── modeling/
│       ├── config.py             # Đường dẫn và tham số mô hình
│       ├── features.py           # Ghép dữ liệu theo thời điểm và tạo đặc trưng
│       ├── targets.py            # Nhãn lợi suất 1/3/5 tháng lịch
│       ├── training.py           # Baseline, kinh tế lượng, học máy
│       ├── evaluation.py         # Fold thời gian, chỉ số, quy tắc quyết định
│       ├── reporting.py          # Tổng hợp kết quả và viết báo cáo
│       └── decision_support.py   # Điều phối, giữ API import cũ
├── scripts/
│   ├── collection/               # Thu thập giá, tin, chỉ số và nguồn chính sách
│   ├── processing/               # Ghép bảng, premium, sự kiện và dữ liệu vĩ mô
│   ├── pipeline/                 # Điều phối cập nhật và điểm chạy tương thích cũ
│   ├── analysis/                 # Huấn luyện, tín hiệu và giao dịch mô phỏng
│   ├── reporting/                # Kiểm toán chất lượng, báo cáo và biểu đồ
│   ├── maintenance/              # Backup, phục hồi và công cụ lịch sử
│   ├── _bootstrap.py             # Thiết lập import dùng chung
│   ├── _compat.py                # Chuyển tiếp các điểm chạy cũ
│   └── build_web_data.py          # Dựng JSON dashboard
├── web/                          # Server, HTML, CSS, JavaScript và JSON dashboard
├── tests/                        # Kiểm thử nghiệp vụ và tương thích cấu trúc
├── notebooks/                    # Notebook phân tích
├── docs/                         # Hướng dẫn, bản đồ mã nguồn và báo cáo
└── data/                         # Dữ liệu giữ nguyên vị trí hiện tại
```

Xem [hướng dẫn script](scripts/README.md) và [bản đồ mã nguồn](docs/SOURCE_CODE_MAP.md). Các lệnh ở vị trí cũ vẫn được chuyển tiếp; khi thêm hoặc sửa chức năng, dùng file trong nhóm trách nhiệm mới.

---

## Setup

```powershell
# 1. Tạo conda env
conda create -y -n gold-data-crawl python=3.11 pip
conda activate gold-data-crawl

# 2. Install package + extras (yfinance, vnstock, crawl4ai, playwright)
python -m pip install -e ".[agentic]"

# 3. Install Chromium cho crawl4ai / playwright
python -m playwright install chromium

# 4. Copy .env.example → .env và điền API keys
copy .env.example .env
# Cần: OPENROUTER_API_KEY, OPENROUTER_MODEL (agentic crawls)
# Optional: FRED API key (nếu không dùng CSV windowed download)
```

---

## Data Lake Layout

| Path | Nội dung | Git-tracked |
|---|---|---|
| `data/lake/raw_gold_15y/` | Raw crawl 2010-2026, mọi nguồn (SJC, PNJ, WebGia...) | Yes — commit riêng |
| `data/lake/domestic_target/` | Historical-valid only — dòng `requested_date == business_date` | Yes — commit riêng |
| `data/lake/market_data/v1/` | FX (Vietcombank+SBV), yfinance, FRED, World Bank, GSO, vnstock | No |
| `data/lake/market_data/v2/` | FRED expanded, futures basis (GC=F), GLD ETF, events, sentiment | No |
| `data/lake/enriched/master/` | **4 master tables** — output cuối của pipeline | No |
| `data/lake/gold_prices/` | Premium decomposition, enriched gold | No |

---

## 4 Master Tables (output cuối cùng)

Pipeline chạy xong sẽ sinh ra 4 bảng trong `data/lake/enriched/master/normalized/`:

| Bảng | Số rows (hiện tại) | Nội dung |
|---|---|---|
| `gold_domestic_daily_panel` | — | Giá vàng nội địa theo ngày × nguồn × loại sản phẩm (buy/sell/spread) |
| `global_reference_daily` | — | LBMA, USD/VND, yields, DXY, VIX, oil, futures basis, ETF — tất cả global ref |
| `vn_macro_asof_panel` | 36K | Macro VN + global, join theo `available_from` (chống leakage) |
| `event_regime_panel` | 1,850 | Tết, Thần Tài, wedding, policy, crisis events — 13 loại |

---

## Quick Start — Chạy Pipeline Đầy đủ

```powershell
# Set encoding cho Vietnamese characters
$env:PYTHONUTF8 = "1"

# ── Bước 1: Audit sources ──────────────────────────────────
# Kiểm tra reliability của mọi nguồn crawl
python scripts/reporting/source_audit.py --out-dir data/experiments/audit_output

# Xây registry mới từ kết quả audit
# Lịch sử, file không có trong checkout hiện tại: python scripts/pipeline/build_source_registry.py --audit-json data/experiments/audit_output/source_audit.json

# ── Bước 2: Backfill domestic target (historical-valid only) ──
# Chỉ giữ records có requested_date == business_date và cả 2 giá hợp lệ
python scripts/collection/backfill_target.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/domestic_target

# ── Bước 3: Raw full crawl (resume-enabled) ──────────────────
# Crawl lịch sử giá vàng từ mọi nguồn, có thể dừng/chạy lại
python scripts/collection/crawl_raw_gold_history.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/raw_gold_15y --resume

# ── Bước 4: External features v1 ─────────────────────────────
# FX rates (SBV + Vietcombank), global market series (yfinance + FRED),
# Vietnam macro (World Bank + GSO), VNINDEX (vnstock)
python scripts/collection/collect_external_features.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/market_data/v1

# ── Bước 5: Enhanced features v2 ────────────────────────────
# FRED expanded (DXY real yields, TIPS, stress indices),
# futures basis (GC=F), GLD ETF, VN deposit rates, event panel, sentiment
python scripts/collection/collect_enhanced_features.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2

# ── Bước 6 (optional): LBMA proxy backfill ──────────────────
# World Bank monthly gold + GC=F daily as LBMA proxy
# Lịch sử, file không có trong checkout hiện tại: python scripts/pipeline/collect_lbma_proxy.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2

# ── Bước 7 (optional): Rule-based sentiment ─────────────────
# Tín hiệu sentiment từ VIX + gold momentum + USD/VND + event anchor
# Lịch sử, file không có trong checkout hiện tại: python scripts/pipeline/rule_sentiment.py --from 2010-01-01 --to 2026-07-11

# ── Bước 8: Premium decomposition ───────────────────────────
# Tính premium = SJC mid - (LBMA USD/oz × USD/VND × conversion_factor)
python scripts/processing/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices

# ── Bước 9: Event panel ──────────────────────────────────────
# Sinh events: Tết proximity, Thần Tài, wedding season, policy, crisis
python scripts/processing/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices

# ── Bước 10: Build master panel (4 tables) ──────────────────
# Tích hợp tất cả nguồn vào 4 bảng chuẩn
python scripts/processing/build_master_panel.py --tables all

# ── Bước 11: Quality report ──────────────────────────────────
# Kiểm tra: leakage, coverage, outliers, source reliability
python scripts/reporting/quality_report.py --data-lake data/lake/domestic_target --from 2011-07-06 --to 2026-07-11
```

---

## Xác minh Kết quả

Sau khi chạy xong, kiểm tra output:

```powershell
# Xem manifest của từng master table
dir data/lake/enriched/master/manifests/

# Đếm rows
python -c "import csv; rows=list(csv.DictReader(open('data/lake/enriched/master/normalized/global_reference_daily.csv',encoding='utf-8'))); print(f'{len(rows):,} rows')"

# Xem premium coverage
python -c "import csv; rows=list(csv.DictReader(open('data/lake/gold_prices/normalized/gold_daily_enriched.csv',encoding='utf-8'))); has_prem=sum(1 for r in rows if r.get('premium')); print(f'Dates: {len(rows)}, With premium: {has_prem} ({has_prem/len(rows)*100:.0f}%)')"

# Quality report
$env:PYTHONUTF8="1"; python scripts/reporting/quality_report.py --data-lake data/lake/domestic_target --from 2011-07-06 --to 2026-07-11
```

---

## Dòng lệnh hay dùng

```powershell
# Xem git status trước khi commit
git status

# Commit dataset lớn (raw_gold, domestic_target, external_features)
git add data/lake/raw_gold_15y data/lake/domestic_target data/lake/market_data/v1
git commit -m "data: backfill raw gold + domestic target + external features v1"

# Run tests
python -m unittest discover -s tests

# Crawl resume — dùng khi crawl bị gián đoạn
python scripts/collection/crawl_raw_gold_history.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/raw_gold_15y --resume

# Chạy 1 table master panel cụ thể (nhanh hơn --tables all)
python scripts/processing/build_master_panel.py --table global_reference_daily
```

---

## Liên kết nhanh

| File | Mô tả |
|---|---|
| [PIPELINE_GUIDE.md](docs/PIPELINE_GUIDE.md) | Hướng dẫn chi tiết từng bước pipeline |
| [DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Schema từng bảng dữ liệu + data flow |
| [SOURCE_CODE_MAP.md](docs/SOURCE_CODE_MAP.md) | Giải thích từng module code — collectors, master panel, quality |
| [deep-research-report.md](docs/deep-research-report.md) | Báo cáo nghiên cứu sâu — framework, model roadmap, gap analysis |

---

## Nguyên tắc quan trọng

1. **Strict reliability**: Record chỉ vào training khi `requested_date == business_date` + cả 2 giá hợp lệ
2. **Không leakage**: External features join theo `available_from`, không phải `observation_date`; US data luôn lag `t-1`
3. **Source quality tiers**: `historical_valid > archive_cross_check > current_only > unstable`
4. **Không giả lập premium**: LBMA proxy được flag `source_quality=proxy_futures_based`; không block pipeline vì thiếu 1 nguồn
5. **Encoding**: Chạy với `PYTHONUTF8=1` để hỗ trợ Unicode Vietnamese (─, đặc tắc)

---

Built with [Claude Code](https://claude.com/claude-code) by Anthropic.
