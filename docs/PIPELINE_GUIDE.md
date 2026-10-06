# Pipeline Guide — VN Gold Market Analysis

Hướng dẫn chi tiết từng bước chạy pipeline, ghi chú những gì mỗi bước đã làm, output sinh ra, và cách tái thí nghiệm.

---

## Tổng quan Pipeline

Pipeline gồm **11 bước**, chia thành 3 nhóm:

```
┌─────────────────────────────────────────────────────────────────┐
│  Nhóm 1: Thu thập & Validation (bước 1–5)                       │
│  Output: các file CSV thô trong data/lake/                       │
├─────────────────────────────────────────────────────────────────┤
│  Nhóm 2: Làm giàu & Enrichment (bước 6–9)                       │
│  Output: các bảng làm giàu trong data/lake/gold_prices/          │
├─────────────────────────────────────────────────────────────────┤
│  Nhóm 3: Tích hợp Master Panel (bước 10–11)                      │
│  Output: 4 master tables trong data/lake/enriched/master/        │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Cập nhật dữ liệu mới hàng ngày (Incremental Update)

Để cập nhật dữ liệu mới nhất từ ngày cuối cùng trong database đến hôm nay mà **không cần crawl lại 15 năm từ đầu**:

```powershell
# Tự động nhận diện ngày mới nhất trong lake, kéo phần còn thiếu đến hôm nay:
python scripts/pipeline/update_incremental.py

