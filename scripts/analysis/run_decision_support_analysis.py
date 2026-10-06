#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
for path in (ROOT, SRC):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)

from gold_collectors.modeling import ModelingConfig, run_full_analysis


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VN gold EDA/modeling decision-support analysis.")
    parser.add_argument("--data-lake", default=str(ROOT / "data" / "lake"))
    parser.add_argument("--output-dir", default=str(ROOT / "data" / "lake" / "modeling"))
    parser.add_argument("--report-path", default=str(ROOT / "docs" / "reports" / "eda_modeling_literature_review.md"))
    args = parser.parse_args()

    config = ModelingConfig(
        data_lake=Path(args.data_lake),
        output_dir=Path(args.output_dir),
        report_path=Path(args.report_path),
    )
    summary = run_full_analysis(config)
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
