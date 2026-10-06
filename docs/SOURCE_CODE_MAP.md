# Source Code Map — VN Gold Market Analysis

Giải thích từng module code: cái nào làm gì, input/output, data flow.

---

## Cấu trúc source

```
src/gold_collectors/          # Shared library — collectors, parsers, models
scripts/pipeline/             # Production CLIs — mỗi file = 1 pipeline stage
tests/                        # Unit tests
```

---

## src/gold_collectors/ — Shared Library

### models.py — Data Models

`GoldPriceRecord`: Frozen dataclass định nghĩa 1 record giá vàng.

```python
@dataclass(frozen=True)
class GoldPriceRecord:
    source: str          # sjc_official, pnj_archive, ...
    provider: str        # Tên website/API provider
    branch: str | None   # Nhánh (URL path)
    gold_type: str       # Loại sản phẩm: sjc_gold_bar, pnj_gold, ...
    buy_value: float | None  # Giá mua vào (VND/lượng)
    sell_value: float | None # Giá bán ra (VND/lượng)
    unit: str            # VND/luong
    currency: str        # VND
    observed_at: str | None  # ISO timestamp crawl
    reference_date: str | None  # business_date (đã normalize)
    raw_payload_hash: str  # SHA1 của payload gốc (audit trail)
    metadata: dict       # Extra: quote_time, source_quality, ...
```

**Dùng ở đâu**: Kết quả crawl từ mọi collector đều trả về `GoldPriceRecord`, sau đó được serialize sang CSV.

### collectors.py — Web Collectors

4 collectors chính:

| Class | Nguồn thu thập | Mode | Output |
|---|---|---|---|
| `SjcOfficialCollector` | sjc.com.vn — SJC chính thức | Historical archive + current page | GoldPriceRecord |
| `PnjCurrentCollector` | pnj.com.vn — PNJ | Current page (HTML) | GoldPriceRecord |
| `DojiCurrentHtmlCollector` | doji.com.vn — DOJI | Current page (HTML) | GoldPriceRecord |
| `ThirdPartyArchiveCollector` | webgia.com, giavang.net — Archive | Archive history (by date) | GoldPriceRecord |

**Logic chính:**
- Mỗi collector có `collect(date_range)` → yield `GoldPriceRecord`
- `ThirdPartyArchiveCollector` xây URL theo pattern `<base>/<year>/<month>/<day>` và parse HTML
- Tất cả đều gọi qua `CachedHttpClient` (có cache disk + throttling)

### parsing.py — Date/Number Parsers

Xử lý các format VN đặc thù:

| Hàm | Input | Output | Ví dụ |
|---|---|---|---|
| `normalize_date(s)` | "28/07/2024", "2024-07-28", "07-28-2024" | "2024-07-28" | Normalize mọi format date về ISO |
| `parse_number(s)` | "68.500.000", "68,500,000", "68500" | 68500.0 | Xử lý . và , theo locale VN |
| `extract_gold_type(s)` | "Vàng SJC 9999", "Nhẫn PNJ" | sjc_gold_bar / gold_jewelry | Phân loại sản phẩm vàng |

**Vấn đề đã fix**: VN format dùng `.` làm thousands separator, `,` làm decimal — ngược với US. Parser phải detect và xử lý đúng.

### http.py — Cached HTTP Client

`CachedHttpClient`: HTTP client với 2 lớp cache:

1. **Disk cache**: Mọi response được lưu vào `data/experiments/http_cache/` keyed by URL hash. Nếu đã có cache, KHÔNG gọi HTTP.
2. **Throttling**: Minimum 0.35s giữa mỗi request đến cùng 1 domain (tránh bị chặn).

**Cách dùng:**
```python
from gold_collectors.http import CachedHttpClient
client = CachedHttpClient(cache_dir="data/experiments/http_cache")
html = client.get("https://example.com/gold-prices")
```

### reliability.py — Source Reliability & Audit

Module quan trọng nhất decide record nào pass historical-valid filter.

**Hàm chính:**

| Hàm | Mô tả |
|---|---|
| `business_date_from_record(rec)` | Extract business_date từ `observed_at` + ngày làm việc VN (bỏ Tết, weekend) |
| `collect_historical_rows(source, from, to)` | Crawl historical data từ 1 source, yield (date, record) |
| `accepted_historical_sources()` | Trả về list sources đã audit pass historical-valid |
| `read_registry()` | Đọc `configs/source_registry_audited.yaml` |

**Strict filter logic:**
```
record pass historical-valid KHÍ:
  observed_at.date == requested_date   // không có forward-fill
  AND buy_value is not None AND sell_value is not None
  AND buy_value > 0 AND sell_value > 0
  AND sell_value >= buy_value           // spread phải >= 0
  AND 50,000 <= sell_value <= 150,000  // sanity range VND/luong
```

