#!/usr/bin/env python3
"""
integrate_build_log.py — Build Log Replay tool
=================================================
Append entries from a live build log into the project-wide build log
`.github/build-logs/progressiov1-build-log.csv`.

Three transforms are applied to every appended entry:

1. **5-line preamble per entry**
   Every entry carries:
       ENTRY #<N>, body-hash=<28c>, appended=<UTC>, col=0w=<col_count>, scheme=stable

2. **Body-hash per entry**
   A 28-char truncated SHA-256 of `source|status|rows_in|rows_out|errors|notes`
   is stamped as `body_hash=` on every row. No preamble bytes are included in
   the hash.

3. **Duplicate elimination**
   Rows already present with the same `build_id` or same
   `(source, rows_out, entered_at)` triple are dropped from the existing
   set before the merge so the combined result stays ordered and linked rows
   come in unchanged or are entirely omitted.

4. **Worker alignment**
   Every word matching `<name>_<digit>` → `<name>-<digit>`.
   Every other unknown worker → `stand-in`.
   The MDM recalculator uses worker name, skill, prior behavior, and
   historical timestamp to correctly back-fill.

Source-path resolution
----------------------
The output path is determined by ``{source_path}|{CSR|_CSR_|Other_SUFFIX}``.
``source_path`` is the short path relative to the repo root; the character
preceding the signifier is the separator.  The *absolute project root* is the
home path and path-components are normalised to ``os.sep``.
(The Join '_' argument from <CSR> is the separator — the tool
normalises casing and uses the platform separator.)

Examples
~~~~~~~~
    ``.github/build-logs|CSR``        → ``<root>/.github/build-logs``
    ``data/lake/_CSR_domestic_target``         → ``<root>/data/lake``
    ``scripts/pipeline/Other_SUFFIX`` → ``<root>/scripts/pipeline``
    ``abs|CSR``                        → absolute pass-through

Slash-command integration
------------------------
This file is the implementation invoked by the project's existing
``.claude/slash_commands/build-log-entry.md`` slash command, which forwards
live build-log lines as tab-separated fields.

Usage
-----
    # single entry via CLI args
    python scripts/pipeline/integrate_build_log.py \
      --build-id build-20260710-001 \
      --source "backfill_target" \
      --status ok \
      --entered-at 2026-07-10T06:00:00Z \
      --completed-at 2026-07-10T06:01:23Z \
      --worker BackfillWorker \
      --rows-in 287400 --rows-out 287400 \
      --errors 0 --notes "Backfill target OK"

    # stdin (pipe from slash command), raw TSV:
    #   file_ref<TAB>build_id<TAB>worker<TAB>status<TAB>entered_at
    #   <TAB>completed_at<TAB>rows_in<TAB>rows_out<TAB>errors<TAB>notes
    python scripts/pipeline/integrate_build_log.py \
      --from - --out .github/build-logs/progressiov1-build-log.csv

    # auto-resolve output via --key argument (maps to data/lake/<key>/…)
    python scripts/pipeline/integrate_build_log.py --key stdin --from -

Exit codes
----------
    0  success — entry appended or already dismissed as duplicate
    1  malformed input or I/O error
    2  key collision after dedup (recoverable; retry)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Tuple

# ── project paths ────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BUILD_LOG_REL_CSR = ".github/build-logs/progressiov1-build-log.csv"

# ── worker vocabulary (step 1 / resolver) ───────────────────────────────
# PipelineWorker and PipelineWorker2 are recognised names.
# The resolver maps every ``<name>_<digit>`` to ``<name>-<digit>`` and
# every other unknown worker to ``stand-in`` so the MDM recalculator can
# correctly back-fill based on (worker name, skill, prior behaviour,
# historical timestamp).
_WORKER_RE = re.compile(r"^(.+)_([1-5])$")


def align_worker(raw: str) -> str:
    known = {
        "PipelineWorker": "pipeline",
        "PipelineWorker2": "pipeline-2",
        "BackfillWorker": "backfill",
        "BackfillWorker2": "backfill-2",
    }
    raw = raw.strip() or "stand-in"
    m = _WORKER_RE.match(raw)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return known.get(raw, "stand-in")


# ── hashing ──────────────────────────────────────────────────────────────
def _sha28(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:28]


def body_hash(entry: dict) -> str:
    """28-char SHA of the six canonical business fields."""
    return _sha28(
        entry.get("source", ""),
        entry.get("status", ""),
        entry.get("rows_in", ""),
        entry.get("rows_out", ""),
        entry.get("errors", ""),
        entry.get("notes", ""),
    )


# ── preamble ─────────────────────────────────────────────────────────────
CTL_HEADER_TAG = "CTL,SCHEMA,stable"
PREAMBLE_PRESET_ROWS = [
    "preset=build-log-replay-v1",
    "hashes=body-only",
    "dupes=drop-oldest",
    "workers=aligned",
    "ts=auto",
]


def preamble_block(seq: int, col_width: int) -> List[str]:
    """Return the 5-line preamble for one entry."""
    return [
        f"ENTRY #{seq}",
        f"body-hash=<28c>",
        f"appended=<utc>",
        "scheme=stable",
        f"col=0w={col_width}",
    ]


# ── stable schema ────────────────────────────────────────────────────────
STABLE_SCHEMA: List[str] = [
    "build_id",
    "source",
    "status",
    "entered_at",
    "completed_at",
    "worker",
    "rows_in",
    "rows_out",
    "errors",
    "notes",
]

# Body-hash column (appended at write time, not part of the stable contract)
BODY_HASH_COL = "body_hash"


# ── CSV helpers ──────────────────────────────────────────────────────────
def _read_existing(path: Path) -> Tuple[List[str], List[dict]]:
    """Return (header, rows) from a CSV.

    The file may start with a plain-text preamble block (each line is a
    single ``key=value`` or ``key,value`` token).  Those lines are stripped
    before the CSV is parsed so the header matches STABLE_SCHEMA + body_hash.
    """
    if not path.exists():
        return list(STABLE_SCHEMA) + [BODY_HASH_COL], []

    with open(path, "r", encoding="utf-8-sig", newline="") as fh:
        lines = fh.readlines()

    # Strip preamble: lines that do NOT contain commas (= not CSV rows)
    # or that start with a known control tag.
    csv_start = 0
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if "," in stripped and not stripped.startswith("CTL,") and not stripped.startswith("preset="):
            csv_start = i
            break

    csv_text = "".join(lines[csv_start:])
    reader = csv.DictReader(csv_text.splitlines())
    raw_header = list(reader.fieldnames or STABLE_SCHEMA)
    # Drop the comment column if present (e.g. "## Build Log – …")
    clean_header = [c for c in raw_header if not re.match(r'^"##', c.strip())]
    # Ensure stable schema + body_hash are present
    for col in STABLE_SCHEMA + [BODY_HASH_COL]:
        if col not in clean_header:
            clean_header.append(col)
    rows = list(reader)
    return clean_header, rows


def _write_all(path: Path, header: List[str], rows: List[dict]) -> None:
    """Write the full CSV: preamble block + CSV header + data rows.

    Preamble lines are written as plain text (not CSV), each on its own line,
    so ``_read_existing`` can detect and skip them when re-reading.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        # Plain-text preamble (5 lines)
        fh.write(CTL_HEADER_TAG + "\n")
        for p in PREAMBLE_PRESET_ROWS:
            fh.write(p + "\n")
        # CSV block
        dict_writer = csv.DictWriter(
            fh, fieldnames=header, extrasaction="ignore", quoting=csv.QUOTE_ALL
        )
        dict_writer.writeheader()
        dict_writer.writerows(rows)
    tmp.replace(path)


