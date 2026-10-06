# VN Gold Decision Support: EDA, Literature Review Và Modeling

## Technical Summary
- Bộ dữ liệu modeling có 5,485 ngày, từ 2011-07-06 đến 2026-07-11. Target chính là return sau spread: `buy_price_t+h / sell_price_t - 1` cho horizon 21, 63, 105 ngày.
- Premium decomposition dùng được nhưng chưa hoàn hảo: tỷ lệ thiếu `premium` trong model frame là 0.0%. Đây là caveat lớn nhất cho diễn giải premium.
- Lãi suất tiền gửi VN bị loại khỏi feature set vì `deposit_rates_vn.csv` có `value` null 100%; opportunity cost chưa production-grade.
- News được lấy từ `news_raw_headlines_vietnam_gold.csv` và chuyển thành các biến intensity/policy/premium/sentiment heuristic theo `event_date`, lag `t-1`; đây là event proxy, không phải sentiment real-time đã kiểm chứng.
- DeepAR/TFT được ghi nhận như nhóm phương pháp trong literature review, nhưng runner v1 không huấn luyện nếu thiếu dependency nặng.

## Key Findings From The Executed Run
- Horizon 21 ngày: `sarimax_exog` có MAE return trung bình 0.0231, directional accuracy 56.30%.
- Horizon 63 ngày: `naive_zero_return` có MAE return trung bình 0.0715, directional accuracy 1.22%.
- Horizon 105 ngày: `lightgbm_mean` có MAE return trung bình 0.1026, directional accuracy 55.39%.

Decision-rule mặc định dùng `P(net_return > 0) >= 0.60` và q10 return không thấp hơn `-5%`.

- 21 ngày, test: 18/365 ngày phát tín hiệu; return trung bình trên ngày mua 0.0100.
- 21 ngày, validation: 0/365 ngày phát tín hiệu; return trung bình trên ngày mua n/a (không có ngày phát tín hiệu).
- 63 ngày, test: 149/494 ngày phát tín hiệu; return trung bình trên ngày mua -0.0495.
- 63 ngày, validation: 283/731 ngày phát tín hiệu; return trung bình trên ngày mua -0.0062.
- 105 ngày, test: 449/452 ngày phát tín hiệu; return trung bình trên ngày mua 0.1279.
- 105 ngày, validation: 366/731 ngày phát tín hiệu; return trung bình trên ngày mua 0.0237.

## Scope, Data, And Metric Definitions
- Target source: `data/lake/gold_quotes_sjc_historical.csv`, gom quote cuối ngày theo timestamp cho SJC Hồ Chí Minh.
- Decomposition: `data/lake/pipeline_output_premium_enriched.csv`, gồm `global_gold_vnd_per_luong`, `premium`, `premium_pct`.
- Global features: `data/lake/pipeline_output_global_reference.csv`; tất cả global/US market features được as-of merge với cutoff `date - 1 day`.
- Macro VN: `data/lake/vn_macro_forecasting.csv`; join bằng `available_from <= date`, không dùng `observation_date` làm cutoff.
- Events: `pipeline_output_event_regime.csv` hoặc fallback master/normalized event panel; policy/geopolitical events chỉ dùng past windows, còn Tết/Thần Tài/wedding được dùng như known-future calendar.
- News raw headlines: `data/lake/news_raw_headlines_vietnam_gold.csv`; feature gồm daily count, gold/VND/policy/premium keyword intensity, positive/negative keyword balance, và rolling 7/30 ngày.
- GPR: `data/lake/gpr_daily_geopolitical_risk.csv`, lag bằng cutoff `date - 1 day`.

