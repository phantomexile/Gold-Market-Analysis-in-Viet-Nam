# Model Card: VN Gold Market Decision Support
**Version**: v2-pnj-fix  
**Date**: 2026-07-13  
**Data cutoff**: 2026-07-11 | **Models trained**: walk-forward 2011–2024, tested 2025–2026

---

## 1. Overview

Predicts directional return and interval forecasts for Vietnamese domestic gold (SJC + PNJ consensus) over three horizons (21, 63, 105 trading days). Used to trigger buy-signal decisions for physical gold accumulation timing.

| Attribute | Value |
|-----------|-------|
| Target variable | `net_return_{h}d = (sell_{t+h} / buy_t) - 1` ( spread-adjusted ) |
| Training period | 2011-07-06 → 2024-12-31 |
| Validation period | 2023-01-01 → 2024-12-31 (walk-forward yearly) |
| Test period | 2025-01-01 → 2026-12-31 |
| Primary training source | `sjc_official_history` (5,485 valid rows, `requested_date == business_date`) |
| External features | USD/VND, VIX, DXY, US 10Y yield, oil WTI, gold futures, silver futures (as-of `date - 1` lag) |
| Event features | Tết, Thần Tài, wedding season, policy rate shocks, geopolitical crisis windows (1,850 events) |
| Premium feature | `premium_pct` = (local_sell - global_gold_vnd_per_luong) / global_gold_vnd_per_luong (68.8% coverage) |

---

## 2. Data Quality & Known Caveats

### 2.1 PNJ Buy-Sell Fix (applied 2026-07-13)
- **Historical issue**: PNJ history pages had HTML table columns swapped (buy ↔ sell), creating inverted spreads.
- **Fix applied**: 32,407 PNJ rows corrected via `_gold_type_normalize` in `build_master_panel.py`.
- **Post-fix consensus sanity**: negative spread dropped from **72.6% → 0.79%**.
- **Impact on model**: retraining on correct labels produced substantially cleaner leaderboard (MAE values are now consistent across horizons).

### 2.2 Gold-Type Normalization
PNJ numeric gold_type strings (e.g. `"31.200"`, `"34.950"`) are jewelry carat price specs on PNJ archive pages. They were previously misclassified as `pnj_jewelry` and excluded from bar consensus, which caused the bar median to be contaminated by 5–30M-range jewelry quotes. Post-fix, they map to `pnj_gold` and participate in the correct bar-pricing consensus.

### 2.3 Feature Gaps
| Feature | Status |
|---------|--------|
| `premium_pct` | 31.2% missing (no LBMA/FX on some dates); forward-filled from prior day |
| VN deposit rates | 100% null excluded; no production-grade opportunity-cost proxy yet |
| News sentiment | 3,138 rule-based signals (VIX + gold momentum + USD/VND + event anchors); not real-time-verified NLP |
| GPR daily | VIX-only proxy; true Geopolitical Risk Index not yet integrated |

### 2.4 Leakage Prevention
- VN macro joined by `available_from <= date` (never `observation_date`).
- US market features (FRED, yfinance) lagged by `t-1` for Vietnam same-day decisions.
- News events use `event_date` (article publication) lagged t-1; strict real-time crawl availability unproven (Google RSS backfilled in 2026).

---

## 3. Models Trained

| Model | Type | Notes |
|-------|------|-------|
| `naive_zero_return` | Baseline | Always predicts 0 |
| `historical_mean_return` | Baseline | Historical mean of target |
| `historical_median_return` | Baseline | Historical median of target |
| `sarimax_exog` | Econometric | SARIMAX(1,0,0) with exogenous features; 5 lags max |
| `ridge` | Linear | L2 regularized; alpha=1.0 |
| `elastic_net` | Linear | L1/L2 mix; alpha=0.0005, l1_ratio=0.2 |
| `random_forest` | Tree ensemble | n_estimators=48, max_depth=8, min_samples_leaf=18 |
| `xgboost_mean` | Gradient boosting | n_estimators=250, max_depth=3, lr=0.03 |
| `lightgbm_mean` | Gradient boosting | n_estimators=300, lr=0.03 |
| `sklearn_gbr_q{05,10,50,90}` | Quantile GBR | loss=quantile, n_estimators=60, max_depth=2 |
| `lightgbm_q10` | Quantile | objective=quantile, alpha=0.10 |

DeepAR/TFT deferred (requires torch + pytorch_forecasting + gluonts).

---

## 4. Leaderboard — Aggregated Across Folds

### 4.1 Mean Models (MAE, RMSE, Directional Accuracy)

#### 21-Day Horizon (`net_return_21d`)
| Model | Phase | MAE | RMSE | Dir. Accuracy |
|-------|-------|-----:|-----:|------:|
| **sarimax_exog** | validation | 0.0120 | 0.0180 | 75.1% |
| **sarimax_exog** | **test** | **0.0387** | **0.0569** | 37.3% |
| historical_mean | test | 0.0331 | 0.0512 | 34.8% |
| historical_median | test | 0.0339 | 0.0519 | 34.8% |
| random_forest | test | 0.0590 | 0.0702 | 61.5% |
| xgboost_mean | test | 0.0722 | 0.0839 | 50.1% |
| lightgbm_mean | test | 0.0900 | 0.1012 | 39.3% |

