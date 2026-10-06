# Literature Review — Gold Price Forecasting for the Vietnamese Market

> **Scope**: 7 methodological areas, 40+ sources synthesized July 2026
> **Status**: Raw claims extracted and cross-referenced; verification pending due to Semantic Scholar rate limit. Core citations from primary venues (IJF, JORS, NeurIPS, arXiv, Elsevier).

---

## 1. Classical Time Series Models for Gold Price

### 1.1 ARIMA / SARIMAX

| Citation | What It Solves | Key Assumptions | Pros | Cons — Vietnam Context |
|---|---|---|---|---|
| Box & Jenkins (1976) — foundational | Univariate linear forecasting with differencing | Stationarity after differencing; linear autocorrelation structure | Interpretable, widely available (statsmodels), fast | Fails on gold's non-linear premium dynamics; severe degradation on long horizons (>20 steps) |
| Makala et al. (2023), *Future Internet* — survey | Systematic comparison on gold price series | Linear time series structure adequate for gold prices | Baseline benchmark against ML | **Catastrophic failure documented**: RMSE=36.18, MAPE=2897 on gold vs. SVM's RMSE=0.028 — univariate ARIMA cannot capture gold's non-linear dynamics |
| Reboredo (2013) — *Resources Policy* | Gold price modeling under regime change | Gold price follows ARMA dynamics | Simple to implement | Regime shifts in Vietnam (auction resumption, policy changes) break ARIMA assumptions |

**Key finding**: Hybrid ARIMA-ML models consistently outperform pure ARIMA on gold price across all surveyed application domains. ARIMA captures linear structure; ML (XGBoost/LightGBM) captures non-linear residuals. This is the most evidence-backed architecture for datasets ≤ 100K rows.

### 1.2 VECM (Vector Error Correction Model)

| Citation | What It Solves | Key Assumptions | Pros | Cons — Vietnam Context |
|---|---|---|---|---|
| Johansen (1995) — foundational | Cointegrated multivariate series | Series share a long-run equilibrium relationship | Gold price, USD/VND, and international gold likely cointegrated in Vietnam | Requires Johansen test confirmation; sensitive to series selection |
| Lin (2013) — *Applied Economics* | Gold price determinants | Cointegration between spot and futures gold | Decomposes short-run dynamics from long-run trend | Needs sufficient sample per cointegrating relationship |

**Key finding**: VECM is appropriate for Vietnam **if** `sjc_mid`, `global_gold_vnd_per_luong`, and `usd_vnd` pass Johansen cointegration test. This is a hypothesis that must be tested first.

### 1.3 GARCH-family (volatility modeling)

| Citation | What It Solves | Key Assumptions | Pros | Cons |
|---|---|---|---|---|
| Baur & McDermott (2010) — *JIMF* | Gold as safe-haven across countries | Conditional heteroscedasticity in gold returns | Captures volatility clustering common in gold | EGARCH/GJR-GARCH variants needed for leverage effects |

---

## 2. Premium Decomposition Methodology

### 2.1 Domestic Premium Over International Gold

| Citation | What It Solves | Methodology | Key Finding | Vietnam Relevance |
|---|---|---|---|---|
| **OSF preprint (doi:10.31219/osf.io/85dqp)** — VN-specific empirical study | Parsimonious model of VN gold price | Stepwise regression, 54 monthly obs 2009M01–2013M06 | **USD/VND is dominant driver**: `VNGOLD = -79225.95 + 5.890462 × USD/VND`, R²=0.920. CPI dropped (r=0.954 with USD/VND). Decree 24/ND-CP (2012-05-25) created **structural break**: gold stopped tracking SBV nominal rate | Direct empirical evidence for Vietnam; confirms USD/VND as primary channel |
| JEFAS paper (doi:10.1108/jefas-03-2017-0052) | Gold price forecasting in frontier/emerging markets | ARDL bounds testing, VECM | ARDL superior to VECM when sample size limited | ARDL approach viable for VN given cointegration uncertainty |
| Physica A (doi:10.1016/j.physa.2015.07.011) | Information flow between international/local gold markets | Granger causality, wavelet coherence | Local premium contains independent information beyond international price | Premium in Vietnam has its own dynamics not explained by LBMA alone |
| Energy Economics (doi:10.1016/j.eneco.2014.04.021) | Cross-border gold price arbitrage | Threshold model, transaction cost | Arbitrage band explains premium in developing markets | SJC premium has administrative floor/ceiling, not just transaction cost |

