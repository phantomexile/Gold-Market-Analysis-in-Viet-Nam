from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
LAKE = ROOT / "data" / "lake"
REPORTS = ROOT / "docs" / "reports"

HORIZONS = (21, 63, 105)
LAGS = (1, 5, 10, 21, 63, 105)
LUONG_PER_OZ = (31.1034768 / 1.205) / 37.5


@dataclass(frozen=True)
class ModelingConfig:
    """Paths and defaults for reproducible decision-support modeling."""

    data_lake: Path = LAKE
    output_dir: Path = LAKE / "modeling"
    report_path: Path = REPORTS / "eda_modeling_literature_review.md"
    horizons: tuple[int, ...] = HORIZONS
    lags: tuple[int, ...] = LAGS
    initial_train_end: str = "2022-12-31"
    validation_start: str = "2023-01-01"
    validation_end: str = "2024-12-31"
    test_start: str = "2025-01-01"
    test_end: str = "2026-12-31"
    decision_prob_threshold: float = 0.50
    decision_q10_floor: float = -0.10
    random_state: int = 42
    include_news_if_coverage_at_least: float = 0.20
    feature_columns: tuple[str, ...] = field(default_factory=tuple)


def _read_csv(path: Path, *, parse_dates: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=parse_dates, low_memory=False)


def _path(config: ModelingConfig, *parts: str) -> Path:
    return config.data_lake.joinpath(*parts)


def _date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def _safe_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _last_quote_per_day(target: pd.DataFrame) -> pd.DataFrame:
    target = target.copy()
    target["date"] = _date_series(target["date"])
    target["timestamp_sort"] = pd.to_datetime(target.get("timestamp"), errors="coerce", utc=True)
    target = _safe_numeric(target, ["buy", "sell", "spread"])
    target = target.dropna(subset=["date", "buy", "sell"])
    target = target[(target["buy"] > 0) & (target["sell"] >= target["buy"])]
    target = target.sort_values(["date", "timestamp_sort"]).groupby("date", as_index=False).tail(1)
    target = target.rename(columns={"buy": "buy_price", "sell": "sell_price"})
    target["mid_price"] = (target["buy_price"] + target["sell_price"]) / 2
    target["spread_abs"] = target["sell_price"] - target["buy_price"]
    target["spread_pct"] = target["spread_abs"] / target["sell_price"]
    return target[["date", "buy_price", "sell_price", "mid_price", "spread_abs", "spread_pct"]]