### full_pipeline.py — DataLakeWriter & Bootstrap

| Class/Function | Mô tả |
|---|---|
| `DataLakeWriter` | Helper ghi CSV/Parquet vào data/lake/ — tự động tạo directory, write manifest |
| `bootstrap()` | Đảm bảo imports từ `src/` hoạt động khi chạy script từ `scripts/pipeline/` — xử lý sys.path |
| `date_range(from, to)` | Generator yield mỗi ngày trong range |

---

## scripts/pipeline/ — Pipeline Scripts

Mỗi script là 1 pipeline stage độc lập, chạy bằng `python scripts/pipeline/<name>.py [args]`.

### pipeline/_bootstrap.py

Không chạy trực tiếp. Đảm bảo `src/gold_collectors` có thể import được từ bất kỳ working directory nào.

```python
# Add src/ to sys.path, sẵn sàng import gold_collectors.*
```

---

### pipeline/source_audit.py → build_source_registry.py

**Bộ đôi audit**: Chạy lần đầu hoặc khi có nguồn mới.

1. `source_audit.py` crawl thử 1 sample dates từ mỗi source → đánh giá pass/fail
2. `build_source_registry.py` đọc audit JSON → sinh `configs/source_registry_audited.{yaml,csv}`

**Khi nào chạy lại**: Khi thêm source mới, hoặc source cũ bị thay đổi HTML structure.

---

### pipeline/crawl_raw_gold_history.py

**Input**: Date range, output dir, list sources
**Output**: `data/lake/raw_gold_15y/normalized/raw_gold_history.csv` + per-source files

**Logic:**
1. Với mỗi source, crawl date-by-date
2. Lưu raw HTML vào HTTP cache
3. Parse HTML → `GoldPriceRecord`
4. Serialize sang CSV (date, source, gold_type, buy, sell, spread, unit)
5. Support `--resume`: nếu file output đã tồn tại, skip các ngày đã có

**Thời gian ước tính**: ~2–3 giờ cho 2010–2026 (4 sources, 0.35s throttle).

---

### pipeline/backfill_target.py

**Input**: domestic_target_output_dir, date range
**Output**: `domestic_gold_quotes.csv` (historical-valid only)

**Logic:**
1. Đọc `raw_gold_history.csv`
2. Với mỗi row, gọi `reliability.business_date_from_record()`
3. Chỉ giữ row nếu: `requested_date == business_date` + buy & sell non-null
4. Dedup: 1 date = 1 row (nếu có nhiều source cho cùng date, ưu tiên source_quality cao)
5. Source hiện tại qua filter: chỉ `sjc_official_history`

**Quan trọng**: Output này là **gold standard** — dùng làm Y trong training.

---

### pipeline/collect_external_features.py (V1)

**Input**: Date range, output dir
**Output**: 4 CSV files trong `data/lake/market_data/v1/normalized/`

**Logic — gọi lần lượt:**

| Hàm | Source | Series |
|---|---|---|
| `collect_sbv_central_fx_history()` | SBV API | USD/VND central rate |
| `collect_vietcombank_fx()` | Vietcombank XML | buy/sell/mid USD/VND |
| `collect_yfinance_prices()` | yfinance | GC=F, SI=F, CL=F, ^VIX, DX-Y.NYB, USDVND=X, ^GSPC |
| `collect_fred_series()` | FRED CSV download | DGS10, DCOILWTICO, VIXCLS, DTWEXBGS |
| `collect_worldbank_macro()` | World Bank API | VN macro annual indicators |
| `collect_gso_macro_monitor_features()` | GSO CSV | Vietnam macro monthly/quarterly |
| `collect_optional_vnstock_features()` | vnstock | VNINDEX |

Mỗi function trả về list[dict] — mỗi dict = 1 record với `date`, `series_id`, `value`, `available_from`, `source`.

---

### pipeline/collect_enhanced_features.py (V2)

**Input**: Date range, output dir
**Output**: Files trong `data/lake/market_data/v2/normalized/`

**So với V1, V2 thêm:**
- FRED JSON API cho expanded series (DFII10, T10YIE, T5YIE, STLFSI2, NFCI, BAA10Y, AAA10Y, M2SL)
- GLD ETF (GLD close + volume)
- GLD shares outstanding (SEC XBRL)
- GC=F futures basis (GC=F daily)
- SBV deposit rates (JSON CMS)
- Event panel generation (Tết, Thần Tài, wedding, crisis windows)
- News sentiment (rule-based fallback)

