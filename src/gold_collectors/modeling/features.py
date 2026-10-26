"""Đọc dữ liệu, ghép theo thời điểm khả dụng và tạo đặc trưng cho mô hình."""

from __future__ import annotations

from pathlib import Path
from datetime import timedelta, timezone
from typing import Any
import numpy as np
import pandas as pd

from .config import (
    ModelingConfig,
)
from .targets import (
    _add_calendar_month_targets,
)


# Đọc bảng nếu tồn tại; trả bảng rỗng để bước ghép xử lý nguồn dữ liệu thiếu.
def _read_csv(path: Path, *, parse_dates: list[str] | None = None) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, parse_dates=parse_dates, low_memory=False)



# Tạo đường dẫn dữ liệu theo cấu hình, hỗ trợ cả data lake thật và bộ dữ liệu kiểm thử.
def _path(config: ModelingConfig, *parts: str) -> Path:
    return config.data_lake.joinpath(*parts)



# Chuẩn hóa ngày để các bảng khác nguồn có thể ghép theo cùng phiên dữ liệu.
def _date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()



# Chuyển các cột hiện có sang số; giá trị không hợp lệ được đánh dấu thiếu.
def _safe_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df



# Chọn báo giá hợp lệ cuối ngày và tính chênh lệch mua/bán cho SJC.
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



# Ghép thị trường quốc tế với độ trễ để tránh dùng thông tin chưa có lúc dự báo.
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



# Ghép chỉ số rủi ro địa chính trị theo ngày khả dụng của nguồn.
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



# Ghép mức chênh giá vàng trong nước so với tham chiếu thế giới.
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



# Chỉ dùng số liệu vĩ mô đã công bố vào ngày dự báo, tránh rò rỉ tương lai.
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



# Ghép lãi suất tiền gửi đã biết để tính chi phí cơ hội của việc nắm giữ vàng.
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

    horizon_to_tenor = {1: 1, 3: 3, 5: 5}
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
        rate_col = f"deposit_rate_{horizon}m_annual_pct"
        ret_col = f"deposit_return_{horizon}m"
        out[rate_col] = merged["rate_pct_annual"].to_numpy()
        # Quy đổi lãi tiền gửi theo đúng số ngày lịch từ ngày mua đến ngày tròn tháng.
        calendar_days = ((out["date"] + pd.DateOffset(months=horizon)) - out["date"]).dt.days
        out[ret_col] = (out[rate_col] / 100.0) * (calendar_days / 365.0)
    return out



# Chọn bảng sự kiện đang có theo thứ tự ưu tiên hiện hành của pipeline.
def _event_path(config: ModelingConfig) -> Path:
    candidates = [
        _path(config, "pipeline_output_event_regime.csv"),
        _path(config, "enriched", "master", "normalized", "event_regime_panel.csv"),
        _path(config, "normalized", "event_regime_panel.csv"),
        _path(config, "gold_event_panel.csv"),
    ]
    return next((p for p in candidates if p.exists()), candidates[0])



# Đưa tác động sự kiện vào đặc trưng ngày theo quy tắc khả dụng hiện có.
def _merge_events(frame: pd.DataFrame, config: ModelingConfig, diagnostics: dict[str, Any] | None = None) -> pd.DataFrame:
    """Chỉ tạo đặc trưng từ lịch biết trước; không dùng chính sách/proxy hồi cứu chưa xác minh."""
    diagnostics = diagnostics if diagnostics is not None else {}
    events = _read_csv(_event_path(config))
    frame = frame.copy()
    diagnostics['event_availability_verified'] = True
    diagnostics['event_features_policy'] = 'known_calendar_only'
    diagnostics['events_input_rows'] = int(len(events))
    # Phải lọc trước groupby/dummies/rolling để tin đã loại không còn ảnh hưởng
    # tới tổng số sự kiện, mức độ nghiêm trọng hoặc các kênh tác động phái sinh.
    if not events.empty:
        kinds = events.get('event_type', pd.Series('', index=events.index)).astype(str).str.lower()
        sources = events.get('source', pd.Series('', index=events.index)).astype(str).str.lower()
        safe = kinds.isin(['tet_proximity', 'than_tai', 'wedding_season']) & sources.isin(['rule_generated', 'calendar'])
        diagnostics['events_excluded_rows'] = int((~safe).sum())
        events = events.loc[safe].copy()
    else:
        diagnostics['events_excluded_rows'] = 0
    diagnostics['events_used_rows'] = int(len(events))
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