### 2.2 Premium Mean-Reversion & Regime Identification

**Core hypothesis**: Vietnam domestic gold premium is **mean-reverting in the long run** but can exhibit extended regime-dependent deviations due to policy interventions.

- **Mean-reversion support**: IMF working papers and Vietnam-specific studies suggest premium converges over 3-12 months in normal conditions
- **Regime break triggers**: NHNN auction resumption (Q4 2024), Decree 24/ND-CP (2012), import restriction changes
- **Regime classification proposed**:
  - `low_premium_mode`: <3% (normal market, ample liquidity)
  - `normal`: 3-6% (typical range)
  - `high`: 6-10% (supply stress, demand surge)
  - `crisis`: >10% (e.g., early 2024 peak ~1000 USD/tael premium)

---

## 3. Machine Learning Approaches

### 3.1 Survey & Methodology Comparison

| Citation | Scope | Key Finding | Vietnam Implication |
|---|---|---|---|
| **Makala et al. (2023)** — *Future Internet* (doi:10.3390/fi15080255) | Systematic review of ML for gold price forecasting (2014-2023) | Hybrid ARIMA-ML consistently best; SVM/XGBoost > LSTM for tabular; ensemble > single model | Directly applicable — recommends XGBoost/LightGBM on lagged features |
| Makridakis et al. (2022) — *JORS* (doi:10.1080/01605682.2022.2118629) | M4 competition analysis | **Simple statistical methods (ETS, Theta, naive) outperform ML/DL** on homogeneous-frequency subsets. ML fails due to inability to extrapolate beyond training range — structural limitation, not data volume | Critical for Vietnam: returns-based prediction should be preferred over price-level prediction |
| LSTM benchmark (doi:10.1007/s10479-022-05076-6) | LSTM vs ARFIMA/ANN/GRU on 6 Bloomberg commodity subindices | LSTM achieves highest R² across all commodities | LSTM viable as secondary model; but needs >5 years data to generalize |

### 3.2 Feature Engineering Best Practices

From the survey corpus:
- **Rolling statistics**: 20d/60d mean_abs_deviation, z-scores of returns — most predictive non-linear features
- **Calendar features**: month sin/cos, weekday, days_to_tet, days_to_than_tai — capture Vietnamese seasonality ignored in global models
- **Event dummies**: rolling 30d count of policy events, auction dummies — regime shift indicators
- **Cross-source consensus features**: number of active sources, source dispersion, primary_source reliability — leverage the 4-source structure of our data
- **Premium propagation**: lagged premium, premium momentum, premium z-score relative to 365d rolling window

### 3.3 XGBoost / LightGBM

- Winning approach for tabular financial data with ≤ 100K rows
- Handles mixed feature types (continuous + categorical + binary)
- Built-in regularization prevents overfitting — critical for limited financial data
- Feature importance output provides model interpretability

---

## 4. Deep Learning for Multi-Horizon Forecasting

### 4.1 TFT (Temporal Fusion Transformer)

| Citation | Dataset | P50 Loss | P90 Loss | vs. Seq2Seq | vs. ARIMA |
|---|---|---|---|---|---|
| Lim et al. (2021) — *IJF* (doi:10.1016/j.ijforecast.2021.03.012) | Electricity (370 entities) | 0.055 | 0.027 | +22% better | +180% better |
| Same | Traffic, Volatility, Retail | Best on all 4 | — | 7% lower P50, 9% lower P90 on avg | — |

**Architecture** (original paper arXiv:1912.09363):
- Gating layers suppress unnecessary components across regimes
- Recurrent layer for local temporal processing
- Interpretable self-attention for long-term dependencies
- Variable selection networks handle static + time-varying covariates
- Quantile output heads → direct probabilistic forecasts

