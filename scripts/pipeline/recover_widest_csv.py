"""
recover_widest_csv.py
---------------------
Back up the project's widest output CSV — the 18-column master panel
`data/lake/modeling/gold_domestic_daily_panel.csv` — before
any user-requested deletion overwrite happens.

What it does
~~~~~~~~~~~~
1. Reads the widest CSV, computes a SHA-256 hash of its full content.
2. Writes a backup copy whose *content* is prefended with a 4-line preamble
   containing: timestamp, source path, content hash, row count.
   The original header line becomes line-5 so it is self-describing.
3. Stores the backup in a `.recovery/` directory next to the source.
4. Emits a boxed recovery-reference string to stdout.

Recovery-reference format
~~~~~~~~~~~~~~~~~~~~~~~~~
┌─────────────────────────────────────────┐
│ RECOVERY-SUCCESS │ hash=<sha256>        │
│ source=gold_domestic_daily_panel.csv    │
│ cols=18 rows=<N>                         │
│ backup=<recovery path>                   │
└─────────────────────────────────────────┘

Usage
~~~~~
    python scripts/pipeline/recover_widest_csv.py
    python scripts/pipeline/recover_widest_csv.py --target gold_domestic_daily_panel.csv

Exits 0 on success, 1 if source file is missing or empty.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
WIDEST_CSV = (
    PROJECT_ROOT
    / "data/lake/modeling/gold_domestic_daily_panel.csv"
)

# All output CSVs known to the pipeline (descending by column count).
_OUTPUT_REGISTRY: list[tuple[str, Path, int]] = []


def _register_outputs() -> None:
    """Scan data/lake for `normalized/*.csv` files and sort by column count desc."""
    norm = PROJECT_ROOT / "data/lake"
    if not norm.exists():
        return
    for csv_path in norm.rglob("normalized/*.csv"):
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
            _OUTPUT_REGISTRY.append((csv_path.name, csv_path, len(header)))
        except Exception:
            continue
    _OUTPUT_REGISTRY.sort(key=lambda t: t[2], reverse=True)


def widest_csv(target_override: str | None = None) -> tuple[int, Path, str]:
    """Return (col_count, path, sha256_hex) for the widest output CSV."""
    _register_outputs()
    if target_override:
        matches = [t for t in _OUTPUT_REGISTRY if t[0] == target_override]
        if not matches:
            sys.exit(f"[recover] fatal: '{target_override}' not found in data/lake/**/")
        _, path, n_cols = matches[0]
    else:
        if not _OUTPUT_REGISTRY:
            sys.exit("[recover] fatal: no normalized CSV files found under data/lake/")
        _, path, n_cols = max(_OUTPUT_REGISTRY, key=lambda t: t[2])

    if not path.exists():
        sys.exit(f"[recover] fatal: widest CSV not found at {path}")

    raw = path.read_bytes()
    if not raw:
        sys.exit(f"[recover] fatal: widest CSV is empty: {path}")
    digest = hashlib.sha256(raw).hexdigest()
    return n_cols, path, digest


def build_recovery_preamble(
    source_path: Path,
    col_count: int,
    content_hash: str,
    row_count: int,
) -> list[str]:
    """Build the 4-column `col...row` prefix lines prepended to the backup."""
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    return [
        f"col={col_count}",
        f"row={row_count}",
        f"hash={content_hash}",
        f"ts={ts}",
    ]


def backup_widest(
    target: str | None = None,
) -> tuple[int, Path, str, Path]:
    """
    Create a `.recovery/` backup of the widest CSV.
    The backup file is the wide CSV with a 4-line preamble prepended.
    Returns (col_count, source_path, content_hash, backup_path).
    """
    col_count, src_path, digest = widest_csv(target)

    raw_text = src_path.read_text(encoding="utf-8-sig")
    lines = raw_text.splitlines()
    header_line = lines[0] if lines else ""
    row_count = max(len(lines) - 1, 0)

    preamble = build_recovery_preamble(src_path, col_count, digest, row_count)

    recovery_dir = src_path.parent / ".recovery"
    recovery_dir.mkdir(exist_ok=True)
    ts_stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_name = f"{src_path.name}.recovery.{ts_stamp}.{digest[:12]}"
    backup_path = recovery_dir / backup_name

    body = "\n".join(preamble) + "\n" + raw_text
    backup_path.write_text(body, encoding="utf-8")
    return col_count, src_path, digest, backup_path


def print_recovery_box(cols, src, digest, backup) -> None:
    """Print the boxed RECOVERY-SUCCESS reference."""
    src_name = src.name
    backup_rel = backup.relative_to(PROJECT_ROOT)
    lines = [
        f"RECOVERY-SUCCESS | hash={digest}",
        f"source={src_name}",
        f"cols={cols} rows={_count_rows(backup)}",
        f"backup={backup_rel}",
    ]
    w = max(len(l) for l in lines) + 2
    top = "+" + "-" * (w - 2) + "+"
    bot = "+" + "-" * (w - 2) + "+"
    print()
    for i, line in enumerate((top, *[f"| {l:<{w-3}}|" for l in lines], bot)):
        print(line)
    print()


def _count_rows(path: Path) -> int:
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            # count data rows (skip recovery preamble lines)
            lines = fh.readlines()
        # find the actual CSV header (contains commas, no space before =)
        header_idx = 0
        for i, ln in enumerate(lines):
            if "," in ln and "=" not in ln[:20]:
                header_idx = i
                break
        return max(len(lines) - header_idx - 1, 0)
    except Exception:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup the widest output CSV before rebuild deletion."
    )
    parser.add_argument(
        "--target",
        help="Explicit CSV filename to back up (overrides auto-detection).",
    )
    args = parser.parse_args()

    cols, src, digest, backup = backup_widest(args.target)
    print(f"[recover] backed up widest CSV ({cols} cols) to {backup.relative_to(PROJECT_ROOT)}")
    print_recovery_box(cols, src, digest, backup)

    # Emit machine-readable reference string for caller to consume
    print(f"RECOVERY-REFERENCE:hash={digest}:source={src.name}:w={cols}:backup={backup}")


if __name__ == "__main__":
    main()