**Cách hoạt động:**
```python
# FRED JSON API — tự động paging và dedup
fetch_fred_series("DFII10", start="2010-01-01", end="2026-07-11")

# yfinance — batch download
ticker = yf.Ticker("GC=F")
frame = ticker.history(start=..., end=...)

# crawl4ai — intercept Next.js data fetch trên LBMA page
# (không dùng cho backfill, chỉ cho today's AM/PM fix)
```

---

### pipeline/collect_lbma_proxy.py

**Strategy cascade:**
1. World Bank monthly PXGONGUSDM → 502 error (không dùng được)
2. yfinance GC=F daily close → ✅ 4,153 rows (2010–2026), flag `proxy_futures_based`
3. LBMA today.json → 7 rows (chỉ hôm nay)

**Output**: `lbma_proxy.csv` merged vào `lbma_spot.csv` (nếu đã có today's AM/PM).

---

### pipeline/collect_vn_news_backfill.py

**Đã thử**: crawl4ai scrapedirect trên 4 VN news sites (vnexpress, tuoitre, thanhnien, vietnamnet).

**Kết quả**: TẤT CẢ bị anti-bot chặn (Cloudflare, bot detection). Output = 0 rows.

**Workaround**: Dùng `rule_sentiment.py` thay thế.

---

### pipeline/rule_sentiment.py

**Logic** (không cần external news — dùng market data có sẵn):

```
Daily sentiment score = base 0
  + VIX contribution:
      VIX > 35 → +2.5 (extreme fear → gold safe haven)
      VIX > 25 → +1.5
      VIX > 20 → +0.5
      VIX < 12 → -1.5 (complacency)
  + Gold futures 30d momentum: clamp ±2 (return % / 10)
  + USD/VND 30d change (VND weakening → bullish gold): clamp ±2 (change% / 3)
  + Event anchor: high-severity events → ±1-2 (half-weight)

Clamp tổng: [-5.0, +5.0]
Bỏ qua ngày |score| < 0.1 (noise)
```

**Output**: `news_sentiment.csv` — 3,138 signals (bullish: 2,736, bearish: 402).

---

### pipeline/build_event_panel.py

**Logic — sinh events từ rules + known calendars:**

| Event Type | Source | Frequency |
|---|---|---|
| tet_proximity | Lunar calendar | Annual, 2 weeks around Tết |
| than_tai | Lunar calendar (mùng 10 tháng Giêng) | Annual |
| wedding_season | Known windows (Apr-May, Aug-Oct) | Annual |
| policy_auction | NHNN announcements + tagged dates | Irregular |
| policy_import_change | Import restriction changes | Irregular |
| policy_inspection | Market inspection events | Irregular |
| policy_rate_change | SBV rate decisions | Irregular |
| geopolitical_crisis | Known crisis windows (2022 war, 2020 COVID) | Irregular |
| financial_crisis | 2008 GFC, 2020 COVID crash | Irregular |
| calendar_rule | weekday, month sin/cos | Daily |

**Output**: `event_regime_panel.csv` — 1,850 events, 13 types.

---

### pipeline/build_premium_decomposition.py

**Input**: domestic_target (quotes) + market_data/v1 (FX + global)
**Output**: `data/lake/gold_prices/normalized/gold_daily_enriched.csv`

**Formula:**
```python
CHI_PER_OZ = 31.1034768 / 1.205         # = 25.807 chi/oz
LUONG_PER_OZ = CHI_PER_OZ / 37.5        # = 0.6886 luong/oz

global_gold_vnd_per_luong = lbma_usd_per_oz * usd_vnd_mid / LUONG_PER_OZ
premium = domestic_sell - global_gold_vnd_per_luong
premium_pct = premium / global_gold_vnd_per_luong * 100
consensus_mid = (buy + sell) / 2
```

---

### pipeline/build_master_panel.py ⭐

**Input**: TẤT CẢ normalized CSVs từ raw_gold_15y, domestic_target, market_data/v1, market_data/v2, gold_prices
**Output**: 4 master tables trong `data/lake/enriched/master/normalized/`

**4 tables:**

#### 1. gold_domestic_daily_panel
```
- Đọc raw_gold_history.csv + domestic_gold_quotes.csv
- Normalize gold_type (sjc_gold_bar, pnj_gold, gold_jewelly...)
- Tính spread/spread_pct nếu thiếu
- Thêm consensus rows: median buy/sell across (source, gold_type) per date
- Forward-fill buy/sell price trong mỗi (source, gold_type) group
- Gán source_quality từ registry (0.50–1.00)
```

#### 2. global_reference_daily
```
- Đọc global_market_series (v1) + futures_basis, etf_proxy, macro_enhanced, lbma_proxy, news_sentiment (v2)
- Map series_id → panel column (GM_SERIES map)
- Join FX: usd_vnd_mid, usd_vnd_buy, usd_vnd_sell
- Join macro series (yields, DXY, VIX, etc.)
- Forward-fill lower-frequency series on trading days
- Thêm 8 V2 fields: silver_futures, gold_futures, usd_vnd_market_rate,
  us_10y_real_tips_yield, us_10y_breakeven_inflation, us_5y_breakeven_inflation,
  st_louis_financial_stress, chicago_fed_nfci
```

#### 3. vn_macro_asof_panel
```
- Đọc macro_series (v1) + vn_macro_forecasting (v2)
- Forward-fill available_from nếu null (trong group source+series_id)
- Dedup by (source, series_id, observation_date)
- Giữ value nulls — KHÔNG impute
```

#### 4. event_regime_panel
```
- Đọc gold_event_panel.csv
- Dedup + sort by event_date
- Giữ nguyên all rows
```

---

### pipeline/quality_report.py

**Đọc** `domestic_target/normalized/domestic_gold_quotes.csv`
**In ra console:**
- Tổng số rows, date range
- Source breakdown
- Buy/sell null ratio
- Outlier detection (daily return > threshold)
- Coverage completeness

---

## Thứ tự dependency giữa scripts

```
source_audit.py ──▶ build_source_registry.yaml ──▶ (dùng bởi reliability.py)
                                                            │
crawl_raw_gold_history.py ──▶ raw_gold_history.csv ───────┘
                                                            │
                                                    backfill_target.py ──▶ domestic_gold_quotes.csv
                                                            │
collect_external_features.py ──▶ market_data/v1/            │
                                                            ▼
                                                  build_master_panel.py ──▶ 4 master tables
                                                            ▲
collect_enhanced_features.py ──▶ market_data/v2/            │
collect_lbma_proxy.py ──────────────────────┘
rule_sentiment.py ────────────────────┘
build_event_panel.py ─────────────────┘
build_premium_decomposition.py ───────┘
```

---

## Luồng dữ liệu tổng thể

```
                      ┌──────────────────────────┐
                      │  NGUYÊN TẮC              │
                      │  requested_date ==        │
                      │  business_date + cả 2 giá │
                      │  hợp lệ                   │
                      └────────────┬─────────────┘
                                   │
           ┌───────────────────────┴────────────────────────┐
           │                                                 │
  crawl_raw_gold_history.py                        backfill_target.py
  (96K rows raw, unfiltered)                       (61K rows, historical-valid)
           │                                                 │
           └──────────────────┬──────────────────────────────┘
                              ▼
                    gold_domestic_daily_panel
                    (training LABELS — buy/sell/spread)
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        collect_       collect_         build_event_
        external_       enhanced_        panel.py
        features.py     features.py      (1,850 events)
        (FX, yfinance,  (FRED exp,      (Tết, Thần Tài,
         FRED, WB, GSO)   futures, GLD)   policy, crisis)
              │               │               │
              └───────┬───────┴───────┬───────┘
                      ▼               ▼
              global_reference_daily  vn_macro_asof_panel
              (global ref: yields,   (macro VN/global
               DXY, VIX, FX, ...)    join by available_from)
                      │               │
                      └───────┬───────┘
                              ▼
                    🚀 4 Master Tables
                    Sẵn sàng cho modeling
```

---

## Key Design Decisions

| Quyết định | Lý do | File liên quan |
|---|---|---|
| Frozen dataclass cho GoldPriceRecord | Immutable — record là evidence, không thay đổi | src/gold_collectors/models.py |
| HTTP disk cache | Tránh re-crawl, tiết kiệm thời gian + bandwidth | src/gold_collectors/http.py |
| Bootstrap pattern | Cho phép chạy `python scripts/pipeline/xxx.py` trực tiếp mà không cần package install | scripts/pipeline/_bootstrap.py |
| `available_from` join | Chống data leakage trong backtest — external data chỉ available sau release_date | reliability.py |
| Rule-based sentiment fallback | crawl4ai bị anti-bot chặn trên VN sites — dùng market-driven signals thay | rule_sentiment.py |
| GC=F proxy cho LBMA | World Bank monthly API 502 — GC=F là proxy acceptable theo báo cáo | collect_lbma_proxy.py |
| Consensus rows trong master panel | Median across sources giảm impact của single-source outliers | build_master_panel.py |
| Forward-fill null spread | Một số source chỉ report sell, không report spread — auto derive | build_master_panel.py |