**Vietnam suitability**: High — handles event dummies, calendar features, and mixed-variate panel. But needs >50K rows to justify DL over tabular ML.

### 4.2 DeepAR (Salinas et al., 2020)

| Metric | Finding |
|---|---|
| Accuracy improvement | ~15% over classical baselines |
| Key advantage | Joint training across related series (multiple sources, product types) |
| Probabilistic output | Direct likelihood-based prediction intervals |
| Limitation | LSTM-based; sensitive to hyperparameters; slower than TFT |

**Vietnam suitability**: Medium — our data is single-series (SJC sell price) mainly; multi-series benefit limited unless we model multiple sources/products jointly.

### 4.3 N-BEATS (Oreshkin et al., 2020, NeurIPS)

| Metric | Finding |
|---|---|
| Improvement | 11% over M3/M4/TOURISM statistical benchmarks; 3% over M4 winner |
| Architecture | Pure deep learning, stack of MLPs with backcast/forecast |
| **Limitation** | Univariate only; **no probabilistic output** |

**Vietnam suitability**: Low for production (no prediction intervals), useful as ensembler in benchmark suite only.

### 4.4 N-HiTS (Challu et al., 2023)

| Metric | Finding |
|---|---|
| Improvement | ~20% over Transformer-based baselines on long-horizon tasks |
| Architecture | Hierarchical interpolation + N-BEATS backbone |

**Vietnam suitability**: Medium — designed for long-horizon (same as our 1m/3m/5m task), but same univariate limitation.

**Critical cross-finding** (Makridakis et al. 2022): Deep learning methods fail to outperform naive benchmarks on **high-frequency financial/economic series with limited history**. Root cause: inability to extrapolate beyond training range — structural, not a data problem. **Our multi-year daily series (2010-2026, ~4000 rows) should be sufficient if we predict returns rather than prices.**

---

## 5. Crisis Regimes, Safe-Haven, and Gold in Emerging Markets

### 5.1 Gold as Safe-Haven

| Citation | Finding | Vietnam Implication |
|---|---|---|
| Baur & McDermott (2010) — *JIMF* | Gold is hedge/safe-haven for major economies; strongest during equity market stress | Vietnam EM status amplifies safe-haven demand during global crises |
| Beckmann et al. (2015) — *IJFE* | Uncertainty (policy, economic) drives gold price; strongest at high uncertainty quantiles | VIX is high-value feature; premium amplifies during uncertainty spikes |
| Baur & Lucey (2010) — early safe-haven characterization | Gold safe-haven properties vary by regime | Regime-switching model warranted for Vietnam premium |
| **EM Equity & Gold/USD copula study** (doi:10.1016/j.ememar.2017.12.006) | **USD hedges downside tail risk more effectively than gold** for EM equity portfolios | In Vietnam, USD/VND movements may be a stronger crisis predictor than gold price alone |

### 5.2 Vietnam Market-Specific Dynamics

| Citation | Key Finding |
|---|---|
| **OSF preprint (doi:10.31219/osf.io/85dqp)** | USD/VND explains 92% of VN gold price variation; Decree 24/ND-CP (2012) created structural regime break; NHNN auction became primary price-stabilization mechanism post-2012 |
| Reuters (2024) — cited in deep-research-report | Premium peaked at ~1000 USD/tael in 2024; NHNN resumed auctions after 10+ year hiatus |
| Reuters + industry sources (2024) | Retail gold demand surged 2024 due to: falling deposit rates, real estate freeze, VND depreciation vs USD → "queue to buy gold" phenomenon |
| SBV regulatory framework | State monopoly on gold bar production/import; NHNN manages wholesale auctions; commercial gold trading licensed but supply-constrained |

**Implication for modeling**: Vietnam gold model is fundamentally a **policy regime model** more than a pure time series model. Key regime shifts:
1. Pre-2012: market-driven + SBV rate tracking
2. 2012-2023: auction-suppressed premium era
3. 2024+: auction resumption, premium volatility increase

---

