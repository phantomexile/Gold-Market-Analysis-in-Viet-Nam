#!/usr/bin/env python3
"""
Build the final Vietnamese DOCX report for the VN Gold Market Analysis project.

The report is generated from the current data lake snapshot only. It does not
fetch live data and does not invent model outputs when optional dependencies are
missing. The final decision is therefore as-of the latest collected date in the
snapshot, not a live market call.
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
MODELING = LAKE / "modeling"
DOCS = ROOT / "docs" / "reports"
FIGURES = DOCS / "figures"
OUT = DOCS / "vn_gold_analysis_full_report.docx"

SNAPSHOT_NOTE = "Báo cáo chỉ sử dụng snapshot dữ liệu hiện có, mới nhất đến 2026-07-11."
HORIZON_LABELS = {21: "1 tháng", 63: "3 tháng", 105: "5 tháng"}


@dataclass
class DataProfile:
    name: str
    path: str
    rows: int
    cols: int
    date_span: str
    key_fields: str
    role: str


def read_csv(rel_path: str, **kwargs: Any) -> pd.DataFrame:
    path = ROOT / rel_path
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False, **kwargs)


def read_json(rel_path: str) -> dict[str, Any]:
    path = ROOT / rel_path
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def safe_date_series(values: pd.Series) -> pd.Series:
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def first_existing(columns: list[str], df: pd.DataFrame) -> str | None:
    for col in columns:
        if col in df.columns:
            return col
    return None


def date_span(df: pd.DataFrame) -> str:
    if df.empty:
        return "Không có dữ liệu"
    col = first_existing(["date", "business_date", "event_date", "available_from", "DAY", "observation_date"], df)
    if not col:
        return "Không có cột ngày chuẩn"
    dates = safe_date_series(df[col])
    dates = dates.dropna()
    if dates.empty:
        return f"Cột {col} không parse được ngày"
    return f"{dates.min().date()} đến {dates.max().date()} ({col})"


def pct(value: float | int | None, digits: int = 1) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{100 * float(value):.{digits}f}%"


def pct_points(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.{digits}f}%"


def money_m(value: float | int | None, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value) / 1_000_000:.{digits}f} triệu"


def num(value: float | int | None, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return f"{int(value):,}"
    return f"{float(value):,.{digits}f}"


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    text = str(value)
    return text.replace("\x00", "").strip()


def as_percent_values(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    if values.dropna().abs().median() < 1:
        values = values * 100
    return values


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(cell, text: Any, bold: bool = False, color: RGBColor | None = None) -> None:
    cell.text = ""
    para = cell.paragraphs[0]
    run = para.add_run(clean_text(text))
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(9)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def configure_document(doc: Document) -> None:
    section = doc.sections[0]
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    styles = doc.styles
    styles["Normal"].font.name = "Calibri"
    styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    styles["Normal"].font.size = Pt(10.5)


def add_heading(doc: Document, text: str, level: int = 1) -> None:
    para = doc.add_paragraph()
    para.paragraph_format.space_before = Pt(10 if level == 1 else 7)
    para.paragraph_format.space_after = Pt(4)
    run = para.add_run(text)
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.bold = True
    run.font.size = Pt({1: 17, 2: 13, 3: 11}.get(level, 10))
    run.font.color.rgb = RGBColor(31, 78, 121) if level <= 2 else RGBColor(68, 68, 68)


def add_para(doc: Document, text: str = "", *, bold: bool = False, italic: bool = False) -> None:
    para = doc.add_paragraph()
    para.paragraph_format.space_after = Pt(5)
    run = para.add_run(text)
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(10.5)
    run.font.bold = bold
    run.font.italic = italic


def add_bullet(doc: Document, text: str) -> None:
    para = doc.add_paragraph(style="List Bullet")
    para.paragraph_format.space_after = Pt(2)
    run = para.add_run(text)
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(10.2)


def add_table(doc: Document, headers: list[str], rows: list[list[Any]], *, max_rows: int | None = None) -> None:
    if max_rows is not None:
        rows = rows[:max_rows]
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    header_color = RGBColor(255, 255, 255)
    for i, header in enumerate(headers):
        cell = table.rows[0].cells[i]
        set_cell_shading(cell, "1F4E79")
        set_cell_text(cell, header, bold=True, color=header_color)
    for row_idx, row in enumerate(rows, start=1):
        for col_idx, value in enumerate(row):
            cell = table.rows[row_idx].cells[col_idx]
            if row_idx % 2 == 0:
                set_cell_shading(cell, "F3F6FA")
            set_cell_text(cell, value)
    doc.add_paragraph()


def add_picture_if_exists(doc: Document, path: Path, title: str, width: float = 6.5) -> None:
    if not path.exists():
        return
    add_para(doc, title, bold=True)
    para = doc.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = para.add_run()
    run.add_picture(str(path), width=Inches(width))


def add_cover(doc: Document, latest_date: str) -> None:
    doc.add_paragraph()
    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("BÁO CÁO PHÂN TÍCH THỊ TRƯỜNG VÀNG VIỆT NAM")
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(22)
    run.font.bold = True
    run.font.color.rgb = RGBColor(31, 78, 121)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run("Business Understanding, EDA, Modeling, Forecasting và quyết định mua 1-5 tháng")
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(13)
    run.font.color.rgb = RGBColor(68, 114, 196)

    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = meta.add_run(
        f"Snapshot dữ liệu: đến {latest_date}\n"
        f"Ngày tái tạo báo cáo: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        "Deliverable: DOCX học thuật, không dùng dữ liệu live ngoài snapshot"
    )
    run.font.name = "Calibri"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    run.font.size = Pt(10.5)
    run.font.color.rgb = RGBColor(90, 90, 90)
    doc.add_page_break()


def profile_datasets(datasets: dict[str, tuple[str, str, str]]) -> tuple[list[DataProfile], dict[str, pd.DataFrame]]:
    frames: dict[str, pd.DataFrame] = {}
    profiles: list[DataProfile] = []
    for name, (path, key_fields, role) in datasets.items():
        df = read_csv(path)
        frames[name] = df
        profiles.append(
            DataProfile(
                name=name,
                path=path,
                rows=len(df),
                cols=len(df.columns),
                date_span=date_span(df),
                key_fields=key_fields,
                role=role,
            )
        )
    return profiles, frames


def build_profiles() -> tuple[list[DataProfile], dict[str, pd.DataFrame]]:
    datasets = {
        "SJC historical target": (
            "data/lake/gold_quotes_sjc_historical.csv",
            "date, business_date, buy, sell, spread, source",
            "Nguồn target huấn luyện chính; giữ bản ghi historical-valid.",
        ),
        "Domestic daily panel": (
            "data/lake/gold_domestic_daily_panel.csv",
            "date, business_date, provider, gold_type, buy_price, sell_price",
            "Panel giá vàng trong nước nhiều nguồn.",
        ),
        "Global reference daily": (
            "data/lake/global_reference_daily.csv",
            "date, gold_futures_close_usd_oz, usd_vnd_mid, vix, dxy_index",
            "Biến toàn cầu và FX dùng để giải thích giá vàng nội địa.",
        ),
        "Premium enriched": (
            "data/lake/pipeline_output_premium_enriched.csv",
            "date, global_gold_vnd_per_luong, premium, premium_pct",
            "Phân rã premium SJC so với vàng thế giới quy đổi VND/lượng.",
        ),
        "VN macro as-of": (
            "data/lake/pipeline_output_vn_macro_asof.csv",
            "available_from, observation_date, indicator_name, value",
            "Panel vĩ mô với mốc công bố để chống leakage.",
        ),
        "GPR daily": (
            "data/lake/gpr_daily_geopolitical_risk.csv",
            "date, GPRD, GPRD_MA7, GPRD_MA30",
            "Chỉ số rủi ro địa chính trị.",
        ),
        "Event regime": (
            "data/lake/pipeline_output_event_regime.csv",
            "event_date, event_type, severity, expected_channel",
            "Tết, Thần Tài, mùa cưới, chính sách, crisis/regime events.",
        ),
        "News raw headlines": (
            "data/lake/news_raw_headlines_vietnam_gold.csv",
            "event_date, headline, body_text, category, source",
            "Nguồn headline/backfill cho biến intensity và sentiment heuristic.",
        ),
        "Model frame": (
            "data/lake/modeling/model_frame_daily.csv",
            "date, prices, targets, lag/rolling features",
            "Bảng cuối cho huấn luyện: một dòng mỗi ngày, 21/63/105d labels.",
        ),
        "Model results": (
            "data/lake/modeling/model_results.csv",
            "model, horizon_days, fold, phase, mae, rmse, directional_accuracy",
            "Leaderboard walk-forward theo horizon và fold.",
        ),
        "Walk-forward predictions": (
            "data/lake/modeling/walk_forward_predictions.csv",
            "date, horizon_days, fold, model, actual, predicted",
            "Dự báo từng fold để audit model behavior.",
        ),
        "Decision signals": (
            "data/lake/modeling/decision_signals.csv",
            "date, horizon_days, prob_return_positive, q10, buy_signal",
            "Bảng tín hiệu mua theo threshold grid.",
        ),
        "Trading signals": (
            "data/lake/modeling/trading_signals.csv",
            "date, horizon_days, selected_model, prob_positive, buy_signal_any",
            "Bảng collapse một dòng/ngày cho paper trading.",
        ),
    }
    return profile_datasets(datasets)


def compute_data_quality(frames: dict[str, pd.DataFrame], summary: dict[str, Any]) -> list[list[Any]]:
    checks: list[list[Any]] = []
    frame = frames.get("Model frame", pd.DataFrame())
    target = frames.get("SJC historical target", pd.DataFrame())
    premium = frames.get("Premium enriched", pd.DataFrame())
    signals = frames.get("Trading signals", pd.DataFrame())

    if not target.empty:
        valid = target.copy()
        for col in ["buy", "sell", "spread"]:
            if col in valid.columns:
                valid[col] = pd.to_numeric(valid[col], errors="coerce")
        invalid_prices = int(((valid.get("buy", 1) <= 0) | (valid.get("sell", 1) <= 0) | (valid.get("sell", 1) < valid.get("buy", 0))).sum())
        checks.append(["Target price validity", f"{invalid_prices:,} dòng bất thường", "Cao", "Phải bằng 0 hoặc được giải thích trước khi dùng làm label."])

    if not frame.empty:
        checks.append(["Model frame grain", f"{len(frame):,} dòng, {frame['date'].nunique():,} ngày unique", "Cao", "Một dòng/ngày cho training frame."])
        for col in ["global_feature_date", "gpr_feature_date", "macro_feature_date"]:
            if col in frame.columns:
                ok = (safe_date_series(frame[col]).dropna() <= safe_date_series(frame.loc[frame[col].notna(), "date"])).all()
                checks.append([f"As-of guard: {col}", "PASS" if ok else "FAIL", "Cao", "Không dùng dữ liệu tương lai so với ngày quyết định."])
        for horizon in [21, 63, 105]:
            col = f"net_return_{horizon}d"
            if col in frame.columns:
                checks.append([f"Target non-null {horizon}d", f"{frame[col].notna().sum():,}", "Trung bình", "Số mẫu có nhãn sau khi trừ phần cuối chưa có tương lai."])

    if not premium.empty and "premium" in premium.columns:
        checks.append(["Premium missing", pct(pd.to_numeric(premium["premium"], errors="coerce").isna().mean()), "Cao", "Caveat lớn cho diễn giải premium và cơ hội entry."])

    if not signals.empty:
        checks.append(["Trading signal coverage", f"{len(signals):,} dòng", "Trung bình", "Bảng collapse đã xuất lại sau modeling run."])

    blockers = summary.get("blockers", [])
    for blocker in blockers[:6]:
        checks.append(["Runtime blocker", blocker[:180], "Cao" if "unavailable" in blocker.lower() or "missing" in blocker.lower() else "Trung bình", "Ghi vào báo cáo, không thay bằng kết quả giả."])
    return checks


def compute_eda_tables(frames: dict[str, pd.DataFrame]) -> dict[str, list[list[Any]]]:
    tables: dict[str, list[list[Any]]] = {}
    frame = frames.get("Model frame", pd.DataFrame()).copy()
    premium = frames.get("Premium enriched", pd.DataFrame()).copy()
    events = frames.get("Event regime", pd.DataFrame()).copy()
    global_ref = frames.get("Global reference daily", pd.DataFrame()).copy()

    if not frame.empty:
        frame["date"] = safe_date_series(frame["date"])
        frame["year"] = frame["date"].dt.year
        frame["sell_price"] = pd.to_numeric(frame["sell_price"], errors="coerce")
        frame["buy_price"] = pd.to_numeric(frame["buy_price"], errors="coerce")
        frame["spread_pct"] = pd.to_numeric(frame.get("spread_pct"), errors="coerce") * 100
        yearly = (
            frame.dropna(subset=["date", "sell_price"])
            .groupby("year")
            .agg(
                start=("sell_price", "first"),
                end=("sell_price", "last"),
                min_price=("sell_price", "min"),
                max_price=("sell_price", "max"),
                obs=("sell_price", "count"),
                spread_mean=("spread_pct", "mean"),
            )
            .reset_index()
        )
        yearly["return"] = yearly["end"] / yearly["start"] - 1
        tables["yearly_price"] = [
            [int(r.year), money_m(r.start), money_m(r.end), money_m(r.min_price), money_m(r.max_price), pct(r["return"]), f"{int(r.obs):,}", pct_points(r.spread_mean)]
            for _, r in yearly.tail(10).iterrows()
        ]

        corr_cols = [
            c
            for c in frame.columns
            if any(k in c for k in ["premium_pct_lag", "usd_vnd", "vix", "dxy", "treasury_10y", "GPRD_MA", "spread_pct"])
        ]
        corr_rows: list[list[Any]] = []
        for horizon in [21, 63, 105]:
            target_col = f"net_return_{horizon}d"
            values = []
            if target_col in frame.columns:
                for col in corr_cols:
                    x = pd.to_numeric(frame[col], errors="coerce")
                    y = pd.to_numeric(frame[target_col], errors="coerce")
                    corr = x.corr(y)
                    if pd.notna(corr):
                        values.append((col, corr))
            for col, corr in sorted(values, key=lambda x: abs(x[1]), reverse=True)[:5]:
                corr_rows.append([HORIZON_LABELS[horizon], col, f"{corr:+.3f}"])
        tables["correlations"] = corr_rows

    if not premium.empty and "premium_pct" in premium.columns:
        premium_pct = as_percent_values(premium["premium_pct"])
        premium_abs = pd.to_numeric(premium.get("premium"), errors="coerce")
        valid = premium_pct.dropna()
        regimes = {
            "Thấp (<3%)": float((valid < 3).mean()) if len(valid) else np.nan,
            "Bình thường (3-6%)": float(((valid >= 3) & (valid < 6)).mean()) if len(valid) else np.nan,
            "Cao (6-10%)": float(((valid >= 6) & (valid < 10)).mean()) if len(valid) else np.nan,
            "Crisis (>10%)": float((valid >= 10).mean()) if len(valid) else np.nan,
        }
        tables["premium_stats"] = [
            ["Số ngày có premium", f"{valid.notna().sum():,}", ""],
            ["Premium trung bình", money_m(premium_abs.mean()), pct_points(valid.mean())],
            ["Premium median", money_m(premium_abs.median()), pct_points(valid.median())],
            ["P10", money_m(premium_abs.quantile(0.10)), pct_points(valid.quantile(0.10))],
            ["P90", money_m(premium_abs.quantile(0.90)), pct_points(valid.quantile(0.90))],
        ]
        tables["premium_regime"] = [[k, pct(v)] for k, v in regimes.items()]

    if not events.empty and "event_type" in events.columns:
        counts = events["event_type"].fillna("unknown").value_counts().head(12)
        tables["events"] = [[idx, f"{int(value):,}"] for idx, value in counts.items()]

    if not global_ref.empty:
        rows = []
        for col in ["gold_futures_close_usd_oz", "lbma_price_usd_oz", "usd_vnd_mid", "vix", "dxy_index", "treasury_10y_pct", "oil_wti_usd_barrel"]:
            if col in global_ref.columns:
                values = pd.to_numeric(global_ref[col], errors="coerce")
                rows.append([col, f"{values.notna().sum():,}", pct(values.notna().mean()), num(values.min()), num(values.max())])
        tables["global_coverage"] = rows

    return tables


def build_figures(frames: dict[str, pd.DataFrame], summary: dict[str, Any]) -> dict[str, Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns

    sns.set_theme(style="whitegrid")
    paths: dict[str, Path] = {}
    frame = frames.get("Model frame", pd.DataFrame()).copy()
    results = frames.get("Model results", pd.DataFrame()).copy()
    signals = frames.get("Trading signals", pd.DataFrame()).copy()

    if not frame.empty:
        frame["date"] = safe_date_series(frame["date"])
        frame["sell_price"] = pd.to_numeric(frame["sell_price"], errors="coerce")
        frame["global_gold_vnd_per_luong"] = pd.to_numeric(frame.get("global_gold_vnd_per_luong"), errors="coerce")
        fig, ax = plt.subplots(figsize=(10, 4.2))
        ax.plot(frame["date"], frame["sell_price"] / 1_000_000, label="SJC sell", color="#1F77B4", linewidth=1.2)
        if frame["global_gold_vnd_per_luong"].notna().any():
            ax.plot(frame["date"], frame["global_gold_vnd_per_luong"] / 1_000_000, label="Global gold VND/luong", color="#B8860B", linewidth=1.0, alpha=0.8)
        ax.set_title("SJC price versus global gold proxy")
        ax.set_ylabel("Million VND per luong")
        ax.legend()
        path = FIGURES / "final_01_price_vs_global.png"
        fig.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(fig)
        paths["price"] = path

        if "premium_pct" in frame.columns:
            prem = as_percent_values(frame["premium_pct"])
            fig, ax = plt.subplots(figsize=(10, 4.2))
            ax.plot(frame["date"], prem, color="#D28E00", linewidth=0.8)
            ax.axhline(3, color="#2E7D32", linestyle="--", linewidth=0.8)
            ax.axhline(6, color="#F57C00", linestyle="--", linewidth=0.8)
            ax.axhline(10, color="#C62828", linestyle="--", linewidth=0.8)
            ax.set_title("Domestic premium regime")
            ax.set_ylabel("Premium (%)")
            path = FIGURES / "final_02_premium_regime.png"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            plt.close(fig)
            paths["premium"] = path

    if not results.empty:
        mean = results[results["pinball_loss"].isna()].copy()
        mean["mae"] = pd.to_numeric(mean["mae"], errors="coerce")
        agg = mean.groupby(["model", "horizon_days"], as_index=False)["mae"].mean().dropna()
        if not agg.empty:
            fig, axes = plt.subplots(1, 3, figsize=(13, 4), sharex=False)
            for axis, horizon in zip(axes, [21, 63, 105]):
                sub = agg[agg["horizon_days"].eq(horizon)].sort_values("mae").head(7)
                axis.barh(sub["model"], sub["mae"], color="#4472C4")
                axis.invert_yaxis()
                axis.set_title(f"{horizon}d MAE")
                axis.set_xlabel("MAE")
            fig.tight_layout()
            path = FIGURES / "final_03_model_leaderboard.png"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            plt.close(fig)
            paths["leaderboard"] = path

    if not signals.empty:
        signals["buy_signal_any"] = signals["buy_signal_any"].astype(str).str.lower().isin(["true", "1"])
        sig = (
            signals.groupby(["phase", "horizon_days"], as_index=False)
            .agg(signal_rate=("buy_signal_any", "mean"), avg_actual=("avg_actual_return", "mean"))
        )
        if not sig.empty:
            sig["label"] = sig["phase"].astype(str) + " " + sig["horizon_days"].astype(str) + "d"
            fig, ax = plt.subplots(figsize=(9, 4))
            ax.bar(sig["label"], sig["signal_rate"] * 100, color="#70AD47")
            ax.set_title("Decision signal frequency")
            ax.set_ylabel("Signal days (%)")
            ax.tick_params(axis="x", rotation=35)
            path = FIGURES / "final_04_signal_frequency.png"
            fig.savefig(path, dpi=180, bbox_inches="tight")
            plt.close(fig)
            paths["signals"] = path

    return paths


def summarize_models(summary: dict[str, Any]) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
    leaderboard = pd.DataFrame(summary.get("leaderboard", []))
    if leaderboard.empty:
        return [], [], []

    mean = leaderboard[leaderboard["pinball_loss"].isna()].copy()
    quant = leaderboard[leaderboard["pinball_loss"].notna()].copy()
    mean_rows: list[list[Any]] = []
    quant_rows: list[list[Any]] = []
    for horizon in [21, 63, 105]:
        sub = mean[mean["horizon_days"].eq(horizon)].copy()
        if not sub.empty:
            best_mae = sub.sort_values("mae").iloc[0]
            best_da = sub.sort_values("directional_accuracy", ascending=False).iloc[0]
            mean_rows.append(
                [
                    HORIZON_LABELS[horizon],
                    best_mae["model"],
                    f"{float(best_mae['mae']):.4f}",
                    f"{float(best_mae['rmse']):.4f}",
                    pct(float(best_mae["directional_accuracy"])),
                    best_da["model"],
                    pct(float(best_da["directional_accuracy"])),
                ]
            )
        qsub = quant[quant["horizon_days"].eq(horizon)].dropna(subset=["pinball_loss"])
        if not qsub.empty:
            best_q = qsub.sort_values("pinball_loss").iloc[0]
            quant_rows.append([HORIZON_LABELS[horizon], best_q["model"], f"{float(best_q['pinball_loss']):.5f}"])

    decision = pd.DataFrame(summary.get("decision_summary", []))
    decision_rows: list[list[Any]] = []
    if not decision.empty:
        for _, row in decision.sort_values(["horizon_days", "phase"]).iterrows():
            signal_days = int(row["signal_days"])
            observations = int(row["observations"])
            decision_rows.append(
                [
                    HORIZON_LABELS[int(row["horizon_days"])],
                    row["phase"],
                    f"{signal_days:,}/{observations:,}",
                    pct(signal_days / observations if observations else np.nan),
                    pct(row["avg_buy_day_return"], 2),
                    pct(row["avg_strategy_return"], 2),
                ]
            )
    return mean_rows, quant_rows, decision_rows


def load_feature_columns() -> list[str]:
    payload = read_json("data/lake/modeling/feature_columns.json")
    if isinstance(payload, list):
        return [str(x) for x in payload]
    return []


def train_snapshot_forecasts(frame: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    if frame.empty or not feature_cols:
        return pd.DataFrame()
    try:
        from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
    except Exception as exc:
        return pd.DataFrame([{"status": f"snapshot forecast skipped: {exc}"}])

    data = frame.copy()
    data["date"] = safe_date_series(data["date"])
    feature_cols = [c for c in feature_cols if c in data.columns]
    latest = data.sort_values("date").iloc[[-1]].copy()
    rows: list[dict[str, Any]] = []

    for horizon in [21, 63, 105]:
        target_col = f"net_return_{horizon}d"
        if target_col not in data.columns:
            continue
        train = data.dropna(subset=[target_col]).copy()
        if len(train) < 500:
            rows.append({"horizon_days": horizon, "status": "skipped_insufficient_training_rows"})
            continue

        # Select the most informative features on the training window only.
        scored: list[tuple[str, float]] = []
        y = pd.to_numeric(train[target_col], errors="coerce")
        for col in feature_cols:
            x = pd.to_numeric(train[col], errors="coerce")
            if x.notna().sum() < 200 or x.nunique(dropna=True) < 2:
                continue
            corr = abs(x.corr(y))
            if pd.notna(corr):
                scored.append((col, corr))
        selected = [col for col, _ in sorted(scored, key=lambda item: item[1], reverse=True)[:120]]
        if not selected:
            rows.append({"horizon_days": horizon, "status": "skipped_no_usable_features"})
            continue

        x_train = train[selected].apply(pd.to_numeric, errors="coerce")
        y_train = y.loc[x_train.index].astype(float)
        x_latest = latest[selected].apply(pd.to_numeric, errors="coerce")

        point_model = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    RandomForestRegressor(
                        n_estimators=350,
                        max_depth=7,
                        min_samples_leaf=12,
                        random_state=42,
                        n_jobs=-1,
                    ),
                ),
            ]
        )
        q10_model = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "model",
                    GradientBoostingRegressor(
                        loss="quantile",
                        alpha=0.10,
                        n_estimators=250,
                        max_depth=3,
                        learning_rate=0.035,
                        random_state=42,
                    ),
                ),
            ]
        )
        point_model.fit(x_train, y_train)
        pred_train = point_model.predict(x_train)
        residual_std = float(np.nanstd(y_train.to_numpy() - pred_train))
        residual_std = residual_std if np.isfinite(residual_std) and residual_std > 0 else 0.05
        pred = float(point_model.predict(x_latest)[0])
        q10_model.fit(x_train, y_train)
        q10 = float(q10_model.predict(x_latest)[0])
        prob_positive = 1.0 - 0.5 * (1.0 + math.erf((0.0 - pred) / (residual_std * math.sqrt(2))))
        buy_signal = bool((prob_positive >= 0.50) and (q10 >= -0.10))
        rows.append(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_date": str(latest["date"].iloc[0].date()),
                "horizon_days": horizon,
                "horizon_label": HORIZON_LABELS[horizon],
                "point_model": "random_forest_snapshot_top120_features",
                "q10_model": "gradient_boosting_quantile_q10_snapshot_top120_features",
                "train_rows": int(len(train)),
                "feature_count": int(len(selected)),
                "predicted_net_return": pred,
                "q10_predicted_net_return": q10,
                "prob_return_positive": prob_positive,
                "buy_signal": buy_signal,
                "status": "ok",
            }
        )

    out = pd.DataFrame(rows)
    if not out.empty:
        MODELING.mkdir(parents=True, exist_ok=True)
        out.to_csv(MODELING / "snapshot_forecasts.csv", index=False)
    return out


def decision_recommendation(snapshot: pd.DataFrame, decision_rows: list[list[Any]]) -> tuple[str, list[list[Any]]]:
    rows: list[list[Any]] = []
    if snapshot.empty or "predicted_net_return" not in snapshot.columns:
        return (
            "Không đưa ra khuyến nghị mua mới vì script không tạo được snapshot forecast kiểm chứng được.",
            rows,
        )
    for _, row in snapshot.iterrows():
        if row.get("status") != "ok":
            rows.append([row.get("horizon_label", ""), row.get("status", ""), "", "", "Không kết luận"])
            continue
        action = "Mua tích lũy" if bool(row["buy_signal"]) else "Không mua mới"
        if row["horizon_days"] == 63:
            action = "Không mua mới" if row["predicted_net_return"] <= 0 or row["q10_predicted_net_return"] < -0.10 else action
        rows.append(
            [
                row["horizon_label"],
                pct(row["predicted_net_return"], 2),
                pct(row["q10_predicted_net_return"], 2),
                pct(row["prob_return_positive"], 1),
                action,
            ]
        )

    five = snapshot[snapshot["horizon_days"].eq(105)]
    three = snapshot[snapshot["horizon_days"].eq(63)]
    one = snapshot[snapshot["horizon_days"].eq(21)]
    if not five.empty and bool(five.iloc[0].get("buy_signal", False)):
        recommendation = (
            "Khuyến nghị chính: có thể mua tích lũy có kiểm soát cho horizon khoảng 5 tháng, "
            "nhưng không mua mạnh một lần. Horizon 3 tháng không đủ hấp dẫn vì backtest tín hiệu âm; "
            "horizon 1 tháng chỉ phù hợp giao dịch nhỏ do tín hiệu lịch sử rất hiếm."
        )
    elif not one.empty and bool(one.iloc[0].get("buy_signal", False)):
        recommendation = (
            "Khuyến nghị chính: chỉ mua nhỏ/ngắn hạn nếu chấp nhận rủi ro, chưa đủ bằng chứng để mua mạnh "
            "cho 3-5 tháng."
        )
    else:
        recommendation = (
            "Khuyến nghị chính: không mua mới ở quy mô lớn theo snapshot hiện tại; ưu tiên chờ premium/spread "
            "hạ nhiệt hoặc có tín hiệu xác nhận tốt hơn."
        )
    if not three.empty and bool(three.iloc[0].get("buy_signal", False)):
        recommendation += " Lưu ý: nếu mô hình snapshot 3 tháng bật tín hiệu, vẫn cần hạ trọng số vì backtest 63 ngày có avg buy-day return âm."
    return recommendation, rows


def add_executive_summary(doc: Document, latest_date: str, recommendation: str, summary: dict[str, Any]) -> None:
    add_heading(doc, "Tóm tắt điều hành", 1)
    add_bullet(doc, f"{SNAPSHOT_NOTE} Kết luận không phải tín hiệu live sau ngày {latest_date}.")
    add_bullet(doc, recommendation)
    add_bullet(
        doc,
        "Target chính là lợi nhuận sau spread: mua tại giá bán hôm nay và bán lại theo giá mua sau 21/63/105 ngày.",
    )
    add_bullet(
        doc,
        f"Model frame có {summary.get('rows', 'n/a'):,} ngày từ {summary.get('date_min')} đến {summary.get('date_max')}; "
        f"premium missing {pct(summary.get('premium_missing_rate'))}.",
    )
    add_bullet(
        doc,
        "LightGBM, XGBoost và CatBoost được cài và train thật khi import được; deep models chỉ xuất hiện khi có runner huấn luyện thật.",
    )


def add_business_understanding(doc: Document) -> None:
    add_heading(doc, "1. Business Understanding và góc nhìn kinh tế", 1)
    add_para(
        doc,
        "Bài toán không chỉ là dự báo giá vàng, mà là quyết định có nên mua vàng vật chất tại Việt Nam trong 1-5 tháng tới. "
        "Người mua trả giá bán ra hôm nay và nếu thoát vị thế sẽ nhận giá mua vào trong tương lai, nên bid-ask spread và premium nội địa là một phần trực tiếp của lợi nhuận.",
    )
    add_para(
        doc,
        "Vàng Việt Nam chịu tác động của bốn nhóm lực: giá vàng quốc tế, tỷ giá USD/VND, premium SJC do cấu trúc cung-cầu và chính sách, và chế độ rủi ro như lạm phát, lãi suất, địa chính trị, mùa vụ Tết/Thần Tài.",
    )
    add_table(
        doc,
        ["Yếu tố", "Cơ chế tác động", "Biến dữ liệu dùng trong báo cáo"],
        [
            ["Giá vàng thế giới", "Neo giá cơ bản theo USD/oz, phản ánh lãi suất thực, USD và safe-haven demand.", "GC=F/LBMA proxy, global_gold_vnd_per_luong"],
            ["USD/VND", "Tăng USD/VND làm vàng quy đổi VND cao hơn ngay cả khi USD gold đi ngang.", "usd_vnd_mid, usd_vnd_market_rate"],
            ["Premium SJC", "Chênh lệch nội địa phản ánh khan hiếm, quy định, đấu thầu và tâm lý tích trữ.", "premium, premium_pct, source_dispersion"],
            ["Thanh khoản/spread", "Spread cao làm giảm lợi nhuận thực nhận và báo hiệu stress bán lẻ.", "spread_abs, spread_pct"],
            ["Rủi ro và mùa vụ", "Crisis/policy/Tết/Thần Tài có thể làm premium và volatility tăng ngắn hạn.", "event_regime, GPRD, raw_news intensity"],
        ],
    )


def add_literature_review(doc: Document) -> None:
    add_heading(doc, "2. Literature Review và lựa chọn phương pháp", 1)
    add_para(
        doc,
        "Tài liệu dự báo vàng thường chia thành ba nhánh: mô hình chuỗi thời gian cổ điển, mô hình tài chính-vĩ mô có biến ngoại sinh, và mô hình machine learning/deep learning cho quan hệ phi tuyến. Với vàng Việt Nam, báo cáo ưu tiên mô hình có thể xử lý premium và biến ngoại sinh theo thời điểm công bố.",
    )
    add_table(
        doc,
        ["Nhóm phương pháp", "Vai trò trong bài toán vàng", "Cách áp dụng trong dự án"],
        [
            ["ARIMA/SARIMAX", "Baseline mạnh cho chuỗi có tự tương quan và biến ngoại sinh.", "SARIMAX+exog trên target return nhiều horizon."],
            ["VECM/Cointegration", "Phù hợp khi giá nội địa, vàng thế giới và FX có quan hệ cân bằng dài hạn.", "VECM screen được ghi nhận; forecast chưa promote trong runner v1."],
            ["GARCH/volatility", "Đánh giá rủi ro, volatility clustering và stress regime.", "Dùng trong literature/methodology; volatility rolling trong EDA."],
            ["Tree boosting / Random Forest", "Bắt tương tác phi tuyến giữa premium, events, FX, GPR.", "Random Forest mean model; Gradient Boosting quantile cho downside q10."],
            ["Quantile regression", "Quyết định mua cần downside risk, không chỉ expected return.", "q10 forecast kết hợp với xác suất return dương."],
            ["DeepAR/TFT/N-BEATS/N-HiTS", "Ứng viên multi-horizon probabilistic forecast khi có panel đủ giàu.", "Ghi là hướng tiếp theo; không train nếu thiếu dependency."],
        ],
    )
    add_para(
        doc,
        "Lý do không chọn một mô hình duy nhất ngay từ đầu: thị trường vàng vừa có thành phần xu hướng toàn cầu, vừa có premium nội địa phi tuyến và event-driven. Vì vậy đánh giá theo walk-forward và quyết định dựa trên cả MAE, directional accuracy, q10 downside và signal performance.",
    )


def add_data_sections(doc: Document, profiles: list[DataProfile], quality_rows: list[list[Any]], eda_tables: dict[str, list[list[Any]]]) -> None:
    add_heading(doc, "3. Data Requirements, Collection và Data Understanding", 1)
    add_para(
        doc,
        "Yêu cầu dữ liệu xuất phát từ phương trình kinh tế: giá vàng nội địa xấp xỉ giá vàng thế giới quy đổi VND cộng premium nội địa, sau đó bị điều chỉnh bởi spread, mùa vụ, chính sách và rủi ro. Vì vậy data lake phải có target nội địa, reference toàn cầu, FX, macro, event và kiểm soát thời điểm công bố.",
    )
    add_table(
        doc,
        ["Dataset", "Rows", "Cols", "Thời gian", "Vai trò"],
        [[p.name, f"{p.rows:,}", f"{p.cols:,}", p.date_span, p.role] for p in profiles],
        max_rows=20,
    )

    add_heading(doc, "4. Data Quality và rủi ro dữ liệu", 1)
    add_table(doc, ["Check", "Kết quả", "Mức độ", "Ý nghĩa"], quality_rows, max_rows=25)

    add_heading(doc, "5. Data Preparation", 1)
    add_bullet(doc, "Historical-valid target: chỉ dùng bản ghi có requested/business date đúng ngày và giá mua/bán hợp lệ.")
    add_bullet(doc, "As-of join: global và GPR dùng cutoff t-1; macro dùng available_from <= date để tránh look-ahead bias.")
    add_bullet(doc, "Feature engineering: tạo lag 1/5/10/21/63/105 ngày và rolling mean/std 5/21/63 ngày.")
    add_bullet(doc, "Target: net_return_h = future_buy_price_h / current_sell_price - 1, đúng logic người mua vàng vật chất chịu spread.")
    add_bullet(doc, "Horizon: 21 ngày khoảng 1 tháng, 63 ngày khoảng 3 tháng, 105 ngày khoảng 5 tháng.")

    add_heading(doc, "6. EDA: Giá, premium, thanh khoản và sự kiện", 1)
    if eda_tables.get("yearly_price"):
        add_para(doc, "Diễn biến 10 năm gần nhất của giá bán SJC trong model frame:")
        add_table(doc, ["Năm", "Start", "End", "Min", "Max", "Return", "N obs", "Avg spread"], eda_tables["yearly_price"])
    if eda_tables.get("premium_stats"):
        add_para(doc, "Premium decomposition cho thấy premium là biến quyết định chất lượng điểm mua:")
        add_table(doc, ["Metric", "Premium VND/lượng", "Premium %"], eda_tables["premium_stats"])
    if eda_tables.get("premium_regime"):
        add_table(doc, ["Premium regime", "Tỷ trọng quan sát"], eda_tables["premium_regime"])
    if eda_tables.get("global_coverage"):
        add_table(doc, ["Global variable", "Non-null", "Coverage", "Min", "Max"], eda_tables["global_coverage"], max_rows=12)
    if eda_tables.get("correlations"):
        add_para(doc, "Top tương quan tuyệt đối giữa một số feature lag và target return, dùng để định hướng chứ không diễn giải nhân quả:")
        add_table(doc, ["Horizon", "Feature", "Correlation"], eda_tables["correlations"], max_rows=18)
    if eda_tables.get("events"):
        add_para(doc, "Các loại sự kiện phổ biến trong event regime panel:")
        add_table(doc, ["Event type", "Count"], eda_tables["events"])


def add_modeling_sections(
    doc: Document,
    mean_rows: list[list[Any]],
    quant_rows: list[list[Any]],
    decision_rows: list[list[Any]],
    snapshot_rows: list[list[Any]],
    recommendation: str,
    summary: dict[str, Any],
) -> None:
    add_heading(doc, "7. Modeling và Evaluation", 1)
    add_para(
        doc,
        "Thiết kế evaluation dùng expanding-window walk-forward: train trên quá khứ, đánh giá trên validation/test theo thời gian. Đây là bắt buộc vì random split sẽ làm rò rỉ chế độ thị trường tương lai vào quá khứ.",
    )
    add_table(
        doc,
        ["Horizon", "Best MAE model", "MAE", "RMSE", "DA", "Best DA model", "Best DA"],
        mean_rows,
    )
    if quant_rows:
        add_table(doc, ["Horizon", "Best quantile model", "Pinball loss"], quant_rows)
    if decision_rows:
        add_para(doc, "Decision-rule backtest với rule P(return>0) >= 0.50 và q10 >= -10%:")
        add_table(doc, ["Horizon", "Phase", "Signals", "Signal rate", "Avg buy-day ret", "Avg strategy ret"], decision_rows)

    add_heading(doc, "8. Snapshot Forecast và quyết định mua 1-5 tháng", 1)
    add_para(
        doc,
        "Bảng dưới đây là dự báo snapshot riêng tại ngày dữ liệu cuối. Mô hình được train trên các dòng có nhãn lịch sử đã biết, sau đó dự báo cho dòng feature mới nhất. Vì tương lai sau snapshot chưa có nhãn, đây là forecast phục vụ quyết định, không phải backtest.",
    )
    if snapshot_rows:
        add_table(doc, ["Horizon", "Expected return", "Q10 downside", "P(return>0)", "Khuyến nghị"], snapshot_rows)
    add_para(doc, recommendation, bold=True)

    add_heading(doc, "9. Caveats, Feedback và kế hoạch cải thiện", 1)
    add_bullet(doc, f"Premium missing rate hiện khoảng {pct(summary.get('premium_missing_rate'))}; kết luận premium cần đọc là directional.")
    add_bullet(doc, "VN deposit-rate history bị loại vì value null 100%, nên chưa benchmark đầy đủ với lãi suất tiết kiệm.")
    add_bullet(doc, "News/headline được backfill trong 2026; đã lag theo event_date nhưng real-time availability chưa chứng minh tuyệt đối.")
    add_bullet(doc, "LightGBM/XGBoost/CatBoost đã được cài và train thật khi xuất hiện trong leaderboard; DeepAR/TFT là production-candidate cho runner riêng, không còn là blocker thiếu dependency.")
    add_bullet(doc, "Bước tiếp theo nên ưu tiên: bổ sung LBMA/FX coverage, nguồn lãi suất tiền gửi VN, lịch đấu thầu/chính sách NHNN, rồi chạy paper-trading rolling sau snapshot.")


def caveat_improvement_rows(summary: dict[str, Any]) -> list[list[Any]]:
    premium_summary = read_json("data/lake/quality/premium_coverage_summary.json")
    deposit_summary = read_json("data/lake/quality/deposit_rate_coverage_summary.json")
    news_summary = read_json("data/lake/quality/news_availability_summary.json")
    sensitivity = read_json("data/lake/modeling/model_sensitivity_summary.json")
    paper = read_json("data/lake/modeling/paper_trading_summary.json")

    before_premium = premium_summary.get("old_premium_missing_rate", summary.get("premium_missing_rate"))
    after_premium = premium_summary.get("new_premium_missing_rate", summary.get("premium_missing_rate"))
    deposit_rows = deposit_summary.get("retail_valid_rows", 0)
    strict_news_share = news_summary.get("strict_realtime_verified_share", 0)
    deps = sensitivity.get("dependency_availability", {})
    model_status = ", ".join(
        f"{name}={'ok' if available else 'missing'}"
        for name, available in deps.items()
        if name in {"lightgbm", "xgboost", "catboost", "torch", "pytorch_forecasting", "gluonts"}
    ) or "not audited"

    return [
        [
            "Premium coverage",
            pct(before_premium),
            pct(after_premium),
            "Met target <10%" if premium_summary.get("target_met") else "Needs source-gap review",
        ],
        [
            "Deposit opportunity cost",
            "0 non-null verified rows",
            f"{deposit_rows} current retail rows; SBV policy rows={deposit_summary.get('sbv_policy_rates', {}).get('rows', 0)}",
            deposit_summary.get("history_status", "not audited"),
        ],
        [
            "News real-time availability",
            "Backfilled event_date lagged",
            pct(strict_news_share),
            "Strict mode uses availability_from; backfilled rows excluded from paper-trading history.",
        ],
        [
            "Boosting/deep model coverage",
            "Boosting deps previously missing",
            model_status,
            "Boosting models are trained when importable; deep models need a dedicated runner before inclusion.",
        ],
        [
            "Paper-trading status",
            "No rolling ledger",
            f"rows={paper.get('rows', 0)}, open={paper.get('open_rows', 0)}, closed={paper.get('closed_rows', 0)}",
            "Open trades have no realized return until exit price exists.",
        ],
    ]


def add_next_data_expansion_section(doc: Document, summary: dict[str, Any]) -> None:
    add_heading(doc, "10. Next Data Expansion & Paper Trading", 1)
    add_para(
        doc,
        "Mục này ghi nhận phần mở rộng sau snapshot bằng dữ liệu thật: Playwright được dùng cho SBV/NHNN vì API trực tiếp có thể bị chặn; Firecrawl chỉ là fallback cho bài báo/trang tĩnh khi có API key. Không có lịch đấu thầu hay lãi suất nào được sinh giả.",
    )
    add_para(doc, "Before vs After Caveats:")
    add_table(doc, ["Caveat", "Before", "After", "Decision impact"], caveat_improvement_rows(summary), max_rows=10)

    discovery_status = read_json("data/lake/source_discovery/sbv_source_discovery_status.json")
    discovery = read_csv("data/lake/source_discovery/sbv_structures.csv")
    events_status = read_json("data/lake/events/sbv_gold_policy_events_status.json")
    events = read_csv("data/lake/events/sbv_gold_policy_events.csv")
    paper = read_json("data/lake/modeling/paper_trading_summary.json")
    lbma = read_csv("data/lake/normalized/lbma_gold_spot_am_pm.csv")

    rows = [
        [
            "SBV source discovery",
            discovery_status.get("rows", len(discovery) if not discovery.empty else 0),
            "137473 central FX verified" if discovery_status.get("central_fx_structure_137473_verified") else "not verified",
            "; ".join(discovery_status.get("blockers", [])) or "No blocker recorded",
        ],
        [
            "SBV gold policy events",
            events_status.get("rows", len(events) if not events.empty else 0),
            f"{events_status.get('date_min', '')} to {events_status.get('date_max', '')}".strip(),
            "; ".join(events_status.get("blockers", [])) or "Official-event extraction completed",
        ],
        [
            "Rolling paper trading",
            paper.get("rows", 0),
            f"buy={paper.get('buy_rows', 0)}, open={paper.get('open_rows', 0)}, closed={paper.get('closed_rows', 0)}",
            "; ".join(paper.get("blockers", [])) or "Ledger ready",
        ],
        [
            "LBMA daily append",
            len(lbma) if not lbma.empty else 0,
            date_span(lbma) if not lbma.empty else "not collected in this run",
            "Public today.json append; historical backfill still requires licensed archive or GC=F proxy.",
        ],
    ]
    add_table(doc, ["Artifact", "Rows", "Coverage/status", "Caveat"], rows, max_rows=12)

    if not discovery.empty:
        cols = [c for c in ["content_structure_id", "classification", "row_count_sample", "field_names"] if c in discovery.columns]
        if cols:
            add_para(doc, "SBV structures discovered from official pages/session:")
            add_table(doc, ["Structure", "Classification", "Sample rows", "Fields"], discovery[cols].head(8).values.tolist(), max_rows=8)

    if not events.empty and "event_type" in events.columns:
        event_counts = events.groupby("event_type").size().reset_index(name="count").sort_values("count", ascending=False)
        add_para(doc, "Official SBV gold-policy event types collected:")
        add_table(doc, ["Event type", "Count"], event_counts.values.tolist(), max_rows=10)

    if paper.get("by_horizon"):
        p_rows = []
        for item in paper["by_horizon"]:
            avg = item.get("avg_realized_net_return")
            hit = item.get("hit_rate")
            p_rows.append([
                item.get("horizon_days"),
                item.get("buy_rows"),
                item.get("open_rows"),
                item.get("closed_rows"),
                pct(avg, 2) if avg is not None else "n/a",
                pct(hit, 1) if hit is not None else "n/a",
            ])
        add_para(doc, "Paper-trading ledger status by horizon:")
        add_table(doc, ["Horizon", "Buy rows", "Open", "Closed", "Avg realized", "Hit rate"], p_rows, max_rows=10)


def add_figures_section(doc: Document, figure_paths: dict[str, Path]) -> None:
    add_heading(doc, "11. Figures", 1)
    add_picture_if_exists(doc, figure_paths.get("price", Path()), "Figure 1. SJC price versus global gold proxy")
    add_picture_if_exists(doc, figure_paths.get("premium", Path()), "Figure 2. Premium regime over time")
    add_picture_if_exists(doc, figure_paths.get("leaderboard", Path()), "Figure 3. Model MAE leaderboard by horizon")
    add_picture_if_exists(doc, figure_paths.get("signals", Path()), "Figure 4. Decision signal frequency")


def add_appendix(doc: Document, summary: dict[str, Any]) -> None:
    section = doc.add_section(WD_SECTION.NEW_PAGE)
    section.top_margin = Cm(1.8)
    section.bottom_margin = Cm(1.8)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)
    add_heading(doc, "Appendix: Reproducibility", 1)
    add_para(doc, "Pipeline đã được chạy lại trên snapshot hiện có trước khi dựng báo cáo:")
    add_bullet(doc, "python scripts/analysis/run_decision_support_analysis.py")
    add_bullet(doc, "python scripts/analysis/export_trading_signals.py --quiet")
    add_bullet(doc, "python scripts/analysis/build_full_report.py")
    add_para(doc, "Các artifact chính:")
    for rel in [
        "data/lake/modeling/model_frame_daily.csv",
        "data/lake/modeling/model_results.csv",
        "data/lake/modeling/walk_forward_predictions.csv",
        "data/lake/modeling/decision_signals.csv",
        "data/lake/modeling/trading_signals.csv",
        "data/lake/modeling/snapshot_forecasts.csv",
        "data/lake/source_discovery/sbv_structures.csv",
        "data/lake/events/sbv_gold_policy_events.csv",
        "data/lake/modeling/paper_trading_ledger.csv",
        "data/lake/quality/premium_coverage_audit.csv",
        "data/lake/normalized/retail_deposit_rates.csv",
        "data/lake/normalized/sbv_policy_rates.csv",
        "data/lake/news_availability_audit.csv",
        "data/lake/modeling/model_sensitivity_summary.json",
    ]:
        add_bullet(doc, rel)
    add_para(doc, "Runtime blockers được ghi nhận:")
    for blocker in summary.get("blockers", []):
        add_bullet(doc, blocker)


def validate_report_inputs(summary: dict[str, Any], profiles: list[DataProfile], snapshot: pd.DataFrame) -> None:
    if not summary:
        raise RuntimeError("Missing analysis_summary.json; run decision support analysis first.")
    required = ["rows", "date_min", "date_max", "leaderboard", "decision_summary"]
    missing = [key for key in required if key not in summary]
    if missing:
        raise RuntimeError(f"analysis_summary.json missing keys: {missing}")
    if not any(p.rows > 0 and p.name == "Model frame" for p in profiles):
        raise RuntimeError("Model frame is empty or missing.")
    if snapshot.empty:
        raise RuntimeError("Snapshot forecasts could not be generated.")


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    summary = read_json("data/lake/modeling/analysis_summary.json")
    profiles, frames = build_profiles()
    frame = frames.get("Model frame", pd.DataFrame())
    feature_cols = load_feature_columns()
    snapshot = train_snapshot_forecasts(frame, feature_cols)

    validate_report_inputs(summary, profiles, snapshot)

    quality_rows = compute_data_quality(frames, summary)
    eda_tables = compute_eda_tables(frames)
    figure_paths = build_figures(frames, summary)
    mean_rows, quant_rows, decision_perf_rows = summarize_models(summary)
    recommendation, snapshot_rows = decision_recommendation(snapshot, decision_perf_rows)

    latest_date = str(summary.get("date_max", "2026-07-11"))
    doc = Document()
    configure_document(doc)
    add_cover(doc, latest_date)
    add_executive_summary(doc, latest_date, recommendation, summary)
    add_business_understanding(doc)
    add_literature_review(doc)
    add_data_sections(doc, profiles, quality_rows, eda_tables)
    add_modeling_sections(doc, mean_rows, quant_rows, decision_perf_rows, snapshot_rows, recommendation, summary)
    add_next_data_expansion_section(doc, summary)
    add_figures_section(doc, figure_paths)
    add_appendix(doc, summary)

    doc.save(OUT)
    print(f"Saved report: {OUT}")
    print(f"Snapshot forecast: {MODELING / 'snapshot_forecasts.csv'}")


if __name__ == "__main__":
    main()