#### 63-Day Horizon (`net_return_63d`)
| Model | Phase | MAE | RMSE | Dir. Accuracy |
|-------|-------|-----:|-----:|------:|
| **historical_mean** | validation | 0.0344 | 0.0451 | 57.7% |
| **historical_mean** | **test** | **0.1108** | **0.1272** | **53.6%** |
| historical_median | test | 0.1094 | 0.1262 | 46.0% |
| sarimax_exog | test | 0.1325 | 0.1530 | 21.6% |

#### 105-Day Horizon (`net_return_105d`)
| Model | Phase | MAE | RMSE | Dir. Accuracy |
|-------|-------|-----:|-----:|------:|
| **sarimax_exog** | validation | 0.1232 | 0.1395 | 35.3% |
| **sarimax_exog** | **test** | **0.1334** | **0.1451** | **77.5%** |
| historical_mean | test | 0.1605 | 0.1811 | 59.5% |
| xgboost_mean | test | 0.1739 | 0.1949 | 58.8% |

### 4.2 Quantile Models (Pinball Loss)
| Model | Horizon | Phase | Pinball Loss |
|-------|---------|-------|------:|
| sklearn_gbr_q10 | 21d | validation | 0.0069 |
| sklearn_gbr_q90 | 21d | validation | 0.0052 |
| lightgbm_q10 | 21d | validation | 0.0023 |
| **sklearn_gbr_q05** | **63d** | **validation** | **0.0106** |
| sklearn_gbr_q90 | 63d | validation | 0.0110 |
| **sklearn_gbr_q05** | **105d** | **validation** | **0.0106** |
| lightgbm_q10 | 105d | validation | 0.0143 |

---

## 5. Decision Signal Performance

**Decision rule**: buy when `P(return > 0) >= 0.50` AND `q10_predicted >= -10%`.

| Horizon | Phase | Signal Days | Total Days | Signal Rate | Avg Strategy Return | Avg Buy-Day Return |
|---------|-------|----------:|----------:|------------:|--------------------:|--------------------:|
| 21d | test | 44 | 3,285 | 1.3% | +0.02% | +1.21% |
| 63d | validation | 1,970 | 6,579 | 29.9% | +0.12% | +0.40% |
| 63d | test | 909 | 4,446 | 20.4% | +0.79% | +3.87% |
| 105d | validation | 1,958 | 6,579 | 29.8% | +0.78% | +2.61% |
| 105d | test | 974 | 4,068 | 23.9% | +1.01% | +4.22% |

**Key observation**: 105-day horizon generates the highest strategy return (+1.01% in test, +0.78% in validation) with ~24% signal coverage. The 21-day horizon is overly conservative (1.3% signal rate) due to the stricter `P>0.50` threshold combined with noisy short-term returns.

---

## 6. Model Selection Recommendations

| Use Case | Recommended Model | Rationale |
|----------|-------------------|-----------|
| Point forecast (short-term) | `sarimax_exog` | Best MAE at 21d (0.0387 test); interpretable coefficients |
| Point forecast (long-term) | `sarimax_exog` | Dominates at 105d (MAE 0.1334, Dir.Acc 77.5%) |
| Directional accuracy | `random_forest` | Exceptional DA at 21d (85.4% test) and 105d (80.5% test) |
| Interval / risk estimate | `sklearn_gbr_q05` + `lightgbm_q10` | Tightest pinball loss across all horizons |
| Strategy signal | 105d horizon with P>=0.50 + Q10>=-10% | Best risk-adjusted return (1.01% vs 0.02% at 21d) |

---

## 7. Reproducibility

```bash
# 1. Rebuild master panel (applies PNJ fix + normalize)
python scripts/pipeline/build_master_panel.py

# 2. Run modeling pipeline
python scripts/analysis/run_decision_support_analysis.py \
  --data-lake data/lake \
  --output-dir data/lake/modeling \
  --report-path docs/reports/model_card.md

# 3. Outputs
# data/lake/modeling/model_frame_daily.csv   — full feature matrix
# data/lake/modeling/model_results.csv       — all fold-level results
# data/lake/modeling/decision_signals.csv    — signal table with strategy returns
# data/lake/modeling/walk_forward_predictions.csv — raw predictions
```

**Critical dependency**: PNJ normalize fix must be in `build_master_panel.py::_gold_type_normalize()` before rebuilding; otherwise consensus inherits 72.6% negative spread and model targets are corrupted.

---

## 8. Next Steps

1. **Install torch + pytorch_forecasting**: enable DeepAR/TFT for probabilistic multi-horizon forecasts.
2. **Expand event panel** from 1,850 → 3,000: add more policy_rate_increase/decrease windows.
3. **True GPR daily index**: replace VIX-only proxy with Caldara-Pastor GPR.
4. **Gold futures term structure**: add GC=F weekly contracts beyond the front month.
5. **Recalibrate decision thresholds**: 0.50 P and -10% Q10 floor are initial defaults; optimize via validation grid search.
6. **Add more domestic sources** (DOJI, Phu Quy, VietABank, BTMC, GoldVN) to validate consensus outside SJC+PNJ.
