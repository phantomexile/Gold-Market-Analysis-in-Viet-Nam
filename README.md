# VN Gold Market Analysis

Pipeline thu thập và xử lý dữ liệu giá vàng Việt Nam (SJC) và các yếu tố vĩ mô toàn cầu để forecasting đa kỳ hạn (1, 3, 5 năm).

**Nguyên tắc cốt lõi**: Một record chỉ được chấp nhận làm dữ liệu huấn luyện lịch sử khi `requested_date == business_date` và cả giá mua/bán đều hợp lệ. Nguồn current-only KHÔNG bao giờ được trộn vào nhãn huấn luyện lịch sử.

---

## Cấu trúc thư mục

```
vn-gold-market-analysis/
├── CLAUDE.md                  # Context file cho Claude Code (quy tắc nghiệp vụ)
├── pyproject.toml             # Dependencies & build config
├── requirements.txt           # Fallback deps
├── .env                       # API keys (gitignored)
├── .env.example               # Template cho API keys
│
├── configs/                   # Source registry đã audit
│   ├── source_registry_audited.yaml
│   └── source_registry_audited.csv
│
├── src/gold_collectors/       # Shared collectors, parsers, models
│   ├── collectors.py          # SJC, PNJ, DOJI, WebGia collectors
│   ├── parsing.py             # Date/number parsers cho VN format
│   ├── http.py                # Cached HTTP client với throttling
│   ├── reliability.py         # Source reliability audit logic
│   ├── models.py              # GoldPriceRecord dataclass
│   └── full_pipeline.py       # DataLakeWriter, bootstrap helpers
│
├── scripts/pipeline/          # Production collection & QA CLIs
│   ├── crawl_raw_gold_history.py   # Crawl 15y raw gold từ mọi nguồn
│   ├── collect_external_features.py # FX, yfinance, FRED, World Bank, GSO
│   ├── collect_enhanced_features.py # FRED expanded, futures basis, GLD, events
│   ├── collect_lbma_proxy.py        # LBMA AM/PM backfill (GC=F proxy)
│   ├── collect_vn_news_backfill.py  # VN news crawl via crawl4ai
│   ├── rule_sentiment.py            # Rule-based sentiment (fallback)
│   ├── build_event_panel.py         # Tết, Thần Tài, wedding, policy events
│   ├── build_premium_decomposition.py # premium = domestic - global(vnd/luong)
│   ├── build_master_panel.py        # ⭐ Tích hợp 4 master tables
│   ├── backfill_target.py          # Historical-valid target only
│   ├── source_audit.py             # Audit source reliability
│   ├── build_source_registry.py    # Rebuild registry sau audit
│   ├── quality_report.py           # QA: leakage, coverage, outliers
│   └── extract_vn_macro.py         # High-signal VN macro subset
│
├── tests/                     # Unit tests
│   ├── test_collectors.py
│   ├── test_full_pipeline.py
│   └── test_reliability.py
│
├── docs/
│   ├── deep-research-report.md      # Báo cáo nghiên cứu sâu (framework, model roadmap)
│   ├── PIPELINE_GUIDE.md            # 📘 Hướng dẫn chạy pipeline
│   ├── DATA_DICTIONARY.md           # 📖 Schema từng bảng dữ liệu
│   └── SOURCE_CODE_MAP.md           # 📋 Giải thích từng module code
│
├── data/lake/                 # Runtime outputs (gitignored theo cấu trúc)
│   ├── raw_gold_15y/normalized/    # Raw crawl 2010-2026, mọi nguồn
│   ├── domestic_target/normalized/ # Historical-valid only (training labels)
│   ├── market_data/v1/normalized/  # FX, yfinance, FRED, WB, GSO, vnstock
│   ├── market_data/v2/normalized/  # FRED expanded, futures, ETF, events
│   └── enriched/master/normalized/ # ⭐ 4 master tables (output cuối)
│
└── data/README.md             # Chính sách git-track cho data/
```

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
python scripts/pipeline/source_audit.py --out-dir data/experiments/audit_output

# Xây registry mới từ kết quả audit
python scripts/pipeline/build_source_registry.py --audit-json data/experiments/audit_output/source_audit.json

# ── Bước 2: Backfill domestic target (historical-valid only) ──
# Chỉ giữ records có requested_date == business_date và cả 2 giá hợp lệ
python scripts/pipeline/backfill_target.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/domestic_target

# ── Bước 3: Raw full crawl (resume-enabled) ──────────────────
# Crawl lịch sử giá vàng từ mọi nguồn, có thể dừng/chạy lại
python scripts/pipeline/crawl_raw_gold_history.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/raw_gold_15y --resume

# ── Bước 4: External features v1 ─────────────────────────────
# FX rates (SBV + Vietcombank), global market series (yfinance + FRED),
# Vietnam macro (World Bank + GSO), VNINDEX (vnstock)
python scripts/pipeline/collect_external_features.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/market_data/v1

# ── Bước 5: Enhanced features v2 ────────────────────────────
# FRED expanded (DXY real yields, TIPS, stress indices),
# futures basis (GC=F), GLD ETF, VN deposit rates, event panel, sentiment
python scripts/pipeline/collect_enhanced_features.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2

# ── Bước 6 (optional): LBMA proxy backfill ──────────────────
# World Bank monthly gold + GC=F daily as LBMA proxy
python scripts/pipeline/collect_lbma_proxy.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2

# ── Bước 7 (optional): Rule-based sentiment ─────────────────
# Tín hiệu sentiment từ VIX + gold momentum + USD/VND + event anchor
python scripts/pipeline/rule_sentiment.py --from 2010-01-01 --to 2026-07-11

# ── Bước 8: Premium decomposition ───────────────────────────
# Tính premium = SJC mid - (LBMA USD/oz × USD/VND × conversion_factor)
python scripts/pipeline/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices

# ── Bước 9: Event panel ──────────────────────────────────────
# Sinh events: Tết proximity, Thần Tài, wedding season, policy, crisis
python scripts/pipeline/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices

# ── Bước 10: Build master panel (4 tables) ──────────────────
# Tích hợp tất cả nguồn vào 4 bảng chuẩn
python scripts/pipeline/build_master_panel.py --tables all

# ── Bước 11: Quality report ──────────────────────────────────
# Kiểm tra: leakage, coverage, outliers, source reliability
python scripts/pipeline/quality_report.py --data-lake data/lake/domestic_target --from 2011-07-06 --to 2026-07-11
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
$env:PYTHONUTF8="1"; python scripts/pipeline/quality_report.py --data-lake data/lake/domestic_target --from 2011-07-06 --to 2026-07-11
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
python scripts/pipeline/crawl_raw_gold_history.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/raw_gold_15y --resume

# Chạy 1 table master panel cụ thể (nhanh hơn --tables all)
python scripts/pipeline/build_master_panel.py --table global_reference_daily
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
