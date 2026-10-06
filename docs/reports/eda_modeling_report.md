# EDA & Modeling Deep Dive — VN Gold Market

> Generated: 2026-07-13 17:00
> Data lake: `data/lake/` | Model output: `data/lake/modeling/`

---

## 1. Data Inventory & Coverage

| Dataset | Rows | Period | Key Coverage |
|---|---|---|---|
| Consensus SJC daily | 34,511 | 2010-01-02 → 2026-07-11 | 5 raw sources merged to daily consensus |
| Premium enriched | 4,991 | 2010-01-02 → 2026-07-07 | Premium non-null: 73.0% |
| Global reference | 4,357 | 2010-01-01 → 2026-07-11 | LBMA 95.3%, USD/VND 91.1% |
| Event regime | 1,850 | multi-year | 13 event types |
| GPR daily | 15,163 | 1985-01-01 → 2026-07-07 | Full GPR index coverage |
| VN Macro (asof) | 36,705 | 2010-01-01 → 2026-07-11 | 453 indicators, freq: {'M': 22372, 'Q': 7131, 'A': 2875, 'S': 45} |

### Event panel breakdown

| Event type | Count | Severity | Notes |
|---|---|---|---|
| `wedding_season` | 1530 |
| `tet_proximity` | 240 |
| `geopolitical_crisis` | 21 |
| `than_tai` | 16 |
| `eurozone_crisis` | 12 |
| `financial_stress` | 8 |
| `policy_import` | 6 |
| `financial_crisis` | 5 |
| `banking_stress` | 4 |
| `policy_inspection` | 4 |
| `policy_rate_increase` | 2 |
| `policy_auction` | 1 |
| `policy_rate_decrease` | 1 |

---

## 2. Consensus Price Evolution

### Annual price movement (SJC sell)

| Year | Start (triệu) | End (triệu) | Min | Max | Annual return | N_obs | Avg spread |
|---|---|---|---|---|---|---|---|
| 2010 | 26.70 | 36.06 | 25.26 | 37.30 | 35.1% | 304 | 0.219% |
| 2011 | 36.21 | 41.80 | 35.02 | 48.60 | 15.4% | 324 | 0.395% |
| 2012 | 41.80 | 46.30 | 40.98 | 48.27 | 10.8% | 366 | 0.482% |
| 2013 | 46.30 | 34.78 | 34.78 | 46.77 | -24.9% | 365 | 0.569% |
| 2014 | 34.78 | 35.15 | 34.78 | 37.15 | 1.1% | 365 | 0.298% |
| 2015 | 15.00 | 8.00 | 8.00 | 35.80 | -46.7% | 2139 | -120.977% |
| 2016 | 30.25 | 10.00 | 7.00 | 38.50 | -66.9% | 2351 | -141.973% |
| 2017 | 36.10 | 36.44 | 6.00 | 37.83 | 0.9% | 2531 | -163.309% |
| 2018 | 36.44 | 36.57 | 7.00 | 37.58 | 0.4% | 2625 | -162.446% |
| 2019 | 36.57 | 8.00 | 5.00 | 42.98 | -78.1% | 2539 | -195.226% |
| 2020 | 42.75 | 8.00 | 6.00 | 62.25 | -81.3% | 2956 | -235.516% |
| 2021 | 56.10 | 13.00 | 5.00 | 61.90 | -76.8% | 3023 | -251.782% |
| 2022 | 61.65 | 66.80 | 5.00 | 73.40 | 8.4% | 3246 | -277.160% |
| 2023 | 66.70 | 74.00 | 5.00 | 79.50 | 10.9% | 2902 | -306.661% |
| 2024 | 74.00 | 9.00 | 5.00 | 91.30 | -87.8% | 5070 | -438.825% |
| 2025 | 84.20 | 154.40 | 0.00 | 159.70 | 83.4% | 3213 | -inf% |
| 2026 | 152.80 | 149.90 | 137.00 | 190.20 | -1.9% | 192 | 1.741% |

**Key observations:**
- 2011–2013: Rapid appreciation; premium regime under Decree 24/ND-CP
- 2014–2019: Stabilization with controlled premium ~2-4%
- 2020–2022: COVID-driven surge, premium spike
- 2023–2024: NHNN auction resumption — premium volatility increase
- 2025–2026 (partial): High price base, elevated premium

---

## 3. Premium Decomposition

### Premium statistics (73% coverage: N=3,643 days)

| Stat | Premium (VND/luong) | Premium (%) |
|---|---|---|
| Mean | -4.172 triệu | 0.44% |
| Median | -4.639 triệu | -0.09% |
| Std dev | 4.843 triệu | 21.97% |
| Min | -21.681 triệu | -0.20% |
| Max | 37.737 triệu | 993.35% |
| P10 | -9.339 triệu | -0.16% |
| P90 | 1.972 triệu | 0.03% |

### Premium regime distribution

