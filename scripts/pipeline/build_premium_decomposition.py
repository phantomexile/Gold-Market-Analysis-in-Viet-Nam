#!/usr/bin/env python3
"""
Premium decomposition builder for Vietnamese gold market.

Materializes:
- global_gold_vnd_per_luong: LBMA USD/oz converted to VND/luong
- domestic_premium: local sell - global_gold_vnd_per_luong
- spread_pct: (sell - buy) / sell
- consensus_mid: (buy + sell) / 2

Outputs to data/lake/
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import date, datetime, timedelta

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.full_pipeline import DataLakeWriter, date_range
from gold_collectors.parsing import normalize_date, parse_number
from gold_collectors.reliability import collect_historical_rows, accepted_historical_sources, read_registry

LUONG_TO_CHI = 37.5 # 1 luong = 37.5 chi
LUONG_TO_OZ = 0.03527395 # troy oz per chi (approx)

# VND per ounce: 23.25 VND/chi * 37.5 chi/luong * 37.5 chi/luong... let's just use standard
# 1 troy oz = 31.1034768 grams
# 1 chi = 1.205 grams
# So 1 oz / 1 chi = 31.1034768 / 1.205 = 25.807 chi/oz
CHI_PER_OZ = 31.1034768 / 1.205 # ~25.807
LUONG_PER_OZ = CHI_PER_OZ / 37.5 # ~0.688 chi/luong... wait

# Standard: 1 luong = 37.5 chi (noi tai), 1 chi = 1.205 grams
# 1 troy ounce = 31.1034768 grams
# So 1 oz = (31.1034768 / 1.205) chi = 25.807 chi
# And 1 luong = 37.5 chi
# So 1 oz = 25.807 chi = 25.807 / 37.5 luong = 0.68856 luong
LUONG_PER_OZ = CHI_PER_OZ / 37.5 # gold standard conversion in Vietnam


def parse_args():
    parser = argparse.ArgumentParser(description="Build premium decomposition table.")
    parser.add_argument("--audited-dir", default="data/lake")
    parser.add_argument("--external-dir", default="data/lake")
    parser.add_argument("--out-dir", default="data/lake")
    parser.add_argument("--registry", default="configs/source_registry_audited.yaml")
    return parser.parse_args()


def load_csv_rows(path: Path, date_col: str = "date") -> list[dict]:
    if not path.exists():
        return []
    import csv as _csv
    with path.open(encoding="utf-8") as f:
        return list(_csv.DictReader(f))


def build_premium_table(args) -> int:
    audited = Path(args.audited_dir)
    external = Path(args.external_dir)
    out_dir = Path(args.out_dir)
    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)

    def _find_candidate(paths: list[Path]) -> Path:
        for p in paths:
            if p.exists() and p.stat().st_size > 0:
                return p
        return paths[0]

    # Load domestic gold quotes
    gold_path = _find_candidate([
        audited / "domestic_gold_quotes.csv",
        audited / "normalized" / "domestic_gold_quotes.csv",
        Path("data/lake/domestic_gold_quotes.csv"),
    ])
    gold_rows = load_csv_rows(gold_path)
    print(f"Loaded {len(gold_rows)} domestic gold rows from {gold_path}")

    # Index by date and source
    by_date_source: dict[tuple[str, str], dict] = {}
    for row in gold_rows:
        key = (row.get("date", ""), row.get("source", ""))
        by_date_source[key] = row

    # Load external features for LBMA gold and FX
    global_market_path = _find_candidate([
        external / "global_market_series_yfinance_fred.csv",
        external / "global_market_series.csv",
        external / "normalized" / "global_market_series.csv",
        Path("data/lake/global_market_series_yfinance_fred.csv"),
    ])
    fx_rates_path = _find_candidate([
        external / "global_reference_daily.csv",
        external / "fx_rates.csv",
        external / "normalized" / "fx_rates.csv",
        Path("data/lake/global_reference_daily.csv"),
    ])
    global_market = load_csv_rows(global_market_path)
    fx_rates = load_csv_rows(fx_rates_path)

    # Index global market by date and series
    global_by_date: dict[str, dict[str, dict]] = {}
    for row in global_market:
        d = row.get("date", "")[:10]
        sid = row.get("series_id", "")
        global_by_date.setdefault(d, {})[sid] = row

    # Index FX by date
    fx_by_date: dict[str, dict[str, list[dict]]] = {}
    for row in fx_rates:
        d = row.get("date", "")[:10]
        fx_by_date.setdefault(d, []).append(row)

    # Main decomposition
    enriched: list[dict] = []
    all_dates = sorted({row.get("date", "") for row in gold_rows if row.get("date")})

    stats = {"processed": 0, "with_premium": 0, "with_global": 0, "with_fx": 0}

    # Accept any available source (works with single-source or multi-source data)
    for row_date in all_dates:
        day_sources = {src: row for (d, src), row in by_date_source.items() if d == row_date}
        if not day_sources:
            continue

        stats["processed"] += 1

        # Get global gold price (USD/oz) for this date (look back up to 5 days for weekends/holidays)
        global_gold_usd = None
        for bid in _recent_dates(row_date, max_lookback=5):
            if bid in global_by_date:
                for sid_key in ["GC=F", "GLD"]:
                    if sid_key in global_by_date[bid]:
                        try:
                            val = float(global_by_date[bid][sid_key].get("value", 0))
                            if val > 0:
                                global_gold_usd = val
                                break
                        except (ValueError, TypeError):
                            pass
                if global_gold_usd:
                    break

        if global_gold_usd:
            stats["with_global"] += 1

        # Get USD/VND rate (look back up to 5 days for weekends/holidays)
        usd_vnd = None
        for bid in _recent_dates(row_date, max_lookback=5):
            # Prefer SBV central rate
            fx_list = fx_by_date.get(bid, [])
            for fx_row in fx_list:
                if fx_row.get("source") == "sbv_central_fx_history" and fx_row.get("mid"):
                    try:
                        usd_vnd = float(fx_row["mid"])
                        break
                    except (ValueError, TypeError):
                        pass
            if usd_vnd:
                break

            # Fallback to USDVND=X from yfinance
            if bid in global_by_date and "USDVND=X" in global_by_date[bid]:
                try:
                    usd_vnd_val = float(global_by_date[bid]["USDVND=X"].get("value", 0))
                    if usd_vnd_val > 0:
                        usd_vnd = usd_vnd_val
                        break
                except (ValueError, TypeError):
                    pass
            if usd_vnd:
                break

        if usd_vnd:
            stats["with_fx"] += 1

        # Calculate global gold in VND/luong
        global_gold_vnd_per_luong = None
        if global_gold_usd and usd_vnd:
            # Convert: USD/oz * USD/VND = VND/oz
            # Then VND/oz / chi_per_oz = VND/chi
            # Then VND/chi * 37.5 = VND/luong
            global_vnd_per_chi = global_gold_usd * usd_vnd / CHI_PER_OZ
            global_gold_vnd_per_luong = global_vnd_per_chi * 37.5 # VND per luong

        # Build consensus buy/sell from available sources
        buy_prices = []
        sell_prices = []
        for src, src_row in day_sources.items():
            try:
                b = float(src_row.get("buy", 0))
                s = float(src_row.get("sell", 0))
                if b > 0 and s > 0:
                    buy_prices.append(b)
                    sell_prices.append(s)
            except (ValueError, TypeError):
                pass

        if not buy_prices or not sell_prices:
            continue

        consensus_buy = _median(buy_prices)
        consensus_sell = _median(sell_prices)
        consensus_mid = (consensus_buy + consensus_sell) / 2
        spread_abs = consensus_sell - consensus_buy
        spread_pct = spread_abs / consensus_sell if consensus_sell > 0 else 0

        # Premium (domestic vs global converted)
        premium = None
        premium_pct = None
        if global_gold_vnd_per_luong:
            premium = consensus_sell - global_gold_vnd_per_luong
            premium_pct = premium / global_gold_vnd_per_luong if global_gold_vnd_per_luong > 0 else 0
            stats["with_premium"] += 1

        # Source count and dispersion
        source_count = len(buy_prices)
        if len(buy_prices) > 1:
            buy_std = _std(buy_prices)
            sell_std = _std(sell_prices)
            source_dispersion = (buy_std + sell_std) / 2
        else:
            source_dispersion = 0

        # Identify primary source
        primary = day_sources.get("sjc_official_history", list(day_sources.values())[0])

        enriched.append({
            "date": row_date,
            "buy_consensus": round(consensus_buy, 2),
            "sell_consensus": round(consensus_sell, 2),
            "mid_consensus": round(consensus_mid, 2),
            "spread_abs": round(spread_abs, 2),
            "spread_pct": round(spread_pct, 4),
            "global_gold_usd_oz": round(global_gold_usd, 2) if global_gold_usd else None,
            "usd_vnd": round(usd_vnd, 2) if usd_vnd else None,
            "global_gold_vnd_per_luong": round(global_gold_vnd_per_luong, 2) if global_gold_vnd_per_luong else None,
            "premium": round(premium, 2) if premium else None,
            "premium_pct": round(premium_pct, 4) if premium_pct else None,
            "source_count": source_count,
            "source_dispersion": round(source_dispersion, 2),
            "primary_source": primary.get("source", ""),
            "sources_active": ",".join(sorted(day_sources.keys())),
        })

    print(f"Enriched: {stats}")

    writer.write_dataset("gold_daily_enriched", enriched)
    gold_prices_dir = Path("data/lake/gold_prices")
    gold_prices_dir.mkdir(parents=True, exist_ok=True)
    if out_dir.resolve() != gold_prices_dir.resolve():
        DataLakeWriter(gold_prices_dir, formats=["csv"], flat=True).write_dataset("gold_daily_enriched", enriched)

    manifest = {
        "generated_at": date.today().isoformat(),
        "inputs": {
            "audited_dir": str(audited),
            "external_dir": str(external),
        },
        "stats": stats,
        "output_dataset": "gold_daily_enriched",
        "records": len(enriched),
    }
    (out_dir / "manifests" / "enrichment_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Output: {out_dir}/gold_daily_enriched.csv ({len(enriched)} rows)")
    return 0


def _median(values: list[float]) -> float:
    s = sorted(values)
    n = len(s)
    if n % 2 == 1:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return (sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5


def _prev_business_day(d: str) -> str:
    """Rough previous business day (skip weekends only)."""
    dt = datetime.strptime(d, "%Y-%m-%d").date()
    while dt.weekday() >= 5:
        dt -= timedelta(days=1)
    return dt.isoformat()


def _recent_dates(d: str, max_lookback: int = 5) -> list[str]:
    """Generate d, d-1, d-2, ... up to max_lookback days to carry forward closing prices over weekends/holidays."""
    dt = datetime.strptime(d, "%Y-%m-%d").date()
    return [(dt - timedelta(days=i)).isoformat() for i in range(max_lookback + 1)]


if __name__ == "__main__":
    raise SystemExit(build_premium_table(parse_args()))
