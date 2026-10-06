# Data Dictionary — VN Gold Market Analysis

Mô tả chi tiết từng bảng dữ liệu trong pipeline: vị trí file, row count, columns, nguồn, và cách sử dụng.

---

## Raw Data Layer (data/lake/raw_gold_15y/)

### raw_gold_history.csv

| Thuộc tính | Giá trị |
|---|---|
| **Rows** | ~96,326 (aggregated từ 4 sub-files) |
| **Files** | `raw_gold_history.csv`, `giavang_pnj_archive.csv`, `webgia_sjc_archive.csv`, `giavang_sjc_archive.csv` |
| **Date range** | 2010-01-01 → 2026-07-07 |
| **Nguồn** | sjc_official, webgia_sjc_archive, giavang_sjc_archive, giavang_pnj_archive |
| **Unit** | VND/lượng (thousands) |

**Columns:**

| Column | Type | Mô tả |
|---|---|---|
| `date` | string | Ngày crawl (có thể khác với business_date) |
| `business_date` | string | Ngày làm việc thực tế (dùng để check historical-valid) |
| `source` | string | Tên nguồn: sjc_official, pnj_archive, webgia_sjc, ... |
| `gold_type` | string | Loại vàng: sjc_gold_bar, gold_jewelry, pnj_gold, ... |
| `buy` | float | Giá mua vào (VND/lượng) |
| `sell` | float | Giá bán ra (VND/lượng) |
| `spread` | float | (sell - buy), có thể null nếu source không cung cấp |
| `currency` | string | VND |
| `unit` | string | VND/luong (thousand) |
| `timestamp` | string | Thời điểm crawl (nếu source có) |

**Lưu ý**: File này là **raw, unfiltered**. KHÔNG dùng trực tiếp cho training. Phải qua `backfill_target.py` để filter. Dùng để cross-check và audit coverage.

---

## Domestic Target (data/lake/domestic_target/)

### normalized/domestic_gold_quotes.csv

| Thuộc tính | Giá trị |
|---|---|
| **Rows** | 61,665 |
| **Date range** | 2011-07-06 → 2026-07-11 |
| **Source** | sjc_official_history (chỉ 1 source pass strict filter) |
| **Unit** | VND/lượng |

**Columns:**

| Column | Type | Mô tả |
|---|---|---|
| `date` | string | Business date (YYYY-MM-DD) |
| `buy_price` | float | Giá mua vào SJC |
| `sell_price` | float | Giá bán ra SJC |
| `unit` | string | VND/luong |
| `source` | string | sjc_official_history |
| `provider` | string | Nguồn provider |

**Đây là bảng duy nhất dùng làm training label.** Nguyên tắc: mỗi date chỉ 1 row, buy và sell đều non-null, requested_date == business_date.

---

## Market Data V1 (data/lake/market_data/v1/)

### normalized/fx_rates.csv (3,961 rows)
FX rates từ SBV central + Vietcombank.

| Column | Mô tả |
|---|---|
| `date` | Ngày ghi nhận |
| `series_id` | sbv_central_fx_history / vietcombank_fx_xml |
| `usd_vnd_*` | Các biến tỷ giá USD/VND |
| `available_from` | Ngày data có thể dùng |

### normalized/global_market_series.csv (41,584 rows)
yfinance + FRED + World Bank global series.

| series_id (quan trọng) | Tên cột trong master panel | Source | Unit |
|---|---|---|---|
| `^VIX` | `vix` | FRED/yfinance | index |
| `DX-Y.NYB` | `dxy_index` | yfinance | index |
| `GC=F` | `gold_futures_close_usd_oz` | yfinance | USD/oz |
| `SI=F` | `silver_futures_close_usd_oz` | yfinance | USD/oz |
| `CL=F` | `oil_wti_usd_barrel` | yfinance | USD/barrel |
| `^GSPC` | `sp500_index` | yfinance | index |
| `DGS10` | `treasury_10y_pct` | FRED | % |
| `DCOILWTICO` | `oil_wti_usd_barrel` | FRED | USD/barrel |
| `DTWEXBGS` | `dxy_index` | FRED | index |
| `USDVND=X` | `usd_vnd_market_rate` | yfinance | VND |

### normalized/macro_series.csv (31,104 rows)
World Bank annual + GSO macro monitor.

| series_id (quan trọng) | Friendly name | Freq | Source |
|---|---|---|---|
| `FP.CPI.TOTL.ZG` | cpi_headline_yoy_pct | M | World Bank |
| `NY.GDP.MKTP.KD.ZG` | gdp_growth_yoy_pct | A | World Bank |
| `AIP_ISIC4_IX` | ip_total_index | M | GSO |
| `LEU_PT` | unemployment_rate_pct | Q | GSO |
| `TMG_CIF_USD` | total_imports_cif_m_usd | M | GSO |
| `VNM_VN_EOP_IX` | vnindex_eop | M | GSO |

