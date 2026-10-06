from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.http import CachedHttpClient
from gold_collectors.reliability import AUDIT_DATES, SourceAuditor, write_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit source historical reliability by requested_date vs business_date.")
    parser.add_argument("--dates", nargs="+", default=AUDIT_DATES, help="Audit dates in YYYY-MM-DD format.")
    parser.add_argument("--out-dir", default="audit_output", help="Output directory.")
    parser.add_argument("--cache-dir", default=".cache/source_audit", help="HTTP cache directory.")
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--retries", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    http = CachedHttpClient(cache_dir=args.cache_dir, timeout_seconds=args.timeout, retries=args.retries, min_interval_seconds=0.35)
    rows = SourceAuditor(http).audit(args.dates)
    payload = [asdict(row) for row in rows]
    (out_dir / "source_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out_dir / "source_audit.csv", payload)
    print(json.dumps({"out_dir": str(out_dir), "records": len(rows)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
