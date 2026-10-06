from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.reliability import date_range, read_registry, write_csv, write_source_reliability

try:
    from tqdm import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None


def _progress(items, description: str, enabled: bool):
    if not enabled or _tqdm is None:
        return items
    return _tqdm(items, desc=description, unit="items")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate quality reports for audited gold data collection.")
    parser.add_argument("--data-lake", default="data/lake")
    parser.add_argument("--registry", default="configs/source_registry_audited.yaml")
    parser.add_argument("--from", dest="from_date", default="2011-07-06")
    parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD. Default is today.")
    parser.add_argument("--show-progress", action="store_true", default=True)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.to_date is None:
        args.to_date = date.today().isoformat()
    data_lake = Path(args.data_lake)
    report_dir = data_lake / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    rows = read_csv(data_lake / "gold_quotes_sjc_historical.csv")
    registry = read_registry(args.registry)

    write_source_reliability(report_dir / "source_reliability.csv", registry)
    write_csv(report_dir / "coverage_by_year.csv", coverage_by_year(rows, args.show_progress))
    write_csv(report_dir / "missing_dates.csv", missing_dates(rows, args.from_date, args.to_date, args.show_progress))
    write_csv(report_dir / "price_outlier_report.csv", price_outliers(rows, args.show_progress))
    write_csv(report_dir / "current_leakage_report.csv", current_leakage(rows, args.show_progress))

    summary = {
        "data_lake": str(data_lake),
        "records": len(rows),
        "historical_valid_sources": [item.source for item in registry if item.status == "historical_valid"],
        "current_only_sources": [item.source for item in registry if item.status == "current_only"],
        "reports": [
            "coverage_by_year.csv",
            "missing_dates.csv",
            "source_reliability.csv",
            "price_outlier_report.csv",
            "current_leakage_report.csv",
        ],
    }
    (report_dir / "final_quality_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def coverage_by_year(rows: list[dict[str, str]], show_progress: bool = False) -> list[dict[str, object]]:
    years = sorted({row.get("date", "")[:4] for row in rows if row.get("date")})
    output = []
    for year in _progress(years, "coverage_by_year", show_progress):
        year_rows = [row for row in rows if row.get("date", "").startswith(year)]
        dates = {row["date"] for row in year_rows if row.get("date")}
        output.append({"year": year, "covered_dates": len(dates), "records": len(year_rows), "sources": len({row.get("source") for row in year_rows})})
    return output


def missing_dates(rows: list[dict[str, str]], start: str, end: str, show_progress: bool = False) -> list[dict[str, str]]:
    present = {row.get("date") for row in rows}
    output = []
    for value in _progress(date_range(start, end), "missing_dates", show_progress):
        if value not in present:
            output.append({"date": value, "issue": "missing_domestic_gold_quote"})
    return output


def price_outliers(rows: list[dict[str, str]], show_progress: bool = False) -> list[dict[str, object]]:
    values = []
    for row in _progress(rows, "collect_price_values", show_progress):
        try:
            values.append(float(row.get("sell") or 0))
        except ValueError:
            pass
    if len(values) < 10:
        return []
    median = statistics.median(values)
    threshold_low = median * 0.25
    threshold_high = median * 4
    output = []
    for row in _progress(rows, "detect_outliers", show_progress):
        try:
            sell = float(row.get("sell") or 0)
        except ValueError:
            continue
        if sell < threshold_low or sell > threshold_high:
            output.append({"date": row.get("date"), "source": row.get("source"), "sell": sell, "median": median, "issue": "coarse_price_outlier"})
    return output


def current_leakage(rows: list[dict[str, str]], show_progress: bool = False) -> list[dict[str, str]]:
    output = []
    for row in _progress(rows, "detect_business_date_leakage", show_progress):
        if row.get("business_date") and row.get("date") and row["business_date"] != row["date"]:
            output.append({"date": row.get("date"), "business_date": row.get("business_date"), "source": row.get("source", ""), "issue": "business_date_mismatch"})
    return output


if __name__ == "__main__":
    raise SystemExit(main())
