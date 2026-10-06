from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.collectors import SjcOfficialCollector, ThirdPartyArchiveCollector
from gold_collectors.full_pipeline import DataLakeWriter, date_range
from gold_collectors.http import CachedHttpClient, CollectorHttpError
from gold_collectors.models import GoldPriceRecord
from gold_collectors.reliability import business_date_from_record, collect_giavang_rows, date_range_windows

try:
    from tqdm import tqdm
except Exception:  # pragma: no cover
    tqdm = None


@dataclass(frozen=True)
class SourceStatus:
    source: str
    requested_dates: int
    rows: int
    errors: int
    note: str = ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect raw historical Vietnamese gold quotes (unfiltered) for a date range.")
    parser.add_argument("--from", dest="from_date", default="2010-01-01")
    parser.add_argument("--to", dest="to_date", default=None, help="YYYY-MM-DD. Default is today.")
    parser.add_argument("--out-dir", default="data/lake")
    parser.add_argument(
        "--sources",
        default="sjc_official,webgia_sjc_archive,giavang_sjc_archive,giavang_pnj_archive",
        help="Comma-separated source keys to crawl.",
    )
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0.35, help="Min seconds between HTTP requests.")
    parser.add_argument("--format", default="csv")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint and continue from last processed index.")
    parser.add_argument("--checkpoint-file", default=None, help="Custom checkpoint file path.")
    return parser.parse_args()


def _normalize_source_record(
    record: GoldPriceRecord,
    source_override: str | None = None,
    fallback_date: str | None = None,
) -> dict[str, Any] | None:
    business_date = business_date_from_record(record) or fallback_date
    if not business_date:
        return None

    buy = record.buy_value
    sell = record.sell_value
    return {
        "date": business_date,
        "source": source_override or record.source,
        "provider": record.provider,
        "branch": record.branch,
        "gold_type": record.gold_type,
        "buy": buy,
        "sell": sell,
        "spread": sell - buy if sell is not None and buy is not None else None,
        "unit": record.unit,
        "currency": record.currency,
        "timestamp": record.observed_at,
        "reference_date": record.reference_date,
        "raw_hash": record.raw_payload_hash,
        "crawl_mode": "raw_range",
    }


def _jsonl_path(out_dir: Path, source: str) -> Path:
    return out_dir / "raw" / f"{source}.jsonl"


def _checkpoint_path(out_dir: Path, args: argparse.Namespace) -> Path:
    if args.checkpoint_file:
        return Path(args.checkpoint_file)
    return out_dir / "checkpoints" / "raw_gold_history_checkpoint.json"


def _init_checkpoint(sources: set[str], args: argparse.Namespace, dates_len: int, windows_len: int) -> dict[str, Any]:
    return {
        "from": args.from_date,
        "to": args.to_date,
        "sources": sorted(sources),
        "generated_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "progress": {
            source: {
                "next_index": 0,
                "total": windows_len if source == "sjc_official_history" else dates_len,
                "rows": 0,
                "errors": 0,
            }
            for source in sources
        },
    }


def _load_checkpoint(path: Path, args: argparse.Namespace, sources: set[str], dates_len: int, windows_len: int) -> dict[str, Any]:
    if not path.exists():
        return _init_checkpoint(sources, args, dates_len, windows_len)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        old_from = payload.get("from")
        old_to = payload.get("to")
        # If expanding date range forward, preserve progress and update totals
        if old_from == args.from_date and old_to and args.to_date >= old_to:
            payload["to"] = args.to_date
            payload.setdefault("progress", {})
            for source in sources:
                payload["progress"].setdefault(source, {"next_index": 0, "total": 0, "rows": 0, "errors": 0})
                if source == "sjc_official_history":
                    payload["progress"][source]["total"] = windows_len
                else:
                    payload["progress"][source]["total"] = dates_len
            payload["updated_at"] = datetime.now().isoformat()
            return payload

        if old_from != args.from_date or old_to != args.to_date:
            return _init_checkpoint(sources, args, dates_len, windows_len)
        if sorted(payload.get("sources", [])) != sorted(sources):
            return _init_checkpoint(sources, args, dates_len, windows_len)
        payload.setdefault("generated_at", datetime.now().isoformat())
        payload.setdefault("progress", {})
        for source in sources:
            payload["progress"].setdefault(source, {"next_index": 0, "total": 0, "rows": 0, "errors": 0})
            if source == "sjc_official_history":
                payload["progress"][source]["total"] = windows_len
            else:
                payload["progress"][source]["total"] = dates_len
        payload["updated_at"] = datetime.now().isoformat()
        return payload
    except Exception:
        return _init_checkpoint(sources, args, dates_len, windows_len)


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _progress(label: str, total: int):
    if tqdm is None:
        print(f"{label}: 0/{total}", flush=True)

        def _next(current: int) -> None:
            print(f"{label}: {current}/{total}", end="\r", flush=True)

        return None, _next
    bar = tqdm(total=total, desc=label, unit="items")
    return bar, bar.update