## 6. Walk-Forward Validation & Decision-Oriented Metrics

### 6.1 Validation Protocol

| Citation/Standard | Recommendation |
|---|---|
| Makridakis et al. (2022) | Expanding window is the only valid protocol for financial data; random split causes leakage |
| Bergmeir & Benítez (2012) — *NN* | Even for ML models on time series, nested CV required for unbiased error estimates |
| Ricardo et al. (2020) — *Int. J. Forecasting* | For horizons >1 step, use rolling-origin rather than expanding window to avoid structural break contamination |

### 6.2 Decision-Oriented Metrics (Beyond MAE/RMSE)

| Metric | Definition | Why for Vietnam |
|---|---|---|
| **Excess return vs savings rate** | E[return_after_spread] - deposit_rate | Gold buys should beat holding cash |
| **Max drawdown in holding period** | Peak-to-trough loss during 21d/63d/105d horizon | Vietnamese retail investors are loss-averse; drawdown risk matters more than volatility |
| **Hit rate of prediction intervals** | % actual returns falling within predicted [5%, 95%] quantile | Probabilistic forecasts directly inform "will I lose money" decision |
| **Premium-adjusted entry quality** | Did entry occur when premium was above/below its 365d median? | Premium timing is the alpha source in VN gold investing |
| **Turnover / rebalance frequency** | How often model changes signal | Transaction costs are real in VN (spread ~0.3%) |
| **Directional accuracy** | Sign(Predicted_return) == Sign(Actual_return) | For trading signals, direction matters more than magnitude |

---

## 7. Comprehensive Methodology Comparison

| Model Family | Best For | Vietnam Suitability | Priority |
|---|---|---|---|
| **Persistence / Naive** | Baseline, sanity check | ★★★★★ | Run first |
| **SARIMAX** | Linear trend + seasonality + exogenous | ★★★☆☆ | Baseline 1 |
| **VECM** | Cointegrated multivariate (premium decomposition) | ★★★★☆ | Baseline 2 (if Johansen passes) |
| **XGBoost/LightGBM on lagged features** | Non-linear, tabular, mixed features | ★★★★★ | Primary ML model |
| **Hybrid ARIMA-ML** | Best of both worlds | ★★★★☆ | Primary approach |
| **DeepAR** | Probabilistic, multi-series | ★★★☆☆ | If join across sources |
| **TFT** | Multi-horizon probabilistic with covariates | ★★★★☆ | Production candidate |
| **N-BEATS** | Pure accuracy (no intervals) | ★★☆☆☆ | Benchmark only |
| **Prophet / Dynamic regression** | Seasonality + holidays (Tết) | ★★★★☆ | Quick prototype |

---

## 8. Recommended Experimental Order

Per Makala et al. (2023) and Makridakis et al. (2022), the order should be:

1. **Naive** (persistence, seasonal naive) → establish lower bound
2. **SARIMAX(1,1,1) + exog** (VIX, DXY, USD/VND, lags) → statistical baseline
3. **XGBoost/LightGBM** on engineered features → primary model
4. **Hybrid**: SARIMAX residuals → XGBoost → ensemble
5. **TFT** (if steps 1-4 show promise) → production candidate

**Critical recommendation**: Predict **future returns** (or premium regime classification), NOT price levels. This addresses the "inability to extrapolate" finding from M4 analysis.

---

## 9. Gaps in Current Literature

1. **No probabilistic forecasting work on Vietnam gold premium specifically** — all existing work is point-forecast only
2. **No regime-switching model for Vietnamese gold** — need Markov-switching or threshold model for auction/policy interventions
3. **Limited work on multi-horizon (1m, 3m, 5m) for gold in EM** — most papers focus on daily/weekly
4. **TFT never applied to commodity premium decomposition** — novel application opportunity
5. **Decision-oriented metrics absent from commodity forecasting literature** — no published work on "should I buy" decision systems for gold

---

## 10. Sources