### normalized/vn_market_series.csv (3,917 rows)
vnstock VNINDEX.

---

## Market Data V2 (data/lake/market_data/v2/)

### normalized/macro_enhanced.csv (38,882 rows)
FRED expanded — 12 series từ FRED JSON API.

| series_id | Friendly name | Unit | Frequency |
|---|---|---|---|
| `DFII10` | us_10y_real_tips_yield | pct | D |
| `DGS10` | us_10y_nominal | pct | D |
| `T10YIE` | us_10y_breakeven_inflation | pct | D |
| `T5YIE` | us_5y_breakeven_inflation | pct | D |
| `VIXCLS` | vix | index | D |
| `DTWEXBGS` | dxy_broad | index | D |
| `STLFSI2` | st_louis_financial_stress | index | W |
| `NFCI` | chicago_fed_national_fin_conditions | index | W |
| `BAA10Y` | baa_corp_bond_yield | pct | D |
| `AAA10Y` | aaa_corp_bond_yield | pct | D |
| `M2SL` | m2_money_supply | billions_usd | M |
| `GLD` | gld_spdr_gold_etf_close | usd | D |

### normalized/futures_basis.csv
COMEX GC=F daily close.

| Column | Mô tả |
|---|---|
| `date` | Trading date |
| `gc_f_close` | GC=F close price |
| `gc_f_volume` | Volume (nếu có) |
| `gc_f_open` | Open (nếu có) |

### normalized/etf_proxy.csv
GLD SPDR Gold Shares ETF — proxy cho vàng tài chính.

| Column | Mô tả |
|---|---|
| `gld_close` | Close price USD |
| `gld_volume` | Trading volume |

### normalized/gld_shares.csv
GLD shares outstanding từ SEC XBRL — proxy cho ETF flows (vốn vào/ra).

### normalized/lbma_proxy.csv (4,153 rows)
LBMA AM gold price proxy.

| series_id | Source | Quality |
|---|---|---|
| `GCF_DAILY_CLOSE_USD_OZ` | yfinance GC=F | proxy_futures_based |

**Không dùng LBMA AM/PM thật vì World Bank API bị lỗi 502.**

### normalized/news_sentiment.csv (3,138 rows)
Rule-based sentiment signals.

| Column | Mô tả |
|---|---|
| `date` | Signal date |
| `value` | Score [-5.0, +5.0]: +5 = extreme bullish, -5 = extreme bearish |
| `unit` | sentiment_bullish hoặc sentiment_bearish |
| `headline` | Mô tả signal (rule_signal: bullish/bearish + score) |
| `note` | Breakdown từng component: vix=, gold_mom_30d=, usd_vnd_chg_30d=, event_score= |

### normalized/sbv_deposit_rates.csv (43 rows)
SBV policy announcements — **KHÔNG phải time series**. Chỉ có event date + rate value từ policy announcements.

### normalized/vn_deposit_rates.csv
SBV TyGiaSo deposit rates — **0 non-null values**. Parser chưa parse được (values 20,000+ range, parser expects 0-100%).

---

## Master Panel (data/lake/enriched/master/) — Output cuối cùng

### normalized/gold_domestic_daily_panel.csv

| Column | Type | Mô tả |
|---|---|---|
| `date` | string | Ngày |
| `source` | string | sjc_official_history, webgia_sjc_archive, ... |
| `gold_type` | string | sjc_gold_bar, pnj_gold, gold_jewelry, ... |
| `buy_price` | float | Giá mua vào (VND/lượng) |
| `sell_price` | float | Giá bán ra (VND/lượng) |
| `spread` | float | sell - buy |
| `spread_pct` | float | spread / sell × 100 |
| `unit` | string | VND/luong |
| `business_date` | string | Ngày làm việc |
| `source_quality` | float | 0.50–1.00 (1.00 = rule_generated, 0.95 = sjc_official_history) |
| `row_type` | string | individual (từ 1 source) hoặc consensus (median across sources) |
| `data_lineage` | JSON | Traceability: qua bước nào sinh ra |

### normalized/global_reference_daily.csv