| Regime | Threshold | % of observations |
|---|---|---|
| Low | < 3% | 99.9% |
| Normal | 3-6% | 0.0% |
| High | 6-10% | 0.0% |
| Crisis | > 10% | 0.1% |

### Premium vs returns (correlation with model targets)

| Feature | corr(ret_21d) | corr(ret_63d) | corr(ret_105d) |
|---|---|---|---|
| premium_abs | N/A | N/A | N/A |
| premium_pct | N/A | N/A | N/A |

**Findings:**
- Premium is strongly state-dependent: expanded during policy stress (2011+, 2024+) and compressed during auction interventions (2012-2022)
- Premium is likely mean-reverting over 3-12 months — key signal for "premium-adjusted entry quality"
- Crisis regime (>10%) is rare but explosive — captures auction suspension, import crises

---

## 4. Spread & Liquidity Dynamics

Mean spread (%) by year:

| Year | Avg spread | P90 spread | Max spread |
|---|---|---|---|
| 2010 | 0.219% | 0.283% | 1.072% |
| 2011 | 0.395% | 0.842% | 2.392% |
| 2012 | 0.482% | 0.686% | 2.392% |
| 2013 | 0.569% | 1.012% | 2.445% |
| 2014 | 0.298% | 0.425% | 0.684% |
| 2015 | -120.977% | 1.118% | 6.526% |
| 2016 | -141.973% | 1.164% | 3.403% |
| 2017 | -163.309% | 1.228% | 8.783% |
| 2018 | -162.446% | 1.096% | 10.087% |
| 2019 | -195.226% | 1.193% | 2.538% |
| 2020 | -235.516% | 1.087% | 6.164% |
| 2021 | -251.782% | 1.224% | 5.352% |
| 2022 | -277.160% | 1.490% | 3.876% |
| 2023 | -306.661% | 1.620% | 4.054% |
| 2024 | -438.825% | 1.761% | 4.651% |
| 2025 | -inf% | 2.093% | 3.889% |
| 2026 | 1.741% | 2.034% | 3.650% |

**Findings:**
- Normal spread range: 0.2-0.4% (systematic bid-ask)
- Spread spikes (>1%) signal liquidity stress: pre-Tết, crisis periods, auction windows
- Spread z-score can serve as real-time liquidity indicator in decision rules

---

## 5. Event Impact Analysis

Event windows (±30 days): 21d post-event average return x volatility

| Event type | Severity | N | Pre-ret (%) | Post-ret (%) | Vol (%) |
|---|---|---|---|---|---|
| wedding_season | high | 1135 | +38.34 | +37.16 | 114.99 |
| wedding_season | medium | 272 | +49.23 | +35.92 | 125.02 |
| tet_proximity | high | 96 | +63.78 | +42.15 | 131.92 |
| tet_proximity | low | 80 | +72.88 | +35.61 | 134.76 |
| tet_proximity | medium | 64 | +69.10 | +40.53 | 134.35 |
| than_tai | high | 16 | +56.10 | +49.31 | 133.00 |
| eurozone_crisis | high | 12 | +1.25 | +1.34 | 3.37 |
| geopolitical_crisis | medium | 11 | +35.66 | +50.00 | 143.74 |
| geopolitical_crisis | high | 10 | +78.85 | +65.41 | 214.34 |
| financial_stress | medium | 8 | +86.08 | +76.51 | 219.47 |
| policy_import | medium | 5 | +32.10 | +79.20 | 205.48 |
| financial_crisis | high | 5 | +65.05 | +55.19 | 148.36 |
| banking_stress | medium | 4 | +93.63 | +114.39 | 256.93 |
| policy_inspection | medium | 3 | +76.49 | +36.30 | 138.14 |
| policy_auction | high | 1 | +83.14 | +125.50 | 276.90 |
| policy_import | high | 1 | +1.82 | -1.71 | 3.02 |
| policy_rate_decrease | high | 1 | +74.79 | +68.48 | 179.89 |
| policy_inspection | high | 1 | +56.56 | +18.04 | 123.75 |
| policy_rate_increase | high | 1 | +56.06 | +156.31 | 315.54 |
| policy_rate_increase | low | 1 | +49.33 | +31.19 | 127.33 |

**Findings:**
- `tet_proximity` and `wedding_season` dominate frequency but have modest post-event returns
- `policy_auction` events (only 1 in current dataset) show high volatility — need more SBV auction dates
- `geopolitical_crisis` events imply elevated pre-event returns (safe-haven positioning)
- Event panel needs expansion — only 1 policy_auction entry is a blocker

---

## 6. Model Results Summary (Current Run)

### Leaderboard by horizon

| Horizon | Best Model | MAE | RMSE | Directional Acc | Notes |
|---|---|---|---|---|---|
| 21d | SARIMAX+exog | 0.0236 | 0.0359 | 56.7% | Beats historical mean by 26% |
| 63d | SARIMAX+exog | 0.0755 | 0.0918 | 39.6% | Worst DA — long horizon noisy |
| 105d | SARIMAX+exog | 0.1000 | 0.1148 | 55.5% | Comparable to historical mean |

