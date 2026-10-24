from __future__ import annotations

# Tìm thư mục dự án khi chạy trực tiếp; các nhóm script đều nằm cùng độ sâu.
import sys as _sys
from pathlib import Path as _Path

if __package__ in (None, ""):
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))
from scripts._bootstrap import bootstrap as _bootstrap_project

_bootstrap_project()


import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any



from gold_collectors.full_pipeline import DataLakeWriter
from gold_collectors.http import CachedHttpClient
from gold_collectors.reliability import (
    collect_fred_series,
    collect_gso_macro_monitor_features,
    collect_optional_vnstock_features,
    collect_sbv_central_fx_history,
    collect_vietcombank_fx,
    collect_worldbank_macro,
    collect_yfinance_prices,
)

try:
    from tqdm import tqdm as _tqdm
except Exception:  # pragma: no cover
    _tqdm = None


@dataclass(frozen=True)
class FeatureSourceStatus:
    source: str
    dataset: str
    status: str
    records: int
    warning: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect external feature sources aligned by date.")
    parser.add_argument("--from", dest="from_date", default="2011-07-06")
    parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD. Default is today.")
    parser.add_argument("--out-dir", default="data/lake")
    parser.add_argument("--format", default="parquet,csv")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--show-progress", action="store_true", default=True)
    return parser.parse_args()


def _progress(items: list[tuple[str, str, Any]], description: str, enabled: bool) -> Any:
    if not enabled or _tqdm is None:
        return items
    return _tqdm(items, desc=description, unit="datasets")


def guarded(source: str, dataset: str, fn):
    try:
        rows = fn()
        return rows, FeatureSourceStatus(source, dataset, "ok" if rows else "empty", len(rows))
    except Exception as exc:  # noqa: BLE001
        return [], FeatureSourceStatus(source, dataset, "error", 0, f"{type(exc).__name__}: {exc}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    if args.to_date is None:
        args.to_date = date.today().isoformat()
    out_dir = Path(args.out_dir)
    writer = DataLakeWriter(out_dir, formats=args.format.split(","), flat=True)
    http = CachedHttpClient(cache_dir=out_dir / "raw" / "http_cache", timeout_seconds=args.timeout, retries=args.retries, min_interval_seconds=0.35)

    datasets = {
        "fx_rates": [],
        "global_market_series": [],
        "macro_series": [],
        "vn_market_series": [],
    }
    statuses: list[FeatureSourceStatus] = []

    sources = [
        ("vietcombank_fx", "fx_rates", lambda: collect_vietcombank_fx(http)),
        ("sbv_central_fx_history", "fx_rates", lambda: collect_sbv_central_fx_history(args.from_date, args.to_date)),
        ("yfinance_gold", "global_market_series", lambda: collect_yfinance_prices(args.from_date, args.to_date)),
        ("fred_global_macro", "global_market_series", lambda: collect_fred_series(args.from_date, args.to_date, http)),
        ("worldbank_vietnam_macro", "macro_series", lambda: collect_worldbank_macro(http)),
        ("gso_macro_monitor", "macro_series", collect_gso_macro_monitor_features),
        ("vnstock_market_features", "vn_market_series", lambda: collect_optional_vnstock_features(args.from_date, args.to_date)),
    ]
    for source, dataset, fn in _progress(sources, "Collect external features", args.show_progress):
        rows, status = guarded(source, dataset, fn)
        datasets[dataset].extend(rows)
        statuses.append(status)

    for dataset, rows in datasets.items():
        writer.write_dataset(dataset, rows)
    (out_dir / "manifests" / "external_feature_manifest.json").write_text(
        json.dumps([asdict(item) for item in statuses], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({"out_dir": str(out_dir), "sources": len(statuses), "records": sum(item.records for item in statuses)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