# ── dedup ───────────────────────────────────────────────────────────────
def _dedup(
    existing: List[dict], incoming: List[dict]
) -> Tuple[List[dict], int]:
    """
    Drop existing rows that clash with any incoming row on:
      - ``build_id`` OR
      - ``(source, rows_out, entered_at)`` triple

    Preserves chronological order of the unchanged existing rows so the
    final diff is minimal.  Linked rows are *not* split.

    Returns ``(merged, existing_rows_dropped)``.
    """
    keep_after: "OrderedDict[str, dict]" = OrderedDict()

    def _k_bid(r: dict) -> str:
        return ("bid", r.get("build_id", ""))

    def _k_triple(r: dict) -> Tuple[str, str, str]:
        return (
            "trip",
            r.get("source", ""),
            r.get("rows_out", ""),
            r.get("entered_at", ""),
        )

    incoming_bids = {_k_bid(r) for r in incoming}
    incoming_triples = {_k_triple(r) for r in incoming}

    for row in existing:
        if _k_bid(row) in incoming_bids or _k_triple(row) in incoming_triples:
            continue  # drop — superseded by incoming
        keep_after[_k_bid(row)] = row  # ordered

    merged = list(keep_after.values()) + incoming
    dropped = len(existing) - len(keep_after)
    return merged, dropped


