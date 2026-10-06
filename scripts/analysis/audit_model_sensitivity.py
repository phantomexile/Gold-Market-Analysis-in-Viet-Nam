#!/usr/bin/env python3
"""
Audit model sensitivity/readiness after data-quality improvements.

This script does not fabricate model scores. It records which feature-set
variants are data-ready, which optional model libraries are importable, and
which variants still need a dedicated training run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
OUT = LAKE / "modeling" / "model_sensitivity_summary.json"


def module_available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, low_memory=False)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    frame = read_csv(LAKE / "modeling" / "model_frame_daily.csv")
    news = read_csv(LAKE / "news_availability_audit.csv")
    premium = read_csv(LAKE / "pipeline_output_premium_enriched.csv")
    analysis = {}
    analysis_path = LAKE / "modeling" / "analysis_summary.json"
    if analysis_path.exists():
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))

    deps = {
        "lightgbm": module_available("lightgbm"),
        "xgboost": module_available("xgboost"),
        "catboost": module_available("catboost"),
        "torch": module_available("torch"),
        "pytorch_forecasting": module_available("pytorch_forecasting"),
        "gluonts": module_available("gluonts"),
    }

    variants: list[dict[str, Any]] = []
    if not frame.empty:
        premium_non_null = float(pd.to_numeric(frame.get("premium"), errors="coerce").notna().mean()) if "premium" in frame else 0.0
        raw_news_cols = [c for c in frame.columns if c.startswith("raw_news_")]
        variants.extend(
            [
                {
                    "variant": "current_all_features",
                    "status": "trained_in_main_runner",
                    "rows": int(len(frame)),
                    "premium_non_null_share": premium_non_null,
                    "news_feature_columns": len(raw_news_cols),
                    "latest_main_summary_date": analysis.get("generated_at", ""),
                },
                {
                    "variant": "no_premium",
                    "status": "ready_for_training",
                    "rows": int(len(frame)),
                    "reason": "Drop premium/global_gold_vnd derived columns for sensitivity training.",
                },
                {
                    "variant": "premium_high_quality_only",
                    "status": "ready_for_training" if not premium.empty and "source_quality" in premium else "blocked_missing_quality_flags",
                    "rows": int(len(frame)),
                    "high_quality_rows": int(premium["source_quality"].isin(["official_exact", "proxy_exact"]).sum()) if not premium.empty and "source_quality" in premium else 0,
                },
            ]
        )
    strict_share = 0.0
    if not news.empty and "feature_mode_strict" in news:
        strict_share = float(news["feature_mode_strict"].eq("strict_realtime_verified").mean())
    variants.append(
        {
            "variant": "strict_news_only",
            "status": "blocked_low_strict_news_coverage" if strict_share < 0.20 else "ready_for_training",
            "strict_realtime_news_share": strict_share,
        }
    )
    variants.append(
        {
            "variant": "no_news",
            "status": "ready_for_training",
            "reason": "Drop raw_news_* columns to quantify backfill sensitivity.",
        }
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dependency_availability": deps,
        "boosting_status": {
            "lightgbm": "available" if deps["lightgbm"] else "blocked_missing_dependency",
            "xgboost": "available" if deps["xgboost"] else "blocked_missing_dependency",
            "catboost": "available" if deps["catboost"] else "blocked_missing_dependency",
        },
        "deep_learning_status": "ready_for_experiment" if deps["torch"] and deps["pytorch_forecasting"] and deps["gluonts"] else "blocked_missing_dependency",
        "feature_set_variants": variants,
        "blockers": [],
    }
    if not deps["lightgbm"]:
        payload["blockers"].append("LightGBM not importable in current runtime.")
    if not deps["xgboost"]:
        payload["blockers"].append("XGBoost not importable in current runtime.")
    if not deps["catboost"]:
        payload["blockers"].append("CatBoost not importable in current runtime.")
    if strict_share < 0.20:
        payload["blockers"].append("Strict real-time news coverage is too low for a reliable news-only backtest.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