def _close_progress(bar: Any) -> None:
    if bar is not None:
        bar.close()


def _normalize_sources(raw_sources: str) -> set[str]:
    source_map = {
        "sjc_official": "sjc_official_history",
        "webgia_sjc_archive": "webgia_sjc_archive",
        "giavang_sjc_archive": "giavang_sjc_archive",
        "giavang_pnj_archive": "giavang_pnj_archive",
    }
    normalized = set()
    for item in {value.strip() for value in raw_sources.split(",") if value.strip()}:
        if item in source_map:
            normalized.add(source_map[item])
        elif item in source_map.values():
            normalized.add(item)
    return normalized


def _collect_sjc_range(
    date_set: set[str],
    windows: list[tuple[str, str]],
    source_state: dict[str, Any],
    http: CachedHttpClient,
    source_output: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    start_index: int,
) -> SourceStatus:
    status = SourceStatus(
        "sjc_official_history",
        len(date_set),
        source_state.get("rows", 0),
        source_state.get("errors", 0),
        "resume_only" if source_state.get("next_index", 0) > 0 else "",
    )
    if start_index >= len(windows):
        status = SourceStatus(
            "sjc_official_history",
            len(date_set),
            source_state.get("rows", 0),
            source_state.get("errors", 0),
            "already_completed" if start_index >= len(windows) else status.note,
        )
        return status

    try:
        collector = SjcOfficialCollector(http)
    except Exception as exc:  # noqa: BLE001
        return SourceStatus("sjc_official_history", len(date_set), 0, 1, f"{type(exc).__name__}: {exc}")

    progress_bar, update = _progress("sjc_official_history (API)", len(windows) - start_index)
    sample_errors: list[str] = []
    rows: list[dict[str, Any]] = []
    for local_idx, window_idx in enumerate(range(start_index, len(windows))):
        window_start, window_end = windows[window_idx]
        window_rows: list[dict[str, Any]] = []
        try:
            for record in collector.get_history(1, window_start, window_end):
                row = _normalize_source_record(record, fallback_date=window_start)
                if row and row["date"] in date_set:
                    window_rows.append(row)
        except Exception as exc:  # noqa: BLE001
            status = SourceStatus(
                "sjc_official_history",
                len(date_set),
                status.rows,
                status.errors + 1,
                "; ".join(sample_errors + [f"{window_start}:{window_end} {type(exc).__name__}: {exc}"]),
            )
            if len(sample_errors) < 3:
                sample_errors.append(f"{window_start}:{window_end} {type(exc).__name__}: {exc}")
        if window_rows:
            _append_jsonl(source_output, window_rows)
            status = SourceStatus(
                "sjc_official_history",
                len(date_set),
                status.rows + len(window_rows),
                status.errors,
                status.note,
            )
        rows.extend(window_rows)
        source_state["next_index"] = window_idx + 1
        source_state["rows"] = status.rows
        source_state["errors"] = status.errors
        checkpoint["progress"]["sjc_official_history"] = source_state
        _save_checkpoint(checkpoint_path, checkpoint)
        if progress_bar is None:
            if local_idx % 5 == 0:
                update(local_idx + 1)
        else:
            update(1)

    _close_progress(progress_bar)
    if sample_errors:
        status = SourceStatus(status.source, status.requested_dates, status.rows, status.errors, "; ".join(sample_errors))
    return status


def _collect_daily_archive(
    source: str,
    dates: list[str],
    source_state: dict[str, Any],
    http: CachedHttpClient,
    source_output: Path,
    checkpoint_path: Path,
    checkpoint: dict[str, Any],
    start_index: int,
) -> SourceStatus:
    if start_index >= len(dates):
        return SourceStatus(
            source,
            len(dates),
            source_state.get("rows", 0),
            source_state.get("errors", 0),
            "already_completed",
        )
    errors = source_state.get("errors", 0)
    rows = source_state.get("rows", 0)
    sample_errors: list[str] = []
    collector = ThirdPartyArchiveCollector(http) if source == "webgia_sjc_archive" else None
    provider = "sjc" if source == "giavang_sjc_archive" else "pnj"
    progress_bar, update = _progress(f"{source}", len(dates) - start_index)

    for local_idx, idx in enumerate(range(start_index, len(dates))):
        current_date = dates[idx]
        daily_rows: list[dict[str, Any]] = []
        try:
            if source == "webgia_sjc_archive":
                assert collector is not None
                for record in collector.get_webgia_sjc_history(current_date):
                    row = _normalize_source_record(record, source_override=source, fallback_date=current_date)
                    if row:
                        daily_rows.append(row)
            else:
                daily_rows.extend(collect_giavang_rows(provider, current_date, http))
        except Exception as exc:  # noqa: BLE001
            errors += 1
            if len(sample_errors) < 3:
                sample_errors.append(f"{current_date}: {type(exc).__name__}: {exc}")
        if daily_rows:
            _append_jsonl(source_output, daily_rows)
            rows += len(daily_rows)
        source_state["next_index"] = idx + 1
        source_state["rows"] = rows
        source_state["errors"] = errors
        checkpoint["progress"][source] = source_state
        _save_checkpoint(checkpoint_path, checkpoint)
        if progress_bar is None:
            if local_idx % 5 == 0:
                update(local_idx + 1)
        else:
            update(1)

    _close_progress(progress_bar)
    return SourceStatus(source, len(dates), rows, errors, "; ".join(sample_errors))


