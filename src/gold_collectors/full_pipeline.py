from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from .parsing import normalize_date


SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class SourceResult:
    source: str
    group: str
    status: str
    records: int
    output_dataset: str | None = None
    raw_hash: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    warning: str = ""
    detail: str = ""


@dataclass(frozen=True)
class DataQualityIssue:
    dataset: str
    severity: str
    check: str
    message: str


class DataLakeWriter:
    def __init__(
        self,
        root: str | Path,
        formats: Iterable[str] = ("parquet", "csv"),
        flat: bool = False,
    ):
        """Args:
        root: base directory
        formats: output formats
        flat: if True, write normalized/ output directly into root
              (no normalized/ subdirectory). Useful for flat data lakes.
        """
        self.root = Path(root)
        self.flat = flat
        self.formats = {item.strip().lower() for item in formats if item.strip()}
        self.raw_dir = self.root / "raw"
        self.normalized_dir = self.root if flat else self.root / "normalized"
        self.manifest_dir = self.root / "manifests"
        self.report_dir = self.root / "reports"
        for path in (self.raw_dir, self.normalized_dir, self.manifest_dir, self.report_dir):
            path.mkdir(parents=True, exist_ok=True)

    def write_dataset(self, dataset: str, rows: list[dict[str, Any]]) -> None:
        normalized_rows = [self._normalize_row(row) for row in rows]
        if "csv" in self.formats or "parquet" not in self.formats:
            self._write_csv(self.normalized_dir / f"{dataset}.csv", normalized_rows)
        if "parquet" in self.formats:
            self._write_parquet_or_note(dataset, normalized_rows)

    def write_manifest(self, results: list[SourceResult]) -> None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "results": [asdict(item) for item in results],
        }
        (self.manifest_dir / "source_manifest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_quality_report(self, issues: list[DataQualityIssue]) -> None:
        (self.report_dir / "quality_issues.json").write_text(
            json.dumps([asdict(item) for item in issues], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_summary(self, results: list[SourceResult], issues: list[DataQualityIssue]) -> None:
        grouped: dict[str, dict[str, int]] = {}
        for item in results:
            group = grouped.setdefault(item.group, {"sources": 0, "ok": 0, "empty": 0, "error": 0, "skipped": 0, "records": 0})
            group["sources"] += 1
            if item.status in {"ok", "empty", "error", "skipped"}:
                group[item.status] += 1
            elif item.status.startswith("skipped"):
                group["skipped"] += 1
            else:
                group["error"] += 1
            group["records"] += item.records

        lines = [
            "# Data Collection Summary",
            "",
            f"Generated at: {datetime.now().isoformat(timespec='seconds')}",
            f"Schema version: {SCHEMA_VERSION}",
            "",
            "## Source Summary",
            "",
            "| Group | Sources | OK | Empty | Error | Skipped | Records |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for group, stats in grouped.items():
            lines.append(
                f"| {group} | {stats['sources']} | {stats['ok']} | {stats['empty']} | {stats['error']} | {stats['skipped']} | {stats['records']} |"
            )
        lines.extend(["", "## Source Details", "", "| Source | Group | Status | Records | Dataset | Warning |", "|---|---|---|---:|---|---|"])
        for item in results:
            warning = item.warning.replace("|", "/") if item.warning else ""
            lines.append(f"| {item.source} | {item.group} | {item.status} | {item.records} | {item.output_dataset or ''} | {warning} |")
        lines.extend(["", "## Quality Issues", "", "| Dataset | Severity | Check | Message |", "|---|---|---|---|"])
        if issues:
            for issue in issues:
                lines.append(f"| {issue.dataset} | {issue.severity} | {issue.check} | {issue.message.replace('|', '/')} |")
        else:
            lines.append("| all | info | quality | No blocking quality issues found. |")
        (self.report_dir / "data_collection_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return
        fieldnames = sorted({key for row in rows for key in row})
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def _write_parquet_or_note(self, dataset: str, rows: list[dict[str, Any]]) -> None:
        note_path = self.normalized_dir / f"{dataset}.parquet.unavailable.txt"
        try:
            import pandas as pd  # type: ignore

            pd.DataFrame(rows).to_parquet(self.normalized_dir / f"{dataset}.parquet", index=False)
            if note_path.exists():
                note_path.unlink()
        except Exception as exc:  # noqa: BLE001 - parquet is optional; CSV fallback remains authoritative.
            note_path.write_text(f"Parquet write skipped: {exc}\nCSV fallback is available.\n", encoding="utf-8")

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        normalized = {}
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                normalized[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
            else:
                normalized[key] = value
        return normalized


def date_range(start: str, end: str) -> list[str]:
    _, start_iso = normalize_date(start)
    _, end_iso = normalize_date(end)
    current = datetime.strptime(start_iso, "%Y-%m-%d").date()
    last = datetime.strptime(end_iso, "%Y-%m-%d").date()
    if current > last:
        raise ValueError("--from must be <= --to")
    values = []
    while current <= last:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def run_quality_checks(datasets: dict[str, list[dict[str, Any]]]) -> list[DataQualityIssue]:
    required = {
        "gold_prices": ["date", "provider", "source", "buy", "sell", "unit", "currency", "raw_hash"],
        "fx_rates": ["date", "source", "pair", "mid", "quote_type", "raw_hash"],
        "macro_series": ["date", "series_id", "series_name", "frequency", "value", "unit", "source", "raw_hash"],
        "global_market_series": ["date", "series_id", "asset", "value", "unit", "source", "raw_hash"],
        "events": ["event_date", "event_type", "scope", "severity", "expected_channel", "note", "source_url"],
    }
    duplicate_keys = {
        "gold_prices": ["date", "timestamp", "provider", "source", "branch", "gold_type", "buy", "sell"],
        "fx_rates": ["date", "source", "pair", "quote_type"],
        "macro_series": ["date", "series_id", "source"],
        "global_market_series": ["date", "series_id", "source"],
        "events": ["event_date", "event_type", "scope"],
    }
    issues: list[DataQualityIssue] = []
    today = date.today().isoformat()
    for dataset, columns in required.items():
        rows = datasets.get(dataset, [])
        if not rows:
            issues.append(DataQualityIssue(dataset, "warning", "non_empty", "Dataset has no rows in this run."))
            continue
        for column in columns:
            if column not in rows[0]:
                issues.append(DataQualityIssue(dataset, "error", "required_columns", f"Missing column: {column}"))
        seen = set()
        for index, row in enumerate(rows):
            if row.get("raw_hash") == "":
                issues.append(DataQualityIssue(dataset, "error", "raw_hash", f"Empty raw_hash at row {index}"))
            row_date = row.get("date") or row.get("event_date")
            if isinstance(row_date, str) and re.match(r"\d{4}-\d{2}-\d{2}", row_date) and row_date[:10] > today:
                issues.append(DataQualityIssue(dataset, "error", "future_date", f"Future date at row {index}: {row_date}"))
            key_columns = duplicate_keys.get(dataset, columns)
            key = tuple((column, row.get(column)) for column in key_columns if column in row)
            if key in seen:
                issues.append(DataQualityIssue(dataset, "warning", "duplicate", f"Duplicate logical row at row {index}"))
            seen.add(key)
    return issues
