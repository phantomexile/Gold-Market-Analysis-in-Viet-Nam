#!/usr/bin/env python3
"""
recovery_hash_backup.py
=======================
Pre-deletion backup tool. Quarantines a copy of the widest output CSV
before destructive operations (delete / reset) are performed on downstream
artifacts such as the build log.

Strategy:
  1. Discover candidate output CSVs under data/lake/ and rank by column count.
  2. Hash the widest file body (UTF-8, header excluded) with SHA-256.
  3. Copy the full file (header + body) to .github/build-logs/backups/ with
     the hash suffix appended to the filename.
  4. Emit quarantine manifest to .github/build-logs/backups/quarantine_manifest.json
     so replay scripts can verify integrity without re-reading the full CSV.

Usage:
    python scripts/pipeline/recovery_hash_backup.py
    python scripts/pipeline/recovery_hash_backup.py --target <path>  # override auto-discovery
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LAKE_OUTPUT_DIRS = [
    PROJECT_ROOT / "data/lake/modeling",
    PROJECT_ROOT / "data/lake/gold_prices",
    PROJECT_ROOT / "data/lake/normalized",
    PROJECT_ROOT / "data/lake/normalized",
    PROJECT_ROOT / "data/lake/normalized",
]
BACKUP_DIR = PROJECT_ROOT / ".github/build-logs/backups"
MANIFEST_PATH = BACKUP_DIR / "quarantine_manifest.json"


def count_columns(csv_path: Path) -> int:
    """Return the number of columns in the header row of a CSV."""
    try:
        with open(csv_path, "r", encoding="utf-8", errors="replace") as fh:
            header_line = fh.readline()
            return len(header_line.strip().split(","))
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] Cannot read {csv_path}: {exc}", file=sys.stderr)
        return 0


def sha256_file(path: Path) -> str:
    """Return hex-encoded SHA-256 of the full file contents."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_body_text(path: Path, encoding: str = "utf-8") -> str:
    """Return hex-encoded SHA-256 of CSV body only (skip header line)."""
    h = hashlib.sha256()
    with open(path, "r", encoding=encoding, errors="replace") as fh:
        fh.readline()  # skip header
        for chunk in iter(lambda: fh.read(1 << 16), ""):
            h.update(chunk.encode(encoding))
    return h.hexdigest()


def discover_widest(dirs: list[Path]) -> Path | None:
    """Scan dirs for CSV files; return the one with the most columns."""
    best: tuple[int, Path] | None = None
    for d in dirs:
        if not d.is_dir():
            continue
        for csv_path in sorted(d.glob("*.csv")):
            n = count_columns(csv_path)
            if n > 0 and (best is None or n > best[0]):
                best = (n, csv_path)
    return best[1] if best else None


def write_manifest(manifest: dict) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-deletion recovery hash backup")
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Explicit path to the CSV to quarantine (skips auto-discovery).",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=str(BACKUP_DIR),
        help="Destination directory for the backup copy.",
    )
    args = parser.parse_args()

    # Resolve target
    if args.target:
        target = Path(args.target)
        if not target.is_file():
            print(f"[err] Target file not found: {target}", file=sys.stderr)
            return 1
    else:
        print("[info] Auto-discovering widest output CSV...")
        target = discover_widest(LAKE_OUTPUT_DIRS)
        if target is None:
            print("[err] No CSV files found in candidate directories.", file=sys.stderr)
            return 1

    col_count = count_columns(target)
    file_size = target.stat().st_size
    full_hash = sha256_file(target)
    body_hash = sha256_body_text(target)
    ts = datetime.now(timezone.utc).isoformat()

    # Compose backup filename: original-stem + .{first8ofhash}.backup.csv
    stem = target.stem
    ext = target.suffix
    backup_name = f"{stem}.{full_hash[:8]}.backup{ext}"
    backup_path = Path(args.out_dir) / backup_name

    # Copy
    Path(args.out_dir).mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup_path)

    manifest = {
        "quarantine_timestamp_utc": ts,
        "source_file": str(target),
        "backup_file": str(backup_path),
        "column_count": col_count,
        "byte_size": file_size,
        "sha256_full": full_hash,
        "sha256_body": body_hash,
    }
    write_manifest(manifest)

    print(f"[ok] Quarantined: {target}")
    print(f"     Backup ->   {backup_path}")
    print(f"     Columns: {col_count}  |  Size: {file_size:,} bytes")
    print(f"     SHA256(full):  {full_hash}")
    print(f"     SHA256(body):  {body_hash}")
    print(f"     Manifest:  {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
