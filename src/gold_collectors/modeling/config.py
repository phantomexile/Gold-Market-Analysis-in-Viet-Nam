"""Cấu hình đường dẫn, kỳ hạn tháng lịch và tham số dùng chung cho mô hình."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from gold_collectors.units import LUONG_PER_OZ


ROOT = Path(__file__).resolve().parents[3]
LAKE = ROOT / "data" / "lake"
REPORTS = ROOT / "docs" / "reports"

# Kỳ hạn dự báo là tháng lịch; các số 21/63/105 bên dưới chỉ là độ trễ đặc trưng.
HORIZONS = (1, 3, 5)
LAGS = (1, 5, 10, 21, 63, 105)


# Đường dẫn và tham số mặc định giúp các bước phân tích dùng cùng một cấu hình.
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
