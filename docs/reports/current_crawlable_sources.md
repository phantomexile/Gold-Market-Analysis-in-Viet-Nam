# Current Crawlable Sources And Coverage

Run date: 2026-07-07

This report uses a stricter definition of "crawlable": the source must return real data over a meaningful historical range, not just a current snapshot or a one-day smoke test.

## Sources With Meaningful Coverage

| Dataset | Source | Coverage evidence | Code path | Decision |
|---|---|---|---|---|
| Domestic gold target | SJC official historical | Exact daily verified for 2010 and 2011: 365/365 dates each. Sampled 1st/15th/28th of each month from 2010-01-01 to 2026-07-06: 595/595 sampled dates matched `business_date == requested_date`. | `SjcOfficialCollector.get_history`, `backfill_target.py` | Primary historical label |
| Official FX | SBV central USD/VND | 3,940 daily records, 3,940 covered dates, `2011-07-06..2026-07-06`, 16 covered years. | `collect_sbv_central_fx_history` | Core FX historical feature |
| Global market | yfinance | 29,201 records, 4,303 covered dates, `2010-01-04..2026-07-07`, 17 covered years. Usable tickers: `GC=F`, `USDVND=X`, `^VIX`, `DX-Y.NYB`, `^GSPC`, `CL=F`, `SI=F`. | `collect_yfinance_prices` | Core daily market features |
| Global macro | FRED windowed CSV | 16,551 records, 4,201 covered dates, `2010-01-04..2026-07-03`, 17 covered years. Series: `DGS10`, `DCOILWTICO`, `VIXCLS`, `DTWEXBGS`. | `collect_fred_series` | Core daily macro/risk features |
| Vietnam macro baseline | World Bank API | 264 records, annual dates `1960..2025`, 66 covered years. | `collect_worldbank_macro` | Annual macro baseline |
| Vietnam macro detail | GSO macro-monitor | 30,840 records, 307 period dates, `1986-12-31..2025-04-01`, 40 covered years. | `collect_gso_macro_monitor_features` | Macro archive |
| Vietnam equity market | vnstock VNINDEX VCI | 4,309 records, 4,309 covered dates, `2009-03-31..2026-07-06`, 18 covered years. | `collect_optional_vnstock_features` | VNINDEX feature |

## Partial Or Limited Sources

| Source | Coverage evidence | Decision |
|---|---|---|
| Vietcombank date API | Sampled Jan/Jul dates show accepted historical rows only from `2020-07-15..2026-01-15`; old 2010-2019 sampled dates are empty or current-leak. | Use as recent commercial FX only; not a 2010-2019 historical source. |
| Vietcombank XML | Current snapshot rows only. | Current FX capture only. |
| WebGia SJC archive | Historical rows exist on sampled dates, but coverage is not complete across holidays/non-trading dates. | Cross-check only, not primary label. |
| Giavang SJC archive | Historical rows exist on sampled dates, but coverage is partial. | Cross-check only, not primary label. |
| PNJ / DOJI current | Current data available, but old-date requests leak current data. | Current monitoring only. |

## Rejected Or Not Production-Ready

| Source | Reason |
|---|---|
| `XAUUSD=X` via yfinance | Empty/not found in this environment. Use `GC=F` as global gold proxy. |
| Stooq XAU/USD | Blocked by anti-bot/session behavior in this environment. |
| VCB date API for 2010-2019 | Does not provide accepted historical rows in sampled audit. |
| BTMC by-day | Not verified with `requested_date == business_date`. |
| Phu Quy / VietABank / BTMC / GoldVN current | Parser not implemented; current-only candidates. |
| GDELT / pytrends / Event Registry | Phase 2; not core historical coverage yet. |

## Practical Interpretation

For model-ready historical coverage from 2010 onward, the solid backbone is:

```text
SJC official target
+ SBV central FX
+ yfinance daily market
+ FRED daily macro/risk
+ World Bank annual macro
+ GSO Vietnam macro archive
+ vnstock VNINDEX VCI
```

VCB should not be described as "full historical FX" for this project. It is useful for current and recent commercial FX, while SBV is the reliable long historical FX source.