def _merge_final(out_dir: Path, active_sources: list[str], output_formats: list[str], args: argparse.Namespace) -> int:
    combined: list[dict[str, Any]] = []
    seen = set()
    for source in active_sources:
        for row in _read_jsonl(_jsonl_path(out_dir, source)):
            key = (
                row.get("date"),
                row.get("source"),
                row.get("provider"),
                row.get("branch"),
                row.get("gold_type"),
                row.get("buy"),
                row.get("sell"),
                row.get("raw_hash"),
            )
            if key in seen:
                continue
            seen.add(key)
            combined.append(row)
    combined.sort(key=lambda row: (str(row.get("date", "")), str(row.get("source", "")), str(row.get("branch", "")), str(row.get("gold_type", ""))))
    writer = DataLakeWriter(out_dir, formats=output_formats)
    writer.write_dataset("raw_gold_history", combined)
    return len(combined)


def main() -> int:
    args = parse_args()
    if args.to_date is None:
        args.to_date = date.today().isoformat()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sources = _normalize_sources(args.sources)
    if not sources:
        sources = {"sjc_official_history", "webgia_sjc_archive", "giavang_sjc_archive", "giavang_pnj_archive"}

    all_dates = date_range(args.from_date, args.to_date)
    date_set = set(all_dates)
    date_windows = date_range_windows(args.from_date, args.to_date, days=120)

    checkpoint_path = _checkpoint_path(out_dir, args)
    if args.resume:
        checkpoint = _load_checkpoint(checkpoint_path, args, sources, len(all_dates), len(date_windows))
    else:
        checkpoint = _init_checkpoint(sources, args, len(all_dates), len(date_windows))
        for source in sources:
            file_path = _jsonl_path(out_dir, source)
            if file_path.exists():
                file_path.unlink()
        if checkpoint_path.exists():
            checkpoint_path.unlink()
        _save_checkpoint(checkpoint_path, checkpoint)

    for source in sources:
        checkpoint.setdefault("progress", {}).setdefault(
            source,
            {"next_index": 0, "total": 0, "rows": 0, "errors": 0},
        )

    http = CachedHttpClient(
        cache_dir=args.cache_dir or str(out_dir / "raw" / "http_cache"),
        timeout_seconds=args.timeout,
        retries=args.retries,
        min_interval_seconds=args.interval,
    )

    statuses: list[SourceStatus] = []
    for source in sorted(sources):
        source_state = checkpoint["progress"].get(source, {"next_index": 0, "rows": 0, "errors": 0})
        source_output = _jsonl_path(out_dir, source)

        if source == "sjc_official_history":
            sjc_start_idx = source_state.get("next_index", 0)
            if sjc_start_idx > 0 and sjc_start_idx <= len(date_windows):
                sjc_start_idx = max(0, sjc_start_idx - 1)
            status = _collect_sjc_range(
                date_set,
                date_windows,
                source_state,
                http,
                source_output,
                checkpoint_path,
                checkpoint,
                sjc_start_idx,
            )
        else:
            status = _collect_daily_archive(
                source,
                all_dates,
                source_state,
                http,
                source_output,
                checkpoint_path,
                checkpoint,
                source_state.get("next_index", 0),
            )
        checkpoint["progress"][source] = source_state
        _save_checkpoint(checkpoint_path, checkpoint)
        statuses.append(status)

    total_rows = _merge_final(out_dir, sorted(sources), [item.strip().lower() for item in args.format.split(",") if item.strip()], args)
    manifest = {
        "generated_at": date.today().isoformat(),
        "from": args.from_date,
        "to": args.to_date,
        "sources": sorted(sources),
        "checkpoint_file": str(checkpoint_path),
        "resume_used": bool(args.resume),
        "status": [status.__dict__ for status in statuses],
        "progress": checkpoint.get("progress", {}),
        "total_rows": total_rows,
    }
    manifest_path = out_dir / "manifests" / "raw_gold_history_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = {
        "out_dir": str(out_dir),
        "from": args.from_date,
        "to": args.to_date,
        "rows": total_rows,
        "sources": sorted(sources),
        "status": [status.__dict__ for status in statuses],
        "checkpoint_file": str(checkpoint_path),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