| Column | Type | Mô tả |
|---|---|---|
| `date` | string | Trading date |
| `usd_vnd_mid` | float | USD/VND mid rate |
| `usd_vnd_buy` / `usd_vnd_sell` | float | Vietcombank bid/ask |
| `vix` | float | VIX index |
| `dxy_index` | float | Broad dollar index |
| `treasury_10y_pct` | float | 10Y Treasury yield % |
| `wti_crude` | float | WTI crude USD/barrel |
| `sp500_index` | float | S&P 500 |
| `gold_futures_close_usd_oz` | float | GC=F daily close |
| `silver_futures_close_usd_oz` | float | SI=F daily close |
| `usd_vnd_market_rate` | float | USDVND=X yfinance |
| `us_10y_real_tips_yield` | float | DFII10 (real TIPS yield) |
| `us_10y_breakeven_inflation` | float | T10YIE |
| `st_louis_financial_stress` | float | STLFSI2 |
| `chicago_fed_nfci` | float | NFCI |
| `gld_close` | float | GLD ETF close |
| `sentiment_score` | float | Rule-based sentiment [-5, +5] |
| `lbma_am_usd_oz` | float | LBMA AM proxy (GC=F) |
| ... | | |

### normalized/vn_macro_asof_panel.csv (36K rows)

| Column | Type | Mô tả |
|---|---|---|
| `series_id` | string | Mã indicator (e.g., FP.CPI.TOTL.ZG) |
| `series_name` | string | Tên thân thiện: cpi_headline_yoy_pct |
| `date` | string | Observation date |
| `available_from` | string | **Ngày data có thể dùng — dùng field này để join, KHÔNG dùng date** |
| `release_date` | string | Ngày công bố chính thức |
| `frequency` | string | M / Q / A |
| `value` | float | Giá trị indicator |
| `unit` | string | Unit của value |
| `source` | string | world_bank / gso_macro_monitor / ... |
| `domain` | string | VN macro | Global macro |

**Cực kỳ quan trọng**: Khi join với gold_domestic_daily_panel, dùng `available_from <= gold_date`, KHÔNG dùng `observation_date <= gold_date`. Điều này tránh leakage — macro data chỉ available sau khi công bố.

### normalized/event_regime_panel.csv (1,850 events)

| Column | Type | Mô tả |
|---|---|---|
| `event_date` | string | Ngày xảy ra sự kiện |
| `event_type` | string | 13 loại (xem bên dưới) |
| `severity` | string | low / medium / high |
| `description` | string | Mô tả sự kiện |
| `expected_channel` | string | premium_spike / safe_haven_buy / ... |
| `days_until_next_tet` | int | Số ngày đến Tết (nếu là Tết proximity) |

**13 event types:**
tet_proximity, than_tai, wedding_season, policy_auction, policy_import_change, policy_inspection, policy_rate_change, geopolitical_crisis, financial_crisis, banking_stress, eurozone_crisis, financial_stress, calendar_rule

---

## Enriched Gold (data/lake/gold_prices/)

### normalized/gold_daily_enriched.csv (4,991 dates)

| Column | Type | Mô tả |
|---|---|---|
| `date` | string | Date |
| `sjc_buy` | float | Giá mua SJC |
| `sjc_sell` | float | Giá bán SJC |
| `consensus_mid` | float | Median buy+sell across sources |
| `global_gold_vnd_per_luong` | float | LBMA × USD/VND × conversion |
| `premium` | float | sell - global_gold_vnd_per_luong (VND/lượng) |
| `premium_pct` | float | premium / global × 100 |
| `spread_pct` | float | (sell - buy) / sell × 100 |

**Formula chuyển đổi (LUÔN dùng chung):**
```
CHI_PER_OZ = 31.1034768 / 1.205        # = 25.807 chi/oz
LUONG_PER_OZ = CHI_PER_OZ / 37.5        # = 0.6886 luong/oz

# LBMA USD/oz → VND/luong
global_gold_vnd_per_luong = lbma_usd_oz × usd_vnd_mid / LUONG_PER_OZ
// hoặc: lbma_usd_oz × usd_vnd_mid × (31.1035/1.205) / 37.5

// premium
premium = domestic_sell - global_gold_vnd_per_luong
premium_pct = premium / global_gold_vnd_per_luong × 100
```

---

## Data Flow Cheat Sheet

```
Domestic target (quotes.csv)
    ↓ gold_type normalization + business_date check
gold_domestic_daily_panel
    ↓ consensus median across sources
Raw gold (raw_gold_history.csv)
    ↓
    ↓ + FX rates (usd_vnd_mid) + LBMA proxy (lbma_am_usd_oz)
    ↓
gold_daily_enriched  ← premium decomposition ở đây
    ↓ join with
global_reference_daily  ← tất cả global features
    ↓ join with
vn_macro_asof_panel  ← macro theo available_from
    ↓ join with
event_regime_panel  ← Tết, Thần Tài, policy events
    ⬇
🚀 Sẵn sàng cho modeling: SARIMAX, VECM, XGBoost, TFT
```