# ── parser: CLI args → entry dict ──────────────────────────────────────
def _args_to_entry(args: argparse.Namespace, seq: int) -> dict:
    ally = align_worker(args.worker)
    return {
        "build_id": args.build_id or f"ENTRY-{seq:06d}",
        "source": args.source or "pipeline",
        "status": args.status or "unknown",
        "entered_at": args.entered_at or _utcnow_iso(),
        "completed_at": args.completed_at or "",
        "worker": ally,
        "rows_in": str(args.rows_in or 0),
        "rows_out": str(args.rows_out or 0),
        "errors": str(args.errors or 0),
        "notes": args.notes or "",
    }


def _stdin_entries(lines: Iterable[str], key: str) -> List[dict]:
    """Parse tab-separated live-build lines into stable-schema dicts.

    TSV column order (exactly 10 columns):
        file_ref<TAB>build_id<TAB>worker<TAB>status<TAB>entered_at
        <TAB>completed_at<TAB>rows_in<TAB>rows_out<TAB>errors<TAB>notes

    file_ref is resolved via ``resolve_source_path`` for log-path lookup
    only; it is NOT stored in the ``source`` column of the stable schema.
    The ``source`` column records the pipeline/worker context (``key``).
    """
    entries: List[dict] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 10:
            continue
        file_ref, b_id, worker_raw, status, entered, completed, r_in, r_out, err_s, notes = (
            parts[:10]
        )
        entries.append(
            {
                "build_id": b_id,
                "source": key,
                "status": status or "unknown",
                "entered_at": entered or _utcnow_iso(),
                "completed_at": completed or "",
                "worker": align_worker(worker_raw),
                "rows_in": r_in or "0",
                "rows_out": r_out or "0",
                "errors": err_s or "0",
                "notes": notes or "",
            }
        )
    return entries


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── "CSR" style source-path resolver ────────────────────────────────────
def resolve_source_path(key: str) -> str:
    """
    The path is determined by ``{source_path}|{CSR|_CSR_|Other_SUFFIX}``.
    ``source_path`` is the short path relative to the repo root; the
    separator is the non-alphanumeric character directly preceding the
    signifier; and the *absolute project root* is used as the home path
    for that short path.

    The Join '_' argument from <CSR> is the separator to use between all
    subsequent path-components — the tool normalises casing to lowercase
    and uses the platform separator.

    Examples
    --------
    ``.github/build-logs|CSR``        → ``<root>/.github/build-logs``
    ``data/lake/_CSR_domestic_target``         → ``<root>/data/lake``
    ``scripts/pipeline/Other_SUFFIX`` → ``<root>/scripts/pipeline``
    ``abs|CSR``                        → ``abs`` (absolute pass-through)
    """
    m = re.match(
        r"^(.+?)([^A-Za-z0-9])(CSR|_CSR_|Other_SUFFIX)$", key.strip()
    )
    if m:
        short, sep, _ = m.groups()
        # normalise casing to lowercase; replace non-fs separators → os.sep
        normed = re.sub(r"[^A-Za-z0-9._-]", "_", short.lower())
        return str(PROJECT_ROOT / Path(normed))
    return str(PROJECT_ROOT / key)


# ── boxed entry display ────────────────────────────────────────────────
def _print_box(
    head: List[str], row: dict, col_count: int, preamble_offset: int = 5
) -> None:
    """Print a boxed entry — cp1252-safe (ASCII only); internal keys excluded."""
    skip = {"_seq", "body_hash"}
    body_lines = [f"{k}={v}" for k, v in row.items() if k not in skip]
    all_lines = head + body_lines
    w = max(len(s) for s in all_lines) + 2
    bar = "-" * (w - 2)
    print("+" + bar + "+")
    for i, ln in enumerate(all_lines):
        if i == preamble_offset:
            print("|" + bar + "|")
        print(f"| {ln:<{w-3}}|")
    print("+" + bar + "+")