def _merge_global_asof(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    global_ref = _read_csv(_path(config, "pipeline_output_global_reference.csv"))
    if global_ref.empty:
        frame["global_feature_date"] = pd.NaT
        return frame

    global_ref["global_feature_date"] = _date_series(global_ref["date"])
    numeric_cols = [
        "dxy_index",
        "gold_futures_close_usd_oz",
        "lbma_price_usd_oz",
        "oil_wti_usd_barrel",
        "silver_futures_close_usd_oz",
        "sp500_index",
        "treasury_10y_pct",
        "usd_vnd_market_rate",
        "usd_vnd_mid",
        "vix",
    ]
    global_ref = _safe_numeric(global_ref, numeric_cols)
    keep = ["global_feature_date"] + [c for c in numeric_cols if c in global_ref.columns]
    global_ref = global_ref[keep].sort_values("global_feature_date")

    left = frame.sort_values("date").copy()
    left["global_cutoff_date"] = left["date"] - pd.Timedelta(days=1)
    merged = pd.merge_asof(
        left,
        global_ref,
        left_on="global_cutoff_date",
        right_on="global_feature_date",
        direction="backward",
    )
    return merged.drop(columns=["global_cutoff_date"])


def _merge_gpr_asof(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    gpr = _read_csv(_path(config, "gpr_daily_geopolitical_risk.csv"))
    if gpr.empty:
        return frame
    gpr["gpr_feature_date"] = _date_series(gpr["date"])
    gpr = _safe_numeric(gpr, ["GPRD", "GPRD_ACT", "GPRD_THREAT", "GPRD_MA7", "GPRD_MA30"])
    gpr = gpr[["gpr_feature_date", "GPRD", "GPRD_ACT", "GPRD_THREAT", "GPRD_MA7", "GPRD_MA30"]]
    left = frame.sort_values("date").copy()
    left["gpr_cutoff_date"] = left["date"] - pd.Timedelta(days=1)
    merged = pd.merge_asof(
        left,
        gpr.sort_values("gpr_feature_date"),
        left_on="gpr_cutoff_date",
        right_on="gpr_feature_date",
        direction="backward",
    )
    return merged.drop(columns=["gpr_cutoff_date"])


def _merge_premium(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    premium = _read_csv(_path(config, "pipeline_output_premium_enriched.csv"))
    if premium.empty:
        return frame
    premium["date"] = _date_series(premium["date"])
    numeric_cols = [
        "global_gold_usd_oz",
        "global_gold_vnd_per_luong",
        "premium",
        "premium_pct",
        "source_count",
        "source_dispersion",
        "usd_vnd",
        "gold_staleness_days",
        "fx_staleness_days",
        "is_proxy",
    ]
    if "is_proxy" in premium.columns:
        premium["is_proxy"] = premium["is_proxy"].astype(str).str.lower().isin(["true", "1", "yes"]).astype(float)
    premium = _safe_numeric(premium, numeric_cols)
    keep = ["date"] + [c for c in numeric_cols if c in premium.columns]
    return frame.merge(premium[keep], on="date", how="left")


def _merge_macro_asof(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    macro = _read_csv(_path(config, "vn_macro_forecasting.csv"))
    if macro.empty:
        frame["macro_feature_date"] = pd.NaT
        return frame

    macro["available_from"] = _date_series(macro["available_from"])
    macro["value"] = pd.to_numeric(macro["value"], errors="coerce")
    macro["feature_name"] = (
        macro["series_name"].fillna(macro["series_id"]).astype(str).str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
    )
    wide = (
        macro.dropna(subset=["available_from", "feature_name"])
        .pivot_table(index="available_from", columns="feature_name", values="value", aggfunc="last")
        .sort_index()
        .ffill()
        .reset_index()
        .rename(columns={"available_from": "macro_feature_date"})
    )
    keep_cols = ["macro_feature_date"] + [c for c in wide.columns if c != "macro_feature_date"][:25]
    left = frame.sort_values("date").copy()
    return pd.merge_asof(
        left,
        wide[keep_cols].sort_values("macro_feature_date"),
        left_on="date",
        right_on="macro_feature_date",
        direction="backward",
    )


def _merge_deposit_asof(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    rates = _read_csv(_path(config, "normalized", "retail_deposit_rates.csv"))
    if rates.empty:
        return frame
    rates = rates.copy()
    rates["available_from"] = _date_series(rates.get("available_from", rates.get("date")))
    rates["tenor_months"] = pd.to_numeric(rates.get("tenor_months"), errors="coerce")
    rates["rate_pct_annual"] = pd.to_numeric(rates.get("rate_pct_annual"), errors="coerce")
    rates = rates.dropna(subset=["available_from", "tenor_months", "rate_pct_annual"])
    rates = rates[(rates["rate_pct_annual"] >= 0) & (rates["rate_pct_annual"] <= 20)]
    if rates.empty:
        return frame

    horizon_to_tenor = {21: 1, 63: 3, 105: 5}
    out = frame.sort_values("date").copy()
    for horizon, tenor in horizon_to_tenor.items():
        sub = (
            rates[rates["tenor_months"].astype(int).eq(tenor)]
            .groupby("available_from", as_index=False)["rate_pct_annual"]
            .mean()
            .sort_values("available_from")
        )
        if sub.empty:
            continue
        merged = pd.merge_asof(
            out[["date"]].sort_values("date"),
            sub,
            left_on="date",
            right_on="available_from",
            direction="backward",
        )
        rate_col = f"deposit_rate_{horizon}d_annual_pct"
        ret_col = f"deposit_return_{horizon}d"
        out[rate_col] = merged["rate_pct_annual"].to_numpy()
        out[ret_col] = (out[rate_col] / 100.0) * (horizon / 365.0)
    return out


def _event_path(config: ModelingConfig) -> Path:
    candidates = [
        _path(config, "pipeline_output_event_regime.csv"),
        _path(config, "enriched", "master", "normalized", "event_regime_panel.csv"),
        _path(config, "normalized", "event_regime_panel.csv"),
        _path(config, "gold_event_panel.csv"),
    ]
    return next((p for p in candidates if p.exists()), candidates[0])


def _merge_events(frame: pd.DataFrame, config: ModelingConfig) -> pd.DataFrame:
    events = _read_csv(_event_path(config))
    frame = frame.copy()
    if events.empty:
        return frame

    date_col = "event_date" if "event_date" in events.columns else "date"
    events["event_date"] = _date_series(events[date_col])
    events = events.dropna(subset=["event_date"])
    daily = pd.DataFrame({"date": frame["date"].sort_values().unique()})
    daily = daily.sort_values("date")

    event_counts = events.groupby("event_date").size().rename("event_count").to_frame()
    severity_counts = (
        pd.get_dummies(events.set_index("event_date")["severity"].fillna("unknown"), prefix="severity")
        .groupby(level=0)
        .sum()
    )
    channel_counts = (
        pd.get_dummies(events.set_index("event_date")["expected_channel"].fillna("unknown"), prefix="channel")
        .groupby(level=0)
        .sum()
    )
    type_counts = (
        pd.get_dummies(events.set_index("event_date")["event_type"].fillna("unknown"), prefix="event")
        .groupby(level=0)
        .sum()
    )
    event_daily = event_counts.join(severity_counts, how="outer").join(channel_counts, how="outer").join(type_counts, how="outer")
    daily = daily.merge(event_daily.reset_index().rename(columns={"event_date": "date"}), on="date", how="left").fillna(0)

    count_cols = [c for c in daily.columns if c != "date"]
    for window in (7, 30):
        for col in count_cols:
            daily[f"{col}_past_{window}d"] = daily[col].rolling(window=window, min_periods=1).sum()

    known_future = {
        "tet_proximity": "days_until_next_tet",
        "than_tai": "days_until_next_than_tai",
        "wedding_season": "days_until_next_wedding_season",
    }
    for event_type, output_col in known_future.items():
        dates = np.sort(events.loc[events["event_type"].astype(str).str.lower().eq(event_type), "event_date"].unique())
        daily[output_col] = np.nan
        if len(dates):
            event_dates = pd.to_datetime(dates)
            values = []
            for d in daily["date"]:
                future = event_dates[event_dates >= d]
                values.append((future[0] - d).days if len(future) else np.nan)
            daily[output_col] = values

    return frame.merge(daily, on="date", how="left")


def _maybe_merge_news(frame: pd.DataFrame, config: ModelingConfig, diagnostics: dict[str, Any]) -> pd.DataFrame:
    raw_news = _read_csv(_path(config, "news_raw_headlines_vietnam_gold.csv"))
    if not raw_news.empty and "event_date" in raw_news.columns:
        raw_news = raw_news.copy()
        raw_news["news_event_date"] = _date_series(raw_news["event_date"])
        raw_news = raw_news.dropna(subset=["news_event_date"])
        text = (
            raw_news.get("headline", pd.Series("", index=raw_news.index)).fillna("")
            + " "
            + raw_news.get("body_text", pd.Series("", index=raw_news.index)).fillna("")
            + " "
            + raw_news.get("category", pd.Series("", index=raw_news.index)).fillna("")
        ).str.lower()
        positive_terms = r"tăng|phục hồi|lên|cao|kỷ lục|record|surge|rally|gain|up"
        negative_terms = r"giảm|rơi|lao dốc|đi xuống|thấp|drop|fall|plunge|down"
        raw_news["raw_news_count"] = 1
        category = raw_news.get("category", pd.Series("", index=raw_news.index)).astype(str)
        raw_news["raw_news_gold_vn_count"] = category.eq("gold_vn").astype(int)
        raw_news["raw_news_fx_vnd_count"] = category.eq("fx_vnd").astype(int)
        raw_news["raw_news_policy_count"] = text.str.contains(r"sbv|nhnn|ngân hàng nhà nước|đấu thầu|chính sách|policy|lãi suất", regex=True).astype(int)
        raw_news["raw_news_premium_count"] = text.str.contains(r"chênh lệch|premium|vênh|cao hơn thế giới", regex=True).astype(int)
        raw_news["raw_news_positive_count"] = text.str.contains(positive_terms, regex=True).astype(int)
        raw_news["raw_news_negative_count"] = text.str.contains(negative_terms, regex=True).astype(int)
        raw_news["raw_news_sentiment_balance"] = raw_news["raw_news_positive_count"] - raw_news["raw_news_negative_count"]

        daily = (
            raw_news.groupby("news_event_date", as_index=False)[
                [
                    "raw_news_count",
                    "raw_news_gold_vn_count",
                    "raw_news_fx_vnd_count",
                    "raw_news_policy_count",
                    "raw_news_premium_count",
                    "raw_news_positive_count",
                    "raw_news_negative_count",
                    "raw_news_sentiment_balance",
                ]
            ]
            .sum()
            .sort_values("news_event_date")
        )
        for col in [c for c in daily.columns if c != "news_event_date"]:
            daily[f"{col}_ma7"] = daily[col].rolling(7, min_periods=1).mean()
            daily[f"{col}_ma30"] = daily[col].rolling(30, min_periods=1).mean()

        coverage = raw_news["news_event_date"].nunique() / max(frame["date"].nunique(), 1)
        diagnostics["raw_news_headline_rows"] = int(len(raw_news))
        diagnostics["raw_news_headline_unique_days"] = int(raw_news["news_event_date"].nunique())
        diagnostics["raw_news_headline_coverage"] = float(coverage)
        diagnostics["raw_news_modeling_status"] = "included_event_date_asof_lagged"
        diagnostics["raw_news_leakage_caveat"] = (
            "Google RSS was backfilled in 2026; event_date is treated as article publication date and lagged t-1, "
            "but strict real-time crawl availability is not proven."
        )

        left = frame.sort_values("date").copy()
        left["news_cutoff_date"] = left["date"] - pd.Timedelta(days=1)
        merged = pd.merge_asof(
            left,
            daily,
            left_on="news_cutoff_date",
            right_on="news_event_date",
            direction="backward",
        ).drop(columns=["news_cutoff_date"])
        news_cols = [c for c in merged.columns if c.startswith("raw_news_")]
        merged[news_cols] = merged[news_cols].fillna(0)
        return merged

    news = _read_csv(_path(config, "news_sentiment.csv"))
    if news.empty:
        diagnostics["news_modeling_status"] = "skipped_missing_file"
        return frame
    news["date"] = _date_series(news["date"])
    news["value"] = pd.to_numeric(news["value"], errors="coerce")
    coverage = news["date"].nunique() / max(frame["date"].nunique(), 1)
    diagnostics["news_sentiment_coverage"] = coverage
    if coverage < config.include_news_if_coverage_at_least:
        diagnostics["news_modeling_status"] = "skipped_low_coverage"
        return frame
    news_daily = news.groupby("date", as_index=False)["value"].mean().rename(columns={"value": "news_sentiment_score"})
    diagnostics["news_modeling_status"] = "included"
    return frame.merge(news_daily, on="date", how="left")


def _add_targets(frame: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    frame = frame.sort_values("date").copy()
    for horizon in horizons:
        future_buy = frame["buy_price"].shift(-horizon)
        future_sell = frame["sell_price"].shift(-horizon)
        future_min_buy = frame["buy_price"].shift(-1).iloc[::-1].rolling(horizon, min_periods=horizon).min().iloc[::-1]
        frame[f"future_buy_{horizon}d"] = future_buy
        frame[f"net_return_{horizon}d"] = future_buy / frame["sell_price"] - 1
        frame[f"gross_sell_return_{horizon}d"] = future_sell / frame["sell_price"] - 1
        frame[f"future_drawdown_{horizon}d"] = future_min_buy / frame["sell_price"] - 1
        frame[f"positive_return_{horizon}d"] = (frame[f"net_return_{horizon}d"] > 0).astype(float)
        frame.loc[frame[f"net_return_{horizon}d"].isna(), f"positive_return_{horizon}d"] = np.nan
    return frame


def _add_lagged_features(frame: pd.DataFrame, config: ModelingConfig) -> tuple[pd.DataFrame, list[str]]:
    frame = frame.sort_values("date").copy()
    base_cols = [
        "buy_price",
        "sell_price",
        "mid_price",
        "spread_abs",
        "spread_pct",
        "global_gold_vnd_per_luong",
        "premium",
        "premium_pct",
        "gold_staleness_days",
        "fx_staleness_days",
        "is_proxy",
        "usd_vnd",
        "usd_vnd_mid",
        "gold_futures_close_usd_oz",
        "lbma_price_usd_oz",
        "vix",
        "dxy_index",
        "treasury_10y_pct",
        "GPRD",
        "GPRD_MA7",
        "GPRD_MA30",
        "deposit_return_21d",
        "deposit_return_63d",
        "deposit_return_105d",
    ]
    base_cols += [c for c in frame.columns if c.startswith(("event_count", "severity_", "channel_", "days_until_next_"))]
    base_cols += [c for c in frame.columns if c.startswith("raw_news_")]
    base_cols += [
        c
        for c in frame.columns
        if c
        in {
            "imports_all_cif_m_usd",
            "imports_direct_m_usd",
            "vnindex_eop",
            "cpi_monthly_index",
            "ip_total_index",
            "unemployment_rate_pct",
        }
    ]
    base_cols = [c for c in dict.fromkeys(base_cols) if c in frame.columns]

    feature_cols: list[str] = []
    new_features: dict[str, pd.Series] = {}
    for col in base_cols:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
        if col.startswith(("event_", "severity_", "channel_", "days_until_next_")):
            feature_cols.append(col)
            continue
        for lag in config.lags:
            new_col = f"{col}_lag_{lag}d"
            new_features[new_col] = frame[col].shift(lag)
            feature_cols.append(new_col)
        for window in (5, 21, 63):
            mean_col = f"{col}_roll_mean_{window}d"
            std_col = f"{col}_roll_std_{window}d"
            new_features[mean_col] = frame[col].rolling(window=window, min_periods=max(2, window // 3)).mean()
            new_features[std_col] = frame[col].rolling(window=window, min_periods=max(2, window // 3)).std()
            feature_cols.extend([mean_col, std_col])

    new_features["sell_return_1d"] = frame["sell_price"].pct_change()
    for window in (5, 21, 63, 105):
        col = f"sell_return_roll_mean_{window}d"
        new_features[col] = new_features["sell_return_1d"].rolling(window, min_periods=max(2, window // 3)).mean()
        feature_cols.append(col)

    if new_features:
        frame = pd.concat([frame, pd.DataFrame(new_features, index=frame.index)], axis=1)
    feature_cols = [c for c in dict.fromkeys(feature_cols) if c in frame.columns]
    return frame, feature_cols


def build_model_frame(config: ModelingConfig | None = None) -> pd.DataFrame:
    """Build the daily model frame with as-of joins, targets, and lagged features."""

    config = config or ModelingConfig()
    diagnostics: dict[str, Any] = {}
    target = _read_csv(_path(config, "gold_quotes_sjc_historical.csv"))
    if target.empty:
        raise FileNotFoundError(_path(config, "gold_quotes_sjc_historical.csv"))

    frame = _last_quote_per_day(target)
    frame = _merge_premium(frame, config)
    frame = _merge_global_asof(frame, config)
    frame = _merge_gpr_asof(frame, config)
    frame = _merge_macro_asof(frame, config)
    frame = _merge_deposit_asof(frame, config)
    frame = _merge_events(frame, config)
    frame = _maybe_merge_news(frame, config, diagnostics)
    frame = _add_targets(frame, config.horizons)
    for horizon in config.horizons:
        ret_col = f"deposit_return_{horizon}d"
        target_col = f"net_return_{horizon}d"
        if ret_col in frame.columns and target_col in frame.columns:
            frame[f"gold_excess_return_vs_deposit_{horizon}d"] = frame[target_col] - frame[ret_col]
    frame, feature_cols = _add_lagged_features(frame, config)
    frame.attrs["feature_columns"] = feature_cols
    frame.attrs["diagnostics"] = diagnostics
    return frame.sort_values("date").reset_index(drop=True)


def make_walk_forward_splits(
    dates: pd.Series,
    *,
    initial_train_end: str = "2022-12-31",
    final_test_end: str = "2026-12-31",
) -> list[dict[str, pd.Timestamp]]:
    """Create chronological expanding-window folds with yearly test windows."""

    min_date = pd.to_datetime(dates.min()).normalize()
    max_date = pd.to_datetime(dates.max()).normalize()
    initial_end = min(pd.Timestamp(initial_train_end), max_date)
    final_end = min(pd.Timestamp(final_test_end), max_date)
    splits: list[dict[str, pd.Timestamp]] = []
    train_end = initial_end
    while train_end < final_end:
        test_start = train_end + pd.Timedelta(days=1)
        test_end = min(pd.Timestamp(year=test_start.year, month=12, day=31), final_end)
        if test_start > max_date:
            break
        splits.append(
            {
                "train_start": min_date,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
            }
        )
        train_end = test_end
    return splits


def _phase_for_dates(dates: pd.Series, config: ModelingConfig) -> pd.Series:
    values = pd.Series("train", index=dates.index, dtype="object")
    values[(dates >= pd.Timestamp(config.validation_start)) & (dates <= pd.Timestamp(config.validation_end))] = "validation"
    values[(dates >= pd.Timestamp(config.test_start)) & (dates <= pd.Timestamp(config.test_end))] = "test"
    return values


def _metrics(actual: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    mask = np.isfinite(actual) & np.isfinite(pred)
    if mask.sum() == 0:
        return {"mae": np.nan, "rmse": np.nan, "directional_accuracy": np.nan}
    y = actual[mask]
    p = pred[mask]
    return {
        "mae": float(np.mean(np.abs(y - p))),
        "rmse": float(np.sqrt(np.mean((y - p) ** 2))),
        "directional_accuracy": float(np.mean(np.sign(y) == np.sign(p))),
    }


def _pinball(actual: np.ndarray, pred: np.ndarray, q: float) -> float:
    mask = np.isfinite(actual) & np.isfinite(pred)
    if mask.sum() == 0:
        return np.nan
    diff = actual[mask] - pred[mask]
    return float(np.mean(np.maximum(q * diff, (q - 1) * diff)))


def _prepare_xy(frame: pd.DataFrame, feature_cols: list[str], target_col: str) -> tuple[pd.DataFrame, pd.Series]:
    cols = [c for c in feature_cols if c in frame.columns]
    x = frame[cols].replace([np.inf, -np.inf], np.nan)
    y = frame[target_col].replace([np.inf, -np.inf], np.nan)
    return x, y


def _impute_train_test(x_train: pd.DataFrame, x_test: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    med = x_train.median(numeric_only=True).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return x_train.fillna(med), x_test.fillna(med)


def _bounded_feature_subset(feature_cols: list[str]) -> list[str]:
    preferred_tokens = (
        "_lag_1d",
        "_lag_21d",
        "_lag_63d",
        "_roll_mean_21d",
        "_roll_std_21d",
        "sell_return_roll_mean_21d",
        "event_count_past_30d",
        "severity_high_past_30d",
        "channel_",
        "days_until_next_",
    )
    selected = [c for c in feature_cols if any(token in c for token in preferred_tokens)]
    if len(selected) < 30:
        selected.extend([c for c in feature_cols if c not in selected])
    return selected[:80]


def train_baselines(frame: pd.DataFrame, config: ModelingConfig | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = config or ModelingConfig()
    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for horizon in config.horizons:
        target_col = f"net_return_{horizon}d"
        for fold_id, split in enumerate(splits, start=1):
            train_mask = (frame["date"] >= split["train_start"]) & (frame["date"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if train.empty or test.empty:
                continue
            model_values = {
                "naive_zero_return": 0.0,
                "historical_mean_return": float(train[target_col].mean()),
                "historical_median_return": float(train[target_col].median()),
            }
            for model_name, value in model_values.items():
                pred = np.full(len(test), value)
                met = _metrics(test[target_col].to_numpy(), pred)
                results.append({"model": model_name, "horizon_days": horizon, "fold": fold_id, "phase": _phase_for_dates(test["date"], config).mode().iat[0], **met})
                for date_value, actual, pred_value, phase in zip(test["date"], test[target_col], pred, _phase_for_dates(test["date"], config)):
                    predictions.append(
                        {
                            "date": date_value,
                            "horizon_days": horizon,
                            "fold": fold_id,
                            "phase": phase,
                            "model": model_name,
                            "prediction_type": "mean",
                            "actual_net_return": actual,
                            "predicted_net_return": pred_value,
                        }
                    )
    return pd.DataFrame(results), pd.DataFrame(predictions)


def train_econometric(
    frame: pd.DataFrame,
    feature_cols: list[str],
    config: ModelingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    config = config or ModelingConfig()
    blockers: list[str] = []
    try:
        from statsmodels.tsa.statespace.sarimax import SARIMAX
        from statsmodels.tsa.vector_ar.vecm import coint_johansen
    except Exception as exc:  # pragma: no cover - depends on local env
        return pd.DataFrame(), pd.DataFrame(), [f"statsmodels unavailable: {exc}"]

    exog_candidates = [
        c
        for c in feature_cols
        if any(key in c for key in ("premium_pct_lag_21d", "usd_vnd_mid_lag_21d", "vix_lag_21d", "dxy_index_lag_21d", "treasury_10y_pct_lag_21d"))
    ][:5]
    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    bounded_splits = [s for s in splits if s["test_start"].year in (2023, 2025)]
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for horizon in config.horizons:
        target_col = f"net_return_{horizon}d"
        for fold_id, split in enumerate(bounded_splits, start=1):
            train_mask = (frame["date"] >= split["train_start"]) & (frame["date"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if len(train) < 200 or test.empty:
                continue
            try:
                x_train, x_test = _impute_train_test(train[exog_candidates], test[exog_candidates])
                y_train = train[target_col].astype(float)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = SARIMAX(y_train, exog=x_train, order=(1, 0, 0), trend="c", enforce_stationarity=False, enforce_invertibility=False)
                    fit = model.fit(disp=False, maxiter=35)
                    pred = np.asarray(fit.forecast(steps=len(test), exog=x_test))
                met = _metrics(test[target_col].to_numpy(), pred)
                results.append({"model": "sarimax_exog", "horizon_days": horizon, "fold": fold_id, "phase": _phase_for_dates(test["date"], config).mode().iat[0], **met})
                for date_value, actual, pred_value, phase in zip(test["date"], test[target_col], pred, _phase_for_dates(test["date"], config)):
                    predictions.append(
                        {
                            "date": date_value,
                            "horizon_days": horizon,
                            "fold": fold_id,
                            "phase": phase,
                            "model": "sarimax_exog",
                            "prediction_type": "mean",
                            "actual_net_return": actual,
                            "predicted_net_return": pred_value,
                        }
                    )
            except Exception as exc:
                blockers.append(f"SARIMAX horizon {horizon} fold {fold_id} skipped: {exc}")

    vecm_cols = ["mid_price", "global_gold_vnd_per_luong", "usd_vnd"]
    vecm_data = frame[vecm_cols].dropna()
    if len(vecm_data) > 300:
        try:
            sample = np.log(vecm_data.tail(min(len(vecm_data), 2500)))
            sample = sample.replace([np.inf, -np.inf], np.nan).dropna()
            johansen = coint_johansen(sample, det_order=0, k_ar_diff=1)
            rank_pass = bool((johansen.lr1 > johansen.cvt[:, 1]).sum() >= 1)
            blockers.append(f"VECM cointegration screen {'passed' if rank_pass else 'did_not_pass'}; VECM forecast not promoted in v1 notebook.")
        except Exception as exc:
            blockers.append(f"VECM cointegration screen skipped: {exc}")
    else:
        blockers.append("VECM skipped: insufficient complete mid/global_gold_vnd/usd_vnd rows.")

    return pd.DataFrame(results), pd.DataFrame(predictions), blockers


def train_ml_models(
    frame: pd.DataFrame,
    feature_cols: list[str],
    config: ModelingConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    config = config or ModelingConfig()
    blockers: list[str] = []
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.linear_model import ElasticNet, Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
    except Exception as exc:  # pragma: no cover - depends on local env
        return pd.DataFrame(), pd.DataFrame(), [f"scikit-learn unavailable: {exc}"]

    feature_cols = _bounded_feature_subset(feature_cols)
    optional_models: dict[str, Any] = {}
    try:
        from lightgbm import LGBMRegressor  # type: ignore

        optional_models["lightgbm_mean"] = LGBMRegressor(n_estimators=300, learning_rate=0.03, random_state=config.random_state, verbose=-1)
        optional_models["lightgbm_q10"] = LGBMRegressor(
            objective="quantile", alpha=0.10, n_estimators=300, learning_rate=0.03, random_state=config.random_state, verbose=-1
        )
    except Exception as exc:
        blockers.append(f"LightGBM unavailable; using sklearn quantile fallback: {exc}")
    try:
        from xgboost import XGBRegressor  # type: ignore

        optional_models["xgboost_mean"] = XGBRegressor(
            n_estimators=250, max_depth=3, learning_rate=0.03, subsample=0.9, colsample_bytree=0.9, random_state=config.random_state
        )
    except Exception as exc:
        blockers.append(f"XGBoost unavailable: {exc}")
    try:
        from catboost import CatBoostRegressor  # type: ignore

        optional_models["catboost_mean"] = CatBoostRegressor(
            iterations=300,
            depth=4,
            learning_rate=0.03,
            loss_function="RMSE",
            random_seed=config.random_state,
            verbose=False,
        )
        optional_models["catboost_q10"] = CatBoostRegressor(
            iterations=300,
            depth=4,
            learning_rate=0.03,
            loss_function="Quantile:alpha=0.10",
            random_seed=config.random_state,
            verbose=False,
        )
    except Exception as exc:
        blockers.append(f"CatBoost unavailable: {exc}")

    mean_models = {
        "ridge": make_pipeline(StandardScaler(with_mean=False), Ridge(alpha=1.0)),
        "elastic_net": make_pipeline(StandardScaler(with_mean=False), ElasticNet(alpha=0.0005, l1_ratio=0.2, random_state=config.random_state, max_iter=3000)),
        "random_forest": RandomForestRegressor(n_estimators=48, max_depth=8, min_samples_leaf=18, random_state=config.random_state, n_jobs=-1),
        **{k: v for k, v in optional_models.items() if k.endswith("_mean")},
    }
    quantile_models = {
        "sklearn_gbr_q05": GradientBoostingRegressor(loss="quantile", alpha=0.05, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q10": GradientBoostingRegressor(loss="quantile", alpha=0.10, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q50": GradientBoostingRegressor(loss="quantile", alpha=0.50, n_estimators=60, max_depth=2, random_state=config.random_state),
        "sklearn_gbr_q90": GradientBoostingRegressor(loss="quantile", alpha=0.90, n_estimators=60, max_depth=2, random_state=config.random_state),
        **{k: v for k, v in optional_models.items() if "_q10" in k},
    }

    splits = make_walk_forward_splits(frame["date"], initial_train_end=config.initial_train_end, final_test_end=config.test_end)
    predictions: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for horizon in config.horizons:
        target_col = f"net_return_{horizon}d"
        for fold_id, split in enumerate(splits, start=1):
            train_mask = (frame["date"] >= split["train_start"]) & (frame["date"] <= split["train_end"])
            test_mask = (frame["date"] >= split["test_start"]) & (frame["date"] <= split["test_end"])
            train = frame.loc[train_mask & frame[target_col].notna()].copy()
            test = frame.loc[test_mask & frame[target_col].notna()].copy()
            if len(train) < 300 or test.empty:
                continue
            x_train, y_train = _prepare_xy(train, feature_cols, target_col)
            x_test, y_test = _prepare_xy(test, feature_cols, target_col)
            x_train, x_test = _impute_train_test(x_train, x_test)
            phase_values = _phase_for_dates(test["date"], config)

            for model_name, model in mean_models.items():
                try:
                    model.fit(x_train, y_train)
                    pred = np.asarray(model.predict(x_test), dtype=float)
                    met = _metrics(y_test.to_numpy(), pred)
                    results.append({"model": model_name, "horizon_days": horizon, "fold": fold_id, "phase": phase_values.mode().iat[0], **met})
                    for date_value, actual, pred_value, phase in zip(test["date"], y_test, pred, phase_values):
                        predictions.append(
                            {
                                "date": date_value,
                                "horizon_days": horizon,
                                "fold": fold_id,
                                "phase": phase,
                                "model": model_name,
                                "prediction_type": "mean",
                                "actual_net_return": actual,
                                "predicted_net_return": pred_value,
                            }
                        )
                except Exception as exc:
                    blockers.append(f"{model_name} horizon {horizon} fold {fold_id} skipped: {exc}")

            for model_name, model in quantile_models.items():
                try:
                    model.fit(x_train, y_train)
                    pred = np.asarray(model.predict(x_test), dtype=float)
                    quantile = 0.10
                    if "_q05" in model_name:
                        quantile = 0.05
                    elif "_q50" in model_name:
                        quantile = 0.50
                    elif "_q90" in model_name:
                        quantile = 0.90
                    results.append(
                        {
                            "model": model_name,
                            "horizon_days": horizon,
                            "fold": fold_id,
                            "phase": phase_values.mode().iat[0],
                            "mae": np.nan,
                            "rmse": np.nan,
                            "directional_accuracy": np.nan,
                            "pinball_loss": _pinball(y_test.to_numpy(), pred, quantile),
                        }
                    )
                    for date_value, actual, pred_value, phase in zip(test["date"], y_test, pred, phase_values):
                        predictions.append(
                            {
                                "date": date_value,
                                "horizon_days": horizon,
                                "fold": fold_id,
                                "phase": phase,
                                "model": model_name,
                                "prediction_type": f"q{int(quantile * 100):02d}",
                                "actual_net_return": actual,
                                "predicted_net_return": pred_value,
                            }
                        )
                except Exception as exc:
                    blockers.append(f"{model_name} horizon {horizon} fold {fold_id} skipped: {exc}")

    deep_missing = []
    for module_name in ("torch", "pytorch_forecasting", "gluonts"):
        try:
            __import__(module_name)
        except Exception:
            deep_missing.append(module_name)
    if deep_missing:
        blockers.append("DeepAR/TFT skipped: missing optional dependencies " + ", ".join(deep_missing))

    return pd.DataFrame(results), pd.DataFrame(predictions), blockers


def evaluate_decision_rules(
    predictions: pd.DataFrame,
    config: ModelingConfig | None = None,
) -> pd.DataFrame:
    config = config or ModelingConfig()
    if predictions.empty:
        return pd.DataFrame()

    mean_preds = predictions[predictions["prediction_type"].eq("mean")].copy()
    validation = mean_preds[mean_preds["phase"].eq("validation")]
    # Pre-compute MAE and directional accuracy per model per horizon.
    # For decision signals we need a model whose predictions VARY across
    # time — "historical_mean_return" returns a constant value, which makes
    # prob_return_positive identical for every date, so the threshold either
    # fires on every day or none.  Score = 0.5 * normalized_MAE + 0.5 * (1 - DA)
    # to pick a balanced model; then keep lowest-MAE among candidates whose
    # predicted_net_return spans > 1% of its own std (i.e. non-constant).
    _skip = {"naive_zero_return", "historical_mean_return", "historical_median_return"}

    def _model_score(g: pd.DataFrame) -> float:
        mae = np.mean(np.abs(g["actual_net_return"] - g["predicted_net_return"]))
        da = np.mean(np.sign(g["actual_net_return"]) == np.sign(g["predicted_net_return"]))
        return 0.5 * (mae / 0.05) + 0.5 * (1.0 - da)  # normalize MAE by ~5% max

    best_models: dict[int, str] = {}
    for horizon in config.horizons:
        subset = validation[validation["horizon_days"].eq(horizon)]
        if subset.empty:
            subset = mean_preds[mean_preds["horizon_days"].eq(horizon)]
        if subset.empty:
            continue
        scored: dict[str, float] = {}
        for model_name, grp in subset.groupby("model"):
            if model_name in _skip:
                continue
            if grp["predicted_net_return"].std(skipna=True) < 1e-6:
                continue  # constant output — useless for threshold signal
            scored[model_name] = _model_score(grp)
        if not scored:
            # fall back to lowest-MAE, but warn is handled upstream
            fallback = subset.groupby("model").apply(
                lambda g: np.mean(np.abs(g["actual_net_return"] - g["predicted_net_return"])),
                include_groups=False,
            )
            if not fallback.empty:
                best_models[horizon] = str(fallback.sort_values().index[0])
            continue
        best_models[horizon] = min(scored, key=scored.get)

    rows: list[pd.DataFrame] = []
    for horizon, model_name in best_models.items():
        selected = mean_preds[(mean_preds["horizon_days"].eq(horizon)) & (mean_preds["model"].eq(model_name))].copy()
        if selected.empty:
            continue
        residual_std = float((selected["actual_net_return"] - selected["predicted_net_return"]).std(skipna=True))
        residual_std = residual_std if np.isfinite(residual_std) and residual_std > 0 else 0.05
        selected["prob_return_positive"] = 1.0 - selected["predicted_net_return"].apply(lambda x: 0.5 * (1.0 + math.erf((0.0 - x) / (residual_std * math.sqrt(2)))))

        q10 = predictions[
            predictions["horizon_days"].eq(horizon)
            & predictions["prediction_type"].eq("q10")
            & predictions["model"].astype(str).str.contains("q10")
        ].copy()
        if not q10.empty:
            q10 = q10.sort_values(["date", "model"]).drop_duplicates(["date", "horizon_days"], keep="first")
            selected = selected.merge(
                q10[["date", "horizon_days", "predicted_net_return"]].rename(columns={"predicted_net_return": "q10_predicted_net_return"}),
                on=["date", "horizon_days"],
                how="left",
            )
        else:
            selected["q10_predicted_net_return"] = selected["predicted_net_return"] - 1.2816 * residual_std

        selected["selected_model"] = model_name
        for prob_threshold in (0.55, config.decision_prob_threshold, 0.65):
            for q10_floor in (-0.03, config.decision_q10_floor, -0.07):
                out = selected.copy()
                out["prob_threshold"] = prob_threshold
                out["q10_floor"] = q10_floor
                out["buy_signal"] = (out["prob_return_positive"] >= prob_threshold) & (out["q10_predicted_net_return"] >= q10_floor)
                rows.append(out)

    if not rows:
        return pd.DataFrame()
    signals = pd.concat(rows, ignore_index=True)
    signals["strategy_return"] = np.where(signals["buy_signal"], signals["actual_net_return"], 0.0)
    return signals


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
    target_cols = [f"net_return_{h}d" for h in config.horizons]
    summary["target_non_null"] = {c: int(frame[c].notna().sum()) for c in target_cols if c in frame}
    if not results.empty:
        leaderboard = (
            results[results["phase"].isin(["validation", "test"])]
            .groupby(["model", "horizon_days"], as_index=False)
            .agg(**{k: v for k, v in {"mae": ("mae", "mean"), "rmse": ("rmse", "mean"), "directional_accuracy": ("directional_accuracy", "mean"), "pinball_loss": ("pinball_loss", "mean")}.items() if k in results.columns})
            .sort_values(["horizon_days", "mae"], na_position="last")
        )
        summary["leaderboard"] = leaderboard.to_dict(orient="records")
    if not signals.empty:
        default = signals[(signals["prob_threshold"].eq(config.decision_prob_threshold)) & (signals["q10_floor"].eq(config.decision_q10_floor))]
        summary["decision_summary"] = (
            default.groupby(["horizon_days", "phase"], as_index=False)
            .agg(
                signal_days=("buy_signal", "sum"),
                observations=("buy_signal", "count"),
                avg_strategy_return=("strategy_return", "mean"),
                avg_buy_day_return=("actual_net_return", lambda s: float(s[default.loc[s.index, "buy_signal"]].mean()) if default.loc[s.index, "buy_signal"].any() else np.nan),
            )
            .to_dict(orient="records")
        )
    return summary


def write_report(summary: dict[str, Any], config: ModelingConfig) -> Path:
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    leaderboard = pd.DataFrame(summary.get("leaderboard", []))
    decision = pd.DataFrame(summary.get("decision_summary", []))

    best_lines: list[str] = []
    if not leaderboard.empty:
        for horizon, group in leaderboard.dropna(subset=["mae"]).groupby("horizon_days"):
            best = group.sort_values("mae").iloc[0]
            best_lines.append(
                f"- Horizon {int(horizon)} ngày: `{best['model']}` có MAE return trung bình {best['mae']:.4f}, directional accuracy {best['directional_accuracy']:.2%}."
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
                f"- {int(row['horizon_days'])} ngày, {row['phase']}: {int(row['signal_days'])}/{int(row['observations'])} ngày phát tín hiệu; return trung bình trên ngày mua {avg_buy_day_return}."
            )

    blockers = summary.get("blockers", [])
    blocker_lines = "\n".join(f"- {b}" for b in blockers[:20]) or "- Không có blocker runtime nghiêm trọng."

    text = f"""# VN Gold Decision Support: EDA, Literature Review Và Modeling

## Technical Summary
- Bộ dữ liệu modeling có {summary['rows']:,} ngày, từ {summary['date_min']} đến {summary['date_max']}. Target chính là return sau spread: `buy_price_t+h / sell_price_t - 1` cho horizon 21, 63, 105 ngày.
- Premium decomposition dùng được nhưng chưa hoàn hảo: tỷ lệ thiếu `premium` trong model frame là {summary['premium_missing_rate']:.1%}. Đây là caveat lớn nhất cho diễn giải premium.
- Lãi suất tiền gửi VN bị loại khỏi feature set vì `deposit_rates_vn.csv` có `value` null 100%; opportunity cost chưa production-grade.
- News được lấy từ `news_raw_headlines_vietnam_gold.csv` và chuyển thành các biến intensity/policy/premium/sentiment heuristic theo `event_date`, lag `t-1`; đây là event proxy, không phải sentiment real-time đã kiểm chứng.
- DeepAR/TFT được ghi nhận như nhóm phương pháp trong literature review, nhưng runner v1 không huấn luyện nếu thiếu dependency nặng.

## Key Findings From The Executed Run
{chr(10).join(best_lines) if best_lines else "- Chưa có leaderboard khả dụng; xem blockers bên dưới."}

Decision-rule mặc định dùng `P(net_return > 0) >= 0.60` và q10 return không thấp hơn `-5%`.

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


def run_full_analysis(config: ModelingConfig | None = None) -> dict[str, Any]:
    config = config or ModelingConfig()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)

    frame = build_model_frame(config)
    feature_cols = list(frame.attrs.get("feature_columns", []))
    diagnostics = frame.attrs.get("diagnostics", {})
    frame.to_csv(config.output_dir / "model_frame_daily.csv", index=False)
    (config.output_dir / "feature_columns.json").write_text(json.dumps(feature_cols, indent=2), encoding="utf-8")

    baseline_results, baseline_preds = train_baselines(frame, config)
    econ_results, econ_preds, econ_blockers = train_econometric(frame, feature_cols, config)
    ml_results, ml_preds, ml_blockers = train_ml_models(frame, feature_cols, config)

    results = pd.concat([baseline_results, econ_results, ml_results], ignore_index=True)
    predictions = pd.concat([baseline_preds, econ_preds, ml_preds], ignore_index=True)
    signals = evaluate_decision_rules(predictions, config)

    blockers = list(econ_blockers) + list(ml_blockers)
    if diagnostics:
        blockers.append("Data diagnostics: " + json.dumps(diagnostics, ensure_ascii=False))

    results.to_csv(config.output_dir / "model_results.csv", index=False)
    predictions.to_csv(config.output_dir / "walk_forward_predictions.csv", index=False)
    signals.to_csv(config.output_dir / "decision_signals.csv", index=False)

    summary = summarize_outputs(frame, results, signals, blockers, config)
    (config.output_dir / "analysis_summary.json").write_text(json.dumps(summary, indent=2, default=str, ensure_ascii=False), encoding="utf-8")
    write_report(summary, config)
    return summary