# Hoặc chỉ định rõ ngày cần lấy:
python scripts/pipeline/update_incremental.py --to 2026-10-06
```

Lệnh này sẽ:
1. Nhận diện ngày mới nhất trong `data/lake/domestic_gold_quotes.csv`.
2. Kéo giá vàng SJC chính thức các ngày còn thiếu.
3. Kéo chuỗi giá thế giới mới nhất từ `yfinance` (`GC=F`, `GLD`, `USDVND=X`, `^VIX`, v.v.).
4. Tự động tính toán lại phân rã Premium decomposition.

---

## Nhóm 1: Thu thập & Validation

### Bước 1 — Audit Sources

```powershell
python scripts/pipeline/source_audit.py --out-dir data/experiments/audit_output
```

**Đã làm gì:**
- Crawl thử mọi nguồn đã đăng ký với các ngày mẫu (sample dates) để kiểm tra source còn sống không
- Đánh giá reliability tier: `historical_valid`, `archive_cross_check`, `current_only`, `unstable`
- Phát hiện encoding issues, anti-bot blocks, stale data, unit mismatches
- Xuất kết quả JSON: `data/experiments/audit_output/source_audit.json`

**Output:**
- `data/experiments/audit_output/source_audit.json` — audit results
- Console report: source name, status (ok/blocked/stale), record count, date range

**Tái thí nghiệm:**
```powershell
# Xóa audit cũ và chạy lại
Remove-Item data/experiments/audit_output/* -Recurse
python scripts/pipeline/source_audit.py --out-dir data/experiments/audit_output
```

### Bước 2 — Build Source Registry

```powershell
python scripts/pipeline/build_source_registry.py --audit-json data/experiments/audit_output/source_audit.json
```

**Đã làm gì:**
- Đọc kết quả audit từ bước 1
- Tạo registry YAML + CSV: `configs/source_registry_audited.{yaml,csv}`
- Registry này được `reliability.py` đọc khi crawl — nó biết source nào đáng tin, crawl thế nào

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/source_audit.py --out-dir data/experiments/audit_output
python scripts/pipeline/build_source_registry.py --audit-json data/experiments/audit_output/source_audit.json
```

### Bước 3 — Backfill Domestic Target (Historical-Valid Only)

```powershell
python scripts/pipeline/backfill_target.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/domestic_target
```

**Đã làm gì:**
- Chỉ giữ records pass strict filter: `requested_date == business_date` + cả `buy_price` và `sell_price` đều non-null và hợp lý
- Đọc từ `data/lake/raw_gold_15y/normalized/` (output của bước crawl ở bước 3.5)
- Sinh 2 files: `domestic_gold_rows.csv` (raw accepted) + `domestic_gold_quotes.csv` (deduped, one row per date)
- Source chính: `sjc_official_history` — SJC official archive, duy nhất pass historical-valid

**Output:**
- `data/lake/domestic_target/normalized/domestic_gold_quotes.csv` (~61,665 rows)
- `data/lake/domestic_target/normalized/domestic_gold_rows.csv` (raw, chưa dedup)

**Quan trọng**: Đây là **training label duy nhất** cho model. Các raw crawl khác (PNJ, WebGia) dùng để cross-check, không dùng làm target.

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/backfill_target.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/domestic_target
```

### Bước 3.5 — Raw Full Crawl (có sẵn dữ liệu, không cần chạy lại)

**Đã làm gì:**
- Crawl lịch sử 2010-2026 từ 4 nguồn: `sjc_official`, `webgia_sjc_archive`, `giavang_sjc_archive`, `giavang_pnj_archive`
- Resume-enabled: dừng giữa chừng, chạy lại thì bỏ qua ngày đã có
- Output: **96,326 rows** raw (chưa filter historical-valid)
  - `giavang_pnj_archive.csv`: 61,778 rows
  - `webgia_sjc_archive.csv`: 24,994 rows
  - `giavang_sjc_archive.csv`: 9,492 rows

**Tái thí nghiệm (chỉ nếu cần re-crawl):**
```powershell
python scripts/pipeline/crawl_raw_gold_history.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/raw_gold_15y --resume
```

### Bước 4 — External Features V1

```powershell
python scripts/pipeline/collect_external_features.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/market_data/v1
```

**Đã làm gì:**
- **FX rates**: SBV central rate + Vietcombank commercial rates (USD/VND buy/sell/mid)
- **Global market series**: yfinance (GC=F, SI=F, CL=F, ^VIX, DX-Y.NYB, USDVND=X, ^GSPC) + FRED CSV windowed (DGS10, DCOILWTICO, VIXCLS, DTWEXBGS) + World Bank Vietnam macro + GSO macro-monitor + vnstock VNINDEX
- Mỗi record có `available_from` = ngày mà data point có thể dùng được

**Output:**
- `data/lake/market_data/v1/normalized/fx_rates.csv` (3,961 rows)
- `data/lake/market_data/v1/normalized/global_market_series.csv` (41,584 rows)
- `data/lake/market_data/v1/normalized/macro_series.csv` (31,104 rows)
- `data/lake/market_data/v1/normalized/vn_market_series.csv` (3,917 rows)

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/collect_external_features.py --from 2011-07-06 --to 2026-07-11 --out-dir data/lake/market_data/v1
```

---

## Nhóm 2: Làm giàu & Enrichment

### Bước 5 — Enhanced Features V2

```powershell
python scripts/pipeline/collect_enhanced_features.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2
```

**Đã làm gì:**
- **FRED expanded**: Thêm 12 series mới: DFII10 (real TIPS yield), T10YIE/T5YIE (breakeven inflation), STLFSI2 (financial stress), NFCI, BAA10Y/AAA10Y (corp yields), M2SL, GLD close
- **GC=F futures basis**: Daily close của gold futures từ yfinance
- **GLD ETF proxy**: SPDR Gold Shares làm proxy cho vàng tài chính
- **GLD shares outstanding**: Từ SEC XBRL + snapshot — proxy cho ETF flows
- **SBV deposit rates**: JSON CMS của SBV (warning: chỉ có 43 rows, là policy announcements, KHÔNG phải time series)
- **Event panel generation**: Tết proximity, Thần Tài, wedding season, global crisis windows
- **Sentiment**: Rule-based signals (VIX, gold momentum, USD/VND, event anchor) — báo cáo do crawl4ai VN news bị anti-bot chặn

**Output:**
- `data/lake/market_data/v2/normalized/macro_enhanced.csv` (38,882 rows)
- `data/lake/market_data/v2/normalized/futures_basis.csv`
- `data/lake/market_data/v2/normalized/etf_proxy.csv`
- `data/lake/market_data/v2/normalized/gld_shares.csv`
- `data/lake/market_data/v2/normalized/sbv_deposit_rates.csv` (43 rows)
- `data/lake/market_data/v2/normalized/news_sentiment.csv` (3,138 rule-based signals)

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/collect_enhanced_features.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2
```

### Bước 5.5 — LBMA Proxy Backfill

```powershell
python scripts/pipeline/collect_lbma_proxy.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2
```

**Đã làm gì:**
- **Strategy 1 (thất bại)**: World Bank monthly gold (PXGONGUSDM) → HTTP 502 Bad Gateway
- **Strategy 2 (thành công)**: GC=F daily close từ yfinance → 4,153 rows, 2010-2026
  - `series_id=GCF_DAILY_CLOSE_USD_OZ`, `source_quality=proxy_futures_based`
- **Strategy 3**: LBMA today.json → chỉ có 7 rows (hôm nay AM/PM fix), không backfill được

**Báo cáo nghiên cứu quy định**: GC=F được chấp nhận như LBMA proxy với flag `source_quality=proxy_futures_based`. Pipeline KHÔNG bị block vì thiếu LBMA thật.

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/collect_lbma_proxy.py --from 2010-01-01 --to 2026-07-11 --out-dir data/lake/market_data/v2
```

### Bước 6 — Premium Decomposition

```powershell
python scripts/pipeline/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices
```

**Đã làm gì:**
- Tính 3 biến then chốt:
  - `global_gold_vnd_per_luong` = LBMA USD/oz × USD/VND ÷ (31.103g/oz ÷ 1.205g/chi ÷ 37.5chi/luong)
  - `domestic_premium` = SJC sell_price − global_gold_vnd_per_luong
  - `spread_pct` = (sell − buy) / sell × 100
- Formula chuyển đổi: 1 troy oz = 31.1035g; 1 chi = 1.205g; 1 luong = 37.5 chi → 1 oz ≈ 0.6886 luong

**Output:**
- `data/lake/gold_prices/normalized/gold_daily_enriched.csv` (4,991 dates, 4,030 có premium = 81% coverage)

**Tại sao 81% chứ không phải 100%?**
- Một số ngày không có LBMA/GC=F data (NYSE closed, holidays)
- Một số ngày không có USD/VND rate
- Khi thiếu bất kỳ thành phần nào trong công thức premium, ngày đó premium = null

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices
```

### Bước 7 — Event Panel

```powershell
python scripts/pipeline/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices
```

**Đã làm gì:**
- Sinh 1,850 events, 13 loại, từ rule + known calendars:
  - **Tết proximity**: 2 tuần trước và sau Tết Nguyên Đán
  - **Thần Tài**: Ngày vía Thần Tài (mùng 10 tháng Giêng âm lịch)
  - **Wedding season**: Apr-May và Aug-Oct (mùa cưới VN)
  - **Policy events**: NHNN auction announcements, import restrictions, inspection notices
  - **Geopolitical/financial crisis**: COVID, 2008 crisis, 2022 rate hikes
  - **Calendar features**: weekday, month sin/cos (known-in-advance, không gây leakage)

**Output:**
- `data/lake/gold_prices/normalized/gold_event_panel.csv` + `data/lake/enriched/master/normalized/event_regime_panel.csv` (1,850 events)

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices
```

---

## Nhóm 3: Tích hợp Master Panel

### Bước 8 — Build Master Panel (4 Tables)

```powershell
python scripts/pipeline/build_master_panel.py --tables all
```

**Đã làm gì:**
Đây là bước **quan trọng nhất** — nó đọc tất cả outputs từ các bước trước và tích hợp thành 4 bảng chuẩn:

| Bảng | Input sources | Logic |
|---|---|---|
| `gold_domestic_daily_panel` | domestic_target + raw_gold_15y | Forward-fill buy/sell, compute spread, flag consistency |
| `global_reference_daily` | market_data/v1 + v2 (FX, FRED, yfinance, LBMA, futures, GLD, macro_enhanced, news_sentiment) | Join by date, forward-fill low-freq series, 8 new V2 fields (silver futures, gold futures, USD/VND market rate, TIPS yield, breakeven inflation, St Louis stress, Chicago Fed NFCI) |
| `vn_macro_asof_panel` | macro_series (v1) + vn_macro_forecasting (v2) | Join by `available_from`, forward-fill nulls within (source, series_id) group |
| `event_regime_panel` | gold_event_panel | Dedup, sort by date |

**Output:**
- `data/lake/enriched/master/normalized/gold_domestic_daily_panel.csv`
- `data/lake/enriched/master/normalized/global_reference_daily.csv`
- `data/lake/enriched/master/normalized/vn_macro_asof_panel.csv`
- `data/lake/enriched/master/normalized/event_regime_panel.csv`
- Kèm manifest JSON cho mỗi table (row count, null counts, columns)

**Có thể chạy 1 table riêng (nhanh hơn):**
```powershell
python scripts/pipeline/build_master_panel.py --table global_reference_daily
python scripts/pipeline/build_master_panel.py --table vn_macro_asof_panel
```

**Tái thí nghiệm:**
```powershell
python scripts/pipeline/build_master_panel.py --tables all
```

### Bước 9 — Quality Report

```powershell
$env:PYTHONUTF8="1"; python scripts/pipeline/quality_report.py --data-lake data/lake/domestic_target --from 2011-07-06 --to 2026-07-11
```

**Đã làm gì:**
- Kiểm tra data quality trên domestic target:
  - Date range coverage (2011-07-06 → 2026-07-11)
  - Buy/sell price validity (non-null, non-negative, trong range hợp lý)
  - Source distribution
  - Outlier detection (returns > threshold)
- In ra console summary + xuất report JSON

**Output:**
- Console: row count, date range, source breakdown, outlier count
- `data/experiments/audit_output/` (nếu có)

---

## Visual Pipeline Flow

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌──────────────┐
│  source_audit │────▶│ build_source  │────▶│ crawl_raw_gold  │────▶│ backfill_    │
│  (bước 1-2)  │     │ _registry     │     │ _history        │     │ target       │
│              │     │ (bước 2)     │     │ (bước 3.5)     │     │ (bước 3)     │
└─────────────┘     └──────────────┘     └────────────────┘     └──────┬───────┘
                                                                       │
                                                                       ▼
                                                              ┌────────────────┐
                                                              │ collect_external│
                                                              │ _features v1    │
                                                              │ (bước 4)        │
                                                              └───────┬────────┘
                                                                      │
                                                                      ▼
                                                              ┌────────────────┐
                                                              │ collect_        │
                                                              │ enhanced v2     │◄── collect_lbma_proxy (bước 5.5)
                                                              │ (bước 5)        │
                                                              └───────┬────────┘
                                                                      │
                                                              ┌───────┴────────┐
                                                              │ build_premium   │
                                                              │ decomposition   │◄── build_event_panel (bước 7)
                                                              │ (bước 6)        │
                                                              └───────┬────────┘
                                                                      │
                                                                      ▼
                                                              ┌────────────────┐
                                                              │ build_master_    │
                                                              │ panel            │◄── Bước 8: Tích hợp 4 tables
                                                              │ (bước 8)         │
                                                              └────────────────┘
                                                                      │
                                                                      ▼
                                                              ┌────────────────┐
                                                              │ quality_report   │
                                                              │ (bước 9)         │
                                                              └────────────────┘
```

---

## So sánh Plan vs Thực tế

| Bước trong Plan | Trạng thái | Ghi chú |
|---|---|---|
| 1A. Re-materialize V2 data | ✅ Done | 38,882 rows macro_enhanced, futures basis, etf_proxy |
| 1B. Fix LBMA historical | ⚠️ Partial | GC=F proxy: 4,153 rows. World Bank monthly: 502 error. LBMA JSON: 7 rows only. Chấp nhận được với flag proxy |
| 1C. Fix FRED integration into master panel | ✅ Done | 8 new fields trong global_reference_daily (paths + indexing fixed) |
| 1D. Fix VN deposit rates | ⚠️ Blocked | SBV API trả policy announcements, không phải time series. sbv_deposit_rates: 43 rows, vn_deposit_rates: 0 non-null |
| 2A. New domestic current sources (DOJI, Phu Quy...) | ❌ Not started | crawl4ai bị anti-bot chặn trên VN news sites. Task #5 pending |
| 2B. Expand PNJ historical | ❌ Not started | Raw crawl đã có 96K rows — có thể đủ |
| 2C. Expand archive cross-check | ⚠️ Low priority | Hiện có 4 sources, coverage đã tốt |
| 3A. News/sentiment full backfill | ✅ Done | Thay 168-row RSS bằng 3,138 rule-based signals |
| 3B. Expand policy event panel | ⚠️ Partial | 1,850 events. Cần bổ sung thêm ~1,150 events để đạt 3,000 |
| 3C. GPR proper daily index | ❌ Blocked | Chỉ có VIX proxy. True GPR cần GDELT/ACLED API |
| 4. Premium decomposition | ✅ Done | 4,991 dates, 81% coverage |
| 5. Final integration & QA | ✅ Done | 4 master tables, quality report pass |

---

## Troubleshooting

**`UnicodeEncodeError: 'charmap' codec can't encode '─'`**
→ Set `$env:PYTHONUTF8 = "1"` trước khi chạy

**crawl4ai bị chặn (anti-bot)**
→ VnExpress, Tuổi Trẻ, Thanh Niên đều có Cloudflare/bot detection. Workaround: dùng rule_sentiment.py thay vì news crawl. Đây là expected behavior.

**World Bank API 502**
→ Endpoint `PXGONGUSDM` thỉnh thoảng lỗi. Fallback: dùng GC=F yfinance qua collect_lbma_proxy.py

**FRED API key thiếu**
→ Pipeline tự động fallback sang FRED windowed CSV download (không cần API key). Chỉ cần `yfinance` + requests.

**MemoryError khi crawl raw_gold_15y**
→ Dùng `--resume` flag — pipeline tự động bỏ qua ngày đã crawl xong.

**Gold target bị empty sau backfill**
→ Kiểm tra source_audit.json: nếu `sjc_official_history` status != `ok`, source đó không pass historical-valid filter.