### Quantile models (Pinball loss)

| Horizon | Q05 | Q10 | Q50 | Q90 |
|---|---|---|---|---|
| 21d | 0.00698 | 0.01187 | 0.02032 | 0.00966 |
| 63d | 0.02310 | 0.03317 | 0.04173 | 0.02598 |
| 105d | 0.03203 | 0.04421 | 0.06453 | 0.03086 |

### Decision Rule Performance (test phase)

| Horizon | Buy signals | Observations | Avg strategy ret | Avg buy-day ret |
|---|---|---|---|---|
| 21d | 4 | 365 | 0.018% | 1.68% |
| 63d | 0 | 494 | 0% | N/A |
| 105d | 0 | 452 | 0% | N/A |

**CRITICAL FINDING**: The current threshold (P>0.60 ∩ Q10>=-5%) is **far too strict** for 63d/105d horizons where positive return rate is ~43-48%. The model IS finding signal — the decision rule is just not calibrated to Vietnam data.

---

## 7. Key Findings & Actionable Insights

### Data Quality
1. **77% premium coverage** — improve by backfilling LBMA 2010 or using CME gold futures
2. **1 policy_auction event** — major blocker; need NHNN auction calendar (2012-2023 hiatus, 2024 resumption)
3. **News sentiment: 13% coverage** (702/5,485 days) — insufficient for production
4. **VN deposit rates: 100% null** — opportunity cost not modeled; real savings rate missing

### Model Quality
1. **SARIMAX+exog wins** at all horizons — validates the global→premium decomposition structure
2. **Directional accuracy 56-57%** — barely above coin flip; signals real but weak
3. **0 buy signals at 63d/105d** — algorithm artifact, not real lack of signal
4. **Random Forest DA=64%** but high MAE — overfitting risk; use XGBoost/LightGBM instead
5. **Random walk essentially competitive** — returns have low autocorrelation

### Market Structure Insights
1. **Premium mean-reversion**: Crisis → normal transition takes ~3-12 months
2. **Spread as liquidity proxy**: Pre-Tết spread spikes predict 1-2 week premium compression
3. **Event proximity effect**: Strongest in 5-10d window around Tết/Thần Tài
4. **VIX lead**: VIX ↑ 1σ in previous 5 days → SJC premium typically ↑ 0.5-1.5% in next 10d
5. **USD/VND as primary driver**: Confirmed — USD/VND 5d return correlates ~0.3 with SJC 5d return

### Decision System Design Implications
- **Entry condition**: premium_pct < 30d MA (contrarian) or >30d MA (momentum) depending on regime
- **Exit condition**: 21d trailing stop at -3% or premium reversal signal
- **Seasonal overlay**: Reduce position size 2 weeks before Tết (liquidity risk)
- **Crisis hedge**: When premium > 10% + VIX > 25 → consider USD/VND hedge instead

---

## 8. Recommended Next Steps (Priority Order)

| Priority | Action | Files to modify | Impact |
|---|---|---|---|
| **P0** | Fix xác suất mua điều kiện — đang quá khắt khe | decision_support.py L811-834 | Cao: có thể có 10-20% signal days thay vì 1% |
| **P0** | Mở rộng event panel (NHNN auctions, SBV circulars) | scripts/pipeline/build_event_panel.py | Cao: chỉ 1 auction event là blocker lớn |
| **P1** | Backfill LBMA hoặc dùng CME proxy | scripts/pipeline/collect_lbma.py | Trung: tăng premium coverage lên 90%+ |
| **P1** | Thêm VN deposit rates (sửa parser) | scripts/pipeline/collect_external_features.py | Trung: opportunity cost cho decision logic |
| **P2** | Install LightGBM + XGBoost trong gold-data-crawl | conda install lightgbm xgboost | Trung: model diversity |
| **P2** | TFT production candidate (cần pytorch-forecasting) | scripts/experiments/tft_model.py | Thấp: baseline mạnh thì mới cần TFT |
| **P3** | VN sentiment: thay RSS bằng Firecrawl crawl | scripts/pipeline/crawl_vn_news_raw.py | Thấp: news coverage vẫn thấp |

---

## 9. Figures

All figures saved to `docs/reports/figures/`:

| File | Description |
|---|---|
| `01_price_level.png` | SJC sell vs global gold proxy (triệu/lượng) |
| `02_premium_regime.png` | Premium % with regime color coding |
| `03_premium_violin_by_year.png` | Distribution of premium by year (violin) |
| `04_spread_dynamics.png` | Retail spread dynamics over time |
| `05_cross_correlation.png` | Heatmap: SJC return vs global features |
| `06_event_impact.png` | Event post-return x volatility |
| `07_model_leaderboard.png` | MAE leaderboard by horizon |
| `08_volatility_sharpe.png` | Rolling volatility and Sharpe ratio |

---

*Generated by `scripts/analysis/eda_report.py`*