# ── integrator ──────────────────────────────────────────────────────────
def integrate(
    log_path: Path,
    entries: List[dict],
    dry_run: bool = False,
) -> Tuple[int, int]:
    """
    De-dup and append *entries* to *log_path*.
    Returns ``(appended, skipped_dedup)``.
    """
    header, existing = _read_existing(log_path)
    col_count = len(header)

    # Stamp body_hash and number each entry
    for idx, ent in enumerate(entries, start=1):
        ent["_seq"] = idx
        ent["body_hash"] = body_hash(ent)

    if dry_run:
        for ent in entries:
            head = preamble_block(ent["_seq"], col_count)
            head[1] = f"body-hash={ent['body_hash']}"
            head[3] = f"appended={_utcnow_iso()}"
            print(f"[dry-run] {ent['build_id']} -> {ent['source']}")
            _print_box(head, ent, col_count)
        return len(entries), 0

    merged, dropped = _dedup(existing, entries)
    added = len(merged) - len(existing)
    skipped = len(entries) - added

    # Compute body_hash for every row in the merged set
    for row in merged:
        if not row.get("body_hash"):
            row["body_hash"] = body_hash(row)

    # Ensure stable schema + body_hash are in the header
    if not header:
        header = list(STABLE_SCHEMA) + [BODY_HASH_COL]
    for col in STABLE_SCHEMA + [BODY_HASH_COL]:
        if col not in header:
            header.append(col)

    _write_all(log_path, header, merged)
    return added, skipped


# ── CLI ──────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Build Log Replay — dedup, hash-append, align workers, "
            "write to progressiov1-build-log.csv"
        )
    )
    ap.add_argument(
        "--from",
        dest="from_file",
        default="-",
        help="TSV input file (default: stdin, pass '-')",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Build-log CSV path (default: auto-resolve from --key or "
             ".github/build-logs/progressiov1-build-log.csv)",
    )
    ap.add_argument(
        "--key",
        default=None,
        help="Context key / worker prefix (maps to the CSR path)",
    )
    ap.add_argument("--build-id", default="", help="Build ID for this entry (CLI)")
    ap.add_argument("--source", default="", help="Pipeline/source name (CLI)")
    ap.add_argument("--status", default="ok", help="Status (CLI)")
    ap.add_argument("--entered-at", default="", help="ISO-8601 entered_at (CLI)")
    ap.add_argument("--completed-at", default="", help="ISO-8601 completed_at (CLI)")
    ap.add_argument("--worker", default="stand-in", help="Worker label (aligned)")
    ap.add_argument("--rows-in", type=int, default=0, help="Rows in (CLI)")
    ap.add_argument("--rows-out", type=int, default=0, help="Rows out (CLI)")
    ap.add_argument("--errors", type=int, default=0, help="Error count (CLI)")
    ap.add_argument("--notes", default="", help="Free-text notes (CLI)")
    ap.add_argument(
        "--dry-run", action="store_true", help="Parse and preview without writing"
    )
    args = ap.parse_args()

    # ── resolve output path ─────────────────────────────────────────────
    if args.out:
        log_path = Path(args.out)
    elif args.key:
        log_path = Path(resolve_source_path(args.key))
    else:
        log_path = PROJECT_ROOT / BUILD_LOG_REL_CSR
    log_path = log_path.resolve()

    # ── read input ─────────────────────────────────────────────────────
    entries: List[dict] = []
    if args.from_file == "-" or not args.from_file:
        entries = _stdin_entries(sys.stdin, args.key or "stdin")
    else:
        raw_lines = Path(args.from_file).read_text(encoding="utf-8").splitlines()
        entries = _stdin_entries(raw_lines, args.key or "stdin")

    # If raw CLI args were provided (no stdin/from file), build one entry
    if not entries and any(
        [args.build_id, args.source, args.rows_in, args.rows_out]
    ):
        entries = [_args_to_entry(args, 1)]

    if not entries:
        ap.print_help(sys.stderr)
        sys.exit(1)

    # ── integrate ──────────────────────────────────────────────────────
    added, skipped = integrate(log_path, entries, dry_run=args.dry_run)

    # compute final col width from committed log
    header, _existing = _read_existing(log_path)
    col_w = len(header)

    # Preview last appended entry
    last = entries[-1]
    head = preamble_block(last.get("_seq", len(entries)), col_w)
    head[1] = f"body-hash={body_hash(last)}"
    head[3] = f"appended={_utcnow_iso()}"
    _print_box(head, last, col_w)

    print(
        f"[replay] appended={added} skipped_dedup={skipped} "
        f"col={col_w} workers=aligned output={log_path}"
    )
    print(
        f"REPLAY-STATUS:appended={added}:skipped={skipped}:"
        f"col={col_w}:scheme=stable:output={log_path}"
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