## Literature Review: Why This Model Shape Is Appropriate
- Gold hedge/safe-haven literature supports treating gold as regime-sensitive rather than a plain trend series: Baur & McDermott (2010) and Baur & Lucey show safe-haven behavior is strongest in stress windows.
- LBMA/IBA timing matters because gold benchmarks are auction-based, with gold fixes at 10:30 and 15:00 London time; the notebook therefore treats same-day global closes conservatively.
- FRED/ALFRED real-time periods motivate the leakage guardrail: macro and market values must be joined by availability, not by observation period alone.
- SARIMAX and VECM are included because the VN gold price naturally decomposes into global gold, USD/VND and domestic premium; tree models are included because policy/event interactions are nonlinear; quantile models are included because the decision needs downside risk, not only expected return.
- DeepAR and TFT remain production-candidate methods for probabilistic multi-horizon forecasting once dependency/runtime and panel-engineering costs are justified by baseline signal.

## Methodology
1. Build a daily target from official SJC historical quotes, retaining buy/sell/mid/spread.
2. Attach decomposition, global, GPR, macro, event and optional news features using as-of rules.
3. Generate lag and rolling features over 1, 5, 10, 21, 63 and 105 days.
4. Create labels for 21, 63 and 105-day net return, gross sell return and future drawdown.
5. Evaluate chronological expanding-window folds: train through 2022, then annual validation/test windows through 2026.
6. Train naive baselines, SARIMAX, sklearn ML models and quantile models; optional XGBoost/LightGBM/deep models are used only if installed.
7. Convert model forecasts into decision signals through probability and q10 downside thresholds.

## Limitations And Robustness
- Premium coverage is incomplete; premium-driven conclusions should be read as directional until LBMA/FX coverage is improved.
- Deposit-rate opportunity cost is missing, so decision returns are not yet benchmarked against a true VN savings alternative.
- Same-day domestic quote is assumed known at decision time; global and US features are lagged to prevent time-zone leakage.
- Raw headline features are included with `event_date` lagging, but strict real-time availability is not fully proven because the Google RSS backfill was collected in 2026.
- VECM is treated as a screen in v1; it should become a full forecast only after stable cointegration is confirmed across rolling windows.

## Runtime Blockers And Skips
- VECM cointegration screen did_not_pass; VECM forecast not promoted in v1 notebook.
- Data diagnostics: {"raw_news_headline_rows": 3441, "raw_news_headline_unique_days": 702, "raw_news_headline_coverage": 0.12798541476754785, "raw_news_modeling_status": "included_event_date_asof_lagged", "raw_news_leakage_caveat": "Google RSS was backfilled in 2026; event_date is treated as article publication date and lagged t-1, but strict real-time crawl availability is not proven."}

## Recommended Next Steps
1. Fix or replace VN deposit-rate history before treating the strategy as investable against savings-rate opportunity cost.
2. Improve premium coverage by adding true historical LBMA AM/PM or a better licensed benchmark source.
3. Promote DeepAR/TFT only after the tabular and econometric leaderboard shows stable out-of-sample signal.
4. If this needs to become a stakeholder-facing deck, export the executed notebook visuals and add model-card diagnostics by regime.

## Source Anchors
- Baur & McDermott 2010: https://www.sciencedirect.com/science/article/abs/pii/S0378426609003343
- Baur & Lucey: https://ideas.repec.org/p/iis/dispap/iiisdp198.html
- LBMA precious metals prices: https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices
- FRED API: https://fred.stlouisfed.org/docs/api/fred/
- FRED real-time periods: https://fred.stlouisfed.org/docs/api/fred/realtime_period.html
- statsmodels SARIMAX: https://www.statsmodels.org/stable/generated/statsmodels.tsa.statespace.sarimax.SARIMAX.html
- statsmodels VECM: https://www.statsmodels.org/stable/generated/statsmodels.tsa.vector_ar.vecm.VECM.html
- StatsForecast: https://nixtlaverse.nixtla.io/statsforecast/index.html
- LightGBM quantile objective: https://lightgbm.readthedocs.io/en/latest/Parameters.html
- DeepAR: https://arxiv.org/abs/1704.04110
- Temporal Fusion Transformer: https://arxiv.org/abs/1912.09363