# Chỉ ghép tin đáp ứng độ phủ và thời điểm khả dụng; ghi lý do loại nguồn vào chẩn đoán.
def _maybe_merge_news(frame: pd.DataFrame, config: ModelingConfig, diagnostics: dict[str, Any]) -> pd.DataFrame:
    """Dùng tin có bằng chứng ngày thu thập/khả dụng, tuyệt đối không hồi tố ngày đăng."""
    raw_news = _read_csv(_path(config, "news_raw_headlines_vietnam_gold.csv"))
    diagnostics['news_input_rows'] = int(len(raw_news))
    diagnostics['news_used_rows'] = 0
    diagnostics['raw_news_availability_verified'] = True
    required = {'feature_mode_strict', 'availability_from', 'published_at', 'fetched_at'}
    if raw_news.empty or not required.issubset(raw_news.columns):
        diagnostics['news_excluded_rows'] = int(len(raw_news))
        diagnostics['raw_news_modeling_status'] = 'excluded_missing_availability_evidence'
        # Không chuyển sang news_sentiment.csv: bảng fallback chưa có bằng chứng
        # khả dụng cũng có thể tái đưa tin hồi cứu vào huấn luyện.
        return frame
    available = pd.to_datetime(raw_news['availability_from'], errors='coerce', utc=True)
    published = pd.to_datetime(raw_news['published_at'], errors='coerce', utc=True)
    fetched = pd.to_datetime(raw_news['fetched_at'], errors='coerce', utc=True)
    verified = (raw_news['feature_mode_strict'].eq('strict_realtime_verified')
                & available.notna() & published.notna() & fetched.notna()
                & available.ge(published) & available.ge(fetched))
    diagnostics['news_excluded_rows'] = int((~verified).sum())
    raw_news = raw_news.loc[verified].copy()
    # Chuyển ngày khả dụng về giờ Việt Nam rồi dùng trễ một ngày; ngày đăng
    # và ngày event chỉ còn là metadata, không quyết định thời điểm đưa vào model.
    raw_news['news_available_date'] = available.loc[verified].dt.tz_convert(timezone(timedelta(hours=7))).dt.tz_localize(None).dt.normalize()
    raw_news = raw_news.loc[raw_news['news_available_date'] <= frame['date'].max()]
    diagnostics['news_used_rows'] = int(len(raw_news))
    if raw_news.empty:
        diagnostics['raw_news_modeling_status'] = 'excluded_no_verified_available_news'
        return frame
    if not raw_news.empty:
        raw_news = raw_news.copy()
        raw_news["news_event_date"] = raw_news['news_available_date']
        raw_news = raw_news.dropna(subset=["news_event_date"])
        text = (
            raw_news.get("headline", pd.Series("", index=raw_news.index)).fillna("")
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
        # Những ngày không có tin có số đếm bằng 0; tránh giữ nguyên số tin
        # của lần crawl cuối và làm rolling 7/30 thành số ngày có tin thay vì ngày lịch.
        calendar = pd.date_range(daily['news_event_date'].min(), frame['date'].max(), freq='D')
        daily = daily.set_index('news_event_date').reindex(calendar, fill_value=0).rename_axis('news_event_date').reset_index()
        for col in [c for c in daily.columns if c != "news_event_date"]:
            daily[f"{col}_ma7"] = daily[col].rolling(7, min_periods=1).mean()
            daily[f"{col}_ma30"] = daily[col].rolling(30, min_periods=1).mean()

        coverage = raw_news["news_event_date"].nunique() / max(frame["date"].nunique(), 1)
        diagnostics["raw_news_headline_rows"] = int(len(raw_news))
        diagnostics["raw_news_headline_unique_days"] = int(raw_news["news_event_date"].nunique())
        diagnostics["raw_news_headline_coverage"] = float(coverage)
        diagnostics["raw_news_modeling_status"] = "included_verified_availability_asof_lagged"

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

    return frame



# Tạo độ trễ và thống kê quá khứ; danh sách cột đầu ra dùng cho bước huấn luyện.
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
        "deposit_return_1m",
        "deposit_return_3m",
        "deposit_return_5m",
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



# Điều phối ghép đầu vào, tạo nhãn và đặc trưng; trả bảng ngày kèm metadata chẩn đoán.
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
    frame = _merge_events(frame, config, diagnostics)
    frame = _maybe_merge_news(frame, config, diagnostics)
    frame = _add_calendar_month_targets(frame, config.horizons)
    for horizon in config.horizons:
        ret_col = f"deposit_return_{horizon}m"
        target_col = f"net_return_{horizon}m"
        if ret_col in frame.columns and target_col in frame.columns:
            frame[f"gold_excess_return_vs_deposit_{horizon}m"] = frame[target_col] - frame[ret_col]
    frame, feature_cols = _add_lagged_features(frame, config)
    frame.attrs["feature_columns"] = feature_cols
    frame.attrs["diagnostics"] = diagnostics
    return frame.sort_values("date").reset_index(drop=True)