| # | DOI / URL | Quality | Subtopic |
|---|---|---|---|
| 1 | doi:10.1016/j.ijforecast.2021.03.012 | Primary | TFT benchmark |
| 2 | doi:10.1080/01605682.2022.2118629 | Primary | M4/WISEs analysis |
| 3 | doi:10.3390/fi15080255 | Primary | Gold ML survey |
| 4 | doi:10.48550/arxiv.1905.10437 | Primary | N-BEATS |
| 5 | arxiv.org/abs/2601.12706 | Primary | TATS on gold |
| 6 | doi:10.1007/s10479-022-05076-6 | Primary | LSTM on commodities |
| 7 | doi:10.31219/osf.io/85dqp | Primary | **Vietnam gold market** |
| 8 | doi:10.1016/j.ememar.2017.12.006 | Primary | Safe-haven, EM |
| 9 | arxiv.org/abs/1912.09363 | Primary | TFT architecture |
| 10 | arxiv.org/abs/1704.04110 | Primary | DeepAR |
| 11 | arxiv.org/abs/2201.12886 | Primary | N-HiTS |
| 12 | doi:10.1108/jefas-03-2017-0052 | Primary | Gold ARDL/VECM |
| 13 | doi:10.1016/j.physa.2015.07.011 | Primary | Info flow gold markets |
| 14 | doi:10.1016/j.eneco.2014.04.021 | Primary | Arbitrage band |
| 15 | doi:10.1016/j.jbankfin.2009.12.008 | Primary | Gold safe-haven |
| 16 | arxiv.org/abs/2211.14730 | Primary | Neural forecasting |
| 17 | SemanticScholar: 3c9353... | Secondary | Gold forecasting review |
| 18 | SemanticScholar: 47846... | Secondary | Financial TS survey |
| 19 | Baur & McDermott (2010) — *JIMF* | Primary | Gold safe-haven |
| 20 | Beckmann et al. (2015) — *IJFE* | Primary | Uncertainty → gold |
| 21 | Baur & Lucey (2010) | Primary | Regime-dependent safe haven |
| 22 | Makridakis et al. (2018) — *M4 competition* | Primary | Baseline reference |
| 23 | Johansen (1995) — foundational | Foundational | VECM |
| 24 | Box & Jenkins (1976) — foundational | Foundational | ARIMA |
| 25 | Bergmeir & Benítez (2012) — *NN* | Primary | CV for time series |
| 26 | Ricardo et al. (2020) — *IJF* | Primary | Rolling-origin evaluation |
| 27 | Reuters/Bloomberg (2024) — market reporting | Industry | VN gold premium 2024 |
| 28 | SBV regulatory documents | Official | Nghị định 43, auction framework |
| 29 | Nguyen et al. (2023) — UEH | Academic | SJC premium duration study |
| 30 | OpenAlex: W2981482780 | Unreliable | Skipped |

---

## 11. Direct Takeaway for Our Modeling Pipeline

Based on this review, the recommended architecture for Vietnam gold forecasting is:

```
[Premium Decomposition Layer]
    global_gold_vnd_per_luong = LBMA_USD × USD/VND × 1.205327
    premium = domestic_mid - global_gold_vnd_per_luong
    spread = sell - buy

[Feature Engineering]
    lags: [1, 5, 20, 60, 120] of premium, spread, vix, dxy, usd_vnd
    rolling_stats: [20, 60]-day mean_abs_deviation, z-score
    calendar: month_sin/cos, weekday, days_to_tet, days_to_than_tai
    event_dummies: rolling 30d policy count, auction_active
    source_features: source_count, source_dispersion, primary_reliability

[Model Stack — in priority order]
    1. Seasonal Naive (baseline)
    2. SARIMAX + exog (statistical baseline)
    3. XGBoost/LightGBM on engineered features (production)
    4. Hybrid: SARIMAX residuals → XGBoost (if needed)
    5. TFT (production candidate, if data justifies)

[Target]
    future_return_21d / future_return_63d / future_return_105d
    (NOT price level — addresses extrapolation limitation)

[Validation]
    Expanding window, min 5 folds
    Metrics: sMAPE, directional accuracy, excess_return_vs_savings_rate,
            max_drawdown, premium-adjusted entry quality
```
