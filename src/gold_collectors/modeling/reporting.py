"""Tổng hợp kết quả và ghi báo cáo từ đầu ra phân tích đã có."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from .config import (
    ModelingConfig,
)
from .features import (
    _path,
)


# Tổng hợp độ phủ, bảng xếp hạng, tín hiệu và các hạn chế từ kết quả đã tính.
def summarize_outputs(frame: pd.DataFrame, results: pd.DataFrame, signals: pd.DataFrame, blockers: list[str], config: ModelingConfig) -> dict[str, Any]:
    deposit_cols = [c for c in frame.columns if c.startswith("deposit_return_")]
    deposit_non_null = int(frame[deposit_cols].notna().sum().sum()) if deposit_cols else 0
    deposit_status = "included_asof" if deposit_non_null else "excluded_no_historical_asof_rate"
    if not _path(config, "normalized", "retail_deposit_rates.csv").exists():
        deposit_status = "excluded_missing_retail_deposit_file"
    summary: dict[str, Any] = {
        "generated_at": datetime.utcnow().isoformat(),
        "rows": int(len(frame)),
        "date_min": str(frame["date"].min().date()),
        "date_max": str(frame["date"].max().date()),
        "premium_missing_rate": float(frame["premium"].isna().mean()) if "premium" in frame else np.nan,
        "deposit_rate_feature": deposit_status,
        "deposit_rate_non_null_values": deposit_non_null,
        "blockers": blockers,
    }
    target_cols = [f"net_return_{h}m" for h in config.horizons]
    summary["target_non_null"] = {c: int(frame[c].notna().sum()) for c in target_cols if c in frame}
    if not results.empty:
        leaderboard = (
            results[results["phase"].isin(["validation", "test"])]
            .groupby(["model", "horizon_months"], as_index=False)
            .agg(**{k: v for k, v in {"mae": ("mae", "mean"), "rmse": ("rmse", "mean"), "directional_accuracy": ("directional_accuracy", "mean"), "pinball_loss": ("pinball_loss", "mean")}.items() if k in results.columns})
            .sort_values(["horizon_months", "mae"], na_position="last")
        )
        summary["leaderboard"] = leaderboard.to_dict(orient="records")
    if not signals.empty:
        default = signals[(signals["prob_threshold"].eq(config.decision_prob_threshold)) & (signals["q10_floor"].eq(config.decision_q10_floor))]
        summary["decision_summary"] = (
            default.groupby(["horizon_months", "phase"], as_index=False)
            .agg(
                signal_days=("buy_signal", "sum"),
                observations=("buy_signal", "count"),
                avg_strategy_return=("strategy_return", "mean"),
                avg_buy_day_return=("actual_net_return", lambda s: float(s[default.loc[s.index, "buy_signal"]].mean()) if default.loc[s.index, "buy_signal"].any() else np.nan),
            )
            .to_dict(orient="records")
        )
    return summary



# Ghi báo cáo phân tích theo cấu hình; không thu thập thêm dữ liệu trong bước trình bày.
def write_report(summary: dict[str, Any], config: ModelingConfig) -> Path:
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    leaderboard = pd.DataFrame(summary.get("leaderboard", []))
    decision = pd.DataFrame(summary.get("decision_summary", []))

    best_lines: list[str] = []
    if not leaderboard.empty:
        for horizon, group in leaderboard.dropna(subset=["mae"]).groupby("horizon_months"):
            best = group.sort_values("mae").iloc[0]
            best_lines.append(
                f"- Horizon {int(horizon)} tháng: `{best['model']}` có MAE return trung bình {best['mae']:.4f}, directional accuracy {best['directional_accuracy']:.2%}."
            )
    decision_lines: list[str] = []
    if not decision.empty:
        for _, row in decision.iterrows():
            avg_buy_day_return = (
                f"{row['avg_buy_day_return']:.4f}"
                if pd.notna(row["avg_buy_day_return"])
                else "n/a (không có ngày phát tín hiệu)"
            )
            decision_lines.append(
                f"- {int(row['horizon_months'])} tháng, {row['phase']}: {int(row['signal_days'])}/{int(row['observations'])} ngày phát tín hiệu; return trung bình trên ngày mua {avg_buy_day_return}."
            )

    blockers = summary.get("blockers", [])
    blocker_lines = "\n".join(f"- {b}" for b in blockers[:20]) or "- Không có blocker runtime nghiêm trọng."

    text = f"""# VN Gold Decision Support: EDA, Literature Review Và Modeling

## Technical Summary
- Bộ dữ liệu modeling có {summary['rows']:,} ngày, từ {summary['date_min']} đến {summary['date_max']}. Target chính là return sau spread: giá mua vào của phiên SJC đầu tiên từ ngày tròn 1, 3 hoặc 5 tháng chia cho giá bán ra ở ngày dự báo, trừ 1.
- Premium decomposition dùng được nhưng chưa hoàn hảo: tỷ lệ thiếu `premium` trong model frame là {summary['premium_missing_rate']:.1%}. Đây là caveat lớn nhất cho diễn giải premium.
- Lãi suất tiền gửi VN bị loại khỏi feature set vì `deposit_rates_vn.csv` có `value` null 100%; opportunity cost chưa production-grade.
- News được lấy từ `news_raw_headlines_vietnam_gold.csv` và chuyển thành các biến intensity/policy/premium/sentiment heuristic theo `event_date`, lag `t-1`; đây là event proxy, không phải sentiment real-time đã kiểm chứng.
- DeepAR/TFT được ghi nhận như nhóm phương pháp trong literature review, nhưng runner v1 không huấn luyện nếu thiếu dependency nặng.

## Key Findings From The Executed Run
{chr(10).join(best_lines) if best_lines else "- Chưa có leaderboard khả dụng; xem blockers bên dưới."}

Decision-rule mặc định dùng `P(net_return > 0) >= 0.50` và q10 return không thấp hơn `-10%`.

{chr(10).join(decision_lines) if decision_lines else "- Chưa có decision signal khả dụng; xem blockers bên dưới."}

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
{blocker_lines}

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
"""
    config.report_path.write_text(text, encoding="utf-8")
    return config.report_path
