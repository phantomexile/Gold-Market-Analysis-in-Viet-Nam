#!/usr/bin/env python3
"""Audit helpers for the data lake.

Subcommands
-----------
audit_fx           Inspect fx_rates.csv structure (sources, pairs, SBV vs VCB).
audit_fx_source    Verify which FX source is used per enriched gold row.
audit_premium      Premium distribution by year, unit consistency, GC=F check.
audit_enriched     Full gap analysis: enriched, event panel, FRED v2, futures, ETF, FX.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).resolve().parent
_ROOT = _SCRIPT_DIR.parent.parent
_V1 = _ROOT / "data" / "lake" / "market_data" / "v1" / "normalized"
_V2 = _ROOT / "data" / "lake" / "market_data" / "v2" / "normalized"
_ENR = _ROOT / "data" / "lake"
_AUD = _ROOT / "data" / "lake" / "gold_quotes_sjc_historical.csv"


# ── helpers ───────────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ── subcommands ───────────────────────────────────────────────────────────────
def audit_fx(_args: argparse.Namespace) -> None:
    """Inspect FX rates structure: sources, quote types, SBV vs VCB details."""
    rows = _read_csv(_V1 / "fx_rates.csv")
    print("FX columns:", list(rows[0].keys()))
    combo = Counter((r["source"], r.get("quote_type", ""), r.get("pair", "")) for r in rows)
    for k, v in sorted(combo.items()):
        print(f"  {k}: {v} rows")

    for src_label in ("sbv_central_fx_history", "vietcombank_fx_xml"):
        subset = [r for r in rows if r["source"] == src_label]
        if not subset:
            continue
        r0 = subset[0]
        print(f"\n{src_label}: buy={r0['buy']}, sell={r0['sell']}, mid={r0['mid']}, "
              f"pair={r0['pair']}, qt={r0.get('quote_type','')}")
        print(f"  date range: {min(r['date'] for r in subset)} -> {max(r['date'] for r in subset)}")
        for r in subset[:3]:
            print(f"  row: date={r['date']}, pair={r['pair']}, buy={r['buy']}, "
                  f"sell={r['sell']}, mid={r['mid']}")

    usd = [r for r in rows if "USD" in r.get("pair", "")]
    pairs = Counter(r["pair"] for r in usd)
    print(f"\nUSD/VND rows: {len(usd)}, pairs: {dict(pairs)}")


def audit_fx_source(_args: argparse.Namespace) -> None:
    """Verify which FX source is used per enriched gold row and cross-check SBV vs yfinance."""
    enriched = _read_csv(_ENR / "pipeline_output_premium_enriched.csv")
    fx_rows = _read_csv(_V1 / "fx_rates.csv")
    gms_rows = _read_csv(_V1 / "global_market_series.csv")

    sbv = {r["date"]: float(r["mid"]) for r in fx_rows
           if r["source"] == "sbv_central_fx_history" and r.get("mid")}
    usdvnd = {r["date"][:10]: float(r["value"]) for r in gms_rows
              if r["series_id"] == "USDVND=X" and r.get("value")}

    print(f"SBV USD/VND dates: {len(sbv)}")
    print(f"yfinance USDVND=X dates: {len(usdvnd)}")
    common = sorted(set(sbv) & set(usdvnd))
    print(f"Common dates: {len(common)}")
    if common:
        diffs = [abs(sbv[d] - usdvnd[d]) for d in common]
        print(f"  max diff: {max(diffs):.4f}, avg diff: {sum(diffs)/len(diffs):.4f}")
        for d in common[:5]:
            print(f"  {d}: SBV={sbv[d]:.2f}, yf={usdvnd[d]:.2f}")

    fx_sources = Counter()
    for r in enriched:
        d = r["date"]
        if d in sbv:
            fx_sources["sbv_central"] += 1
        elif d in usdvnd:
            fx_sources["yfinance_USDVND=X_fallback"] += 1
        else:
            fx_sources["none"] += 1
    for k, v in sorted(fx_sources.items()):
        print(f"  {k}: {v} rows ({100*v/len(enriched):.1f}%)")
    print(f"  date range: {min(r['date'] for r in enriched)} -> {max(r['date'] for r in enriched)}")


def audit_premium(_args: argparse.Namespace) -> None:
    """Premium distribution, unit consistency, GC=F source check, FX coverage."""
    enriched = _read_csv(_ENR / "pipeline_output_premium_enriched.csv")

    # ── A1: distribution by year ──────────────────────────────────────────────
    print("=" * 70)
    print("A1. PREMIUM DISTRIBUTION BY YEAR")
    print("=" * 70)
    year_data: dict[str, list[float]] = defaultdict(list)
    for r in enriched:
        if r.get("premium") not in (None, "", "None"):
            year_data[r["date"][:4]].append(float(r["premium"]))
    for y in sorted(year_data):
        v = year_data[y]
        print(f"  {y}: n={len(v):3d}, median={statistics.median(v):>15,.0f}, "
              f"mean={sum(v)/len(v):>15,.0f}, min={min(v):>15,.0f}, max={max(v):>15,.0f}")

    # ── A2: unit check ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("A2. UNIT CONSISTENCY CHECK (first valid row)")
    print("=" * 70)
    for r in enriched:
        if r.get("premium") in (None, "", "None"):
            continue
        g_usd = float(r["global_gold_usd_oz"])
        fx = float(r["usd_vnd"])
        stored = float(r["global_gold_vnd_per_luong"])
        computed = g_usd * fx / 25.807 * 37.5
        buy = float(r["buy_consensus"])
        sell = float(r["sell_consensus"])
        mid = float(r["mid_consensus"])
        prem = float(r["premium"])
        print(f"  {r['date']}: gold={g_usd:.1f}*{fx:.1f} -> {stored:,.0f} (computed={computed:,.0f}) match={abs(computed-stored)<1}")
        print(f"  buy={buy:,.0f}, sell={sell:,.0f}, mid={mid:,.0f}")
        print(f"  premium_stored={prem:>15,.0f}  premium_mid_calc={mid-stored:>15,.0f}  premium_sell_vs_global={sell-stored:>15,.0f}")
        print(f"  spread={float(r['spread_abs']):>12,.0f} VND ({float(r['spread_pct'])*100:.3f}%)")
        break

    # ── A3: global gold source ────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("A3. GLOBAL GOLD SOURCE (GC=F check)")
    print("=" * 70)
    try:
        gc_rows = [r for r in _read_csv(_V1 / "global_market_series.csv") if r["series_id"] == "GC=F"]
        print(f"  GC=F rows in v1: {len(gc_rows)}")
        if gc_rows:
            print(f"  columns: {list(gc_rows[0].keys())}")
    except FileNotFoundError:
        print("  global_market_series.csv not found")

    # ── A4: FX coverage ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("A4. FX COVERAGE FOR GOLD DATES")
    print("=" * 70)
    gold_dates = {r["date"] for r in enriched}
    try:
        fx_all = _read_csv(_V1 / "fx_rates.csv")
        usd_fx = {r["date"] for r in fx_all if r["pair"] == "USD/VND" and r["source"] == "sbv_central_fx_history"}
        covered = gold_dates & usd_fx
        print(f"  gold dates: {len(gold_dates)}, SBV USD/VND dates: {len(usd_fx)}")
        print(f"  overlap: {len(covered)}, missing: {len(gold_dates - usd_fx)}")
    except FileNotFoundError:
        print("  fx_rates.csv not found")

    # ── A5: macro v1 content ──────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("A5. MACRO DATA CHECK (v1 macro_series)")
    print("=" * 70)
    try:
        macro = _read_csv(_V1 / "macro_series.csv")
        series: dict[str, int] = {}
        for r in macro:
            sid = r.get("series_id", r.get("asset", ""))
            series[sid] = series.get(sid, 0) + 1
        print(f"  total rows: {len(macro)}, series: {len(series)}")
        for s, c in sorted(series.items(), key=lambda x: -x[1])[:10]:
            print(f"    {s}: {c}")
    except FileNotFoundError:
        print("  macro_series.csv not found")


def audit_enriched(_args: argparse.Namespace) -> None:
    """Full gap analysis across enriched, event panel, FRED v2, futures, ETF, FX, audited."""
    # ── 1. enriched overview ──────────────────────────────────────────────────
    print("=" * 70)
    print("1. pipeline_output_premium_enriched.csv — PREMIUM DECOMPOSITION")
    print("=" * 70)
    enriched = _read_csv(_ENR / "pipeline_output_premium_enriched.csv")
    dates = sorted(r["date"] for r in enriched)
    print(f"  date range: {dates[0]} -> {dates[-1]} ({len(dates)} unique)")
    print(f"  total rows: {len(enriched)}, columns: {list(enriched[0].keys())}")
    has_prem = [r for r in enriched if r.get("premium") not in (None, "", "None")]
    prems = [float(r["premium"]) for r in has_prem]
    spreads = [float(r["spread_pct"]) for r in enriched if r.get("spread_pct")]
    print(f"  premium coverage: {len(has_prem)}/{len(enriched)} ({100*len(has_prem)/len(enriched):.1f}%)")
    print(f"  premium: median={statistics.median(prems):,.0f}, min={min(prems):,.0f}, max={max(prems):,.0f}")
    if spreads:
        print(f"  spread %: median={statistics.median(spreads)*100:.3f}%, max={max(spreads)*100:.3f}%")
    sells = [float(r["sell_consensus"]) for r in enriched]
    print(f"  sell range: {min(sells):,.0f} -> {max(sells):,.0f} VND/luong")

    r0 = enriched[0]
    print(f"\n  sample row: date={r0['date']}, source={r0['primary_source']}")
    print(f"    buy={r0['buy_consensus']}, sell={r0['sell_consensus']}, mid={r0['mid_consensus']}")
    print(f"    global_usd_oz={r0['global_gold_usd_oz']}, usd_vnd={r0['usd_vnd']}")
    print(f"    global_vnd/luong={r0['global_gold_vnd_per_luong']}, premium={r0['premium']}")
    g_usd = float(r0["global_gold_usd_oz"])
    fx = float(r0["usd_vnd"])
    computed = g_usd * fx / 25.807 * 37.5
    stored = float(r0["global_gold_vnd_per_luong"])
    print(f"    unit check: {g_usd}*{fx}/25.807*37.5 = {computed:,.0f} (stored {stored:,.0f}) match={abs(computed-stored)<1}")

    # ── 2. event panel ────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("2. gold_event_panel.csv — EVENT PANEL")
    print("=" * 70)
    try:
        events = _read_csv(_ENR / "gold_event_panel.csv")
        types: dict[str, int] = {}
        for e in events:
            types[e["event_type"]] = types.get(e["event_type"], 0) + 1
        print(f"  total events: {len(events)}")
        for t, c in sorted(types.items()):
            print(f"    {t}: {c}")
        print(f"  columns: {list(events[0].keys())}")
    except FileNotFoundError:
        print("  NOT FOUND")

    # ── 3. FRED v2 ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("3. macro_enhanced.csv — FRED v2")
    print("=" * 70)
    try:
        macro_v2 = _read_csv(_V2 / "macro_enhanced.csv")
        series_v2: dict[str, int] = {}
        for r in macro_v2:
            series_v2[r["series_id"]] = series_v2.get(r["series_id"], 0) + 1
        print(f"  total rows: {len(macro_v2)}, series: {len(series_v2)}")
        print(f"  columns: {list(macro_v2[0].keys())}")
        required = ["DFII10", "DGS10", "T10YIE", "T5YIE", "VIXCLS", "DTWEXBGS",
                     "STLFSI2", "NFCI", "BAA10Y", "AAA10Y", "M2SL", "DCOILWTICO"]
        for s in required:
            status = "OK(v2)" if s in series_v2 else "MISSING"
            print(f"    {s}: {status}")
        rt = sum(1 for r in macro_v2 if r.get("realtime_start"))
        print(f"  realtime_start coverage: {rt}/{len(macro_v2)} ({100*rt/len(macro_v2):.0f}%)")
        print(f"  release_date column: {'present' if 'release_date' in macro_v2[0] else 'MISSING'}")
    except FileNotFoundError:
        print("  NOT FOUND")

    # ── 4. futures ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("4. futures_basis.csv — GOLD FUTURES")
    print("=" * 70)
    try:
        fut = _read_csv(_V2 / "futures_basis.csv")
        req_fut = ["gc_front", "gc_next", "basis_pct", "calendar_spread",
                    "roll_yield", "open_interest", "volume"]
        print(f"  rows: {len(fut)}, columns: {list(fut[0].keys())}")
        for c in req_fut:
            print(f"    {c}: {'PRESENT' if c in fut[0] else 'MISSING'}")
    except FileNotFoundError:
        print("  NOT FOUND")

    # ── 5. ETF ────────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("5. etf_proxy.csv — GLD ETF")
    print("=" * 70)
    try:
        etf = _read_csv(_V2 / "etf_proxy.csv")
        print(f"  rows: {len(etf)}, columns: {list(etf[0].keys())}")
        if etf:
            print(f"  note: {etf[0].get('note', 'N/A')}")
    except FileNotFoundError:
        print("  NOT FOUND")

    # ── 6. FX summary ─────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("6. fx_rates.csv — USD/VND")
    print("=" * 70)
    try:
        fx_rows = _read_csv(_V1 / "fx_rates.csv")
        sources = Counter(r["source"] for r in fx_rows)
        print(f"  rows: {len(fx_rows)}, sources: {dict(sources)}")
        print(f"  columns: {list(fx_rows[0].keys())}")
        print(f"  date range: {min(r['date'] for r in fx_rows)} -> {max(r['date'] for r in fx_rows)}")
        for src in sources:
            s = next(r for r in fx_rows if r["source"] == src)
            print(f"    [{src}] buy={s.get('buy')}, sell={s.get('sell')}, mid={s.get('mid')}")
    except FileNotFoundError:
        print("  NOT FOUND")

    # ── 7. audited ────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("7. audited/gold_quotes_sjc_historical.csv")
    print("=" * 70)
    try:
        aud = _read_csv(_AUD / "gold_quotes_sjc_historical.csv")
        src_counts = Counter(r["source"] for r in aud)
        print(f"  rows: {len(aud)}, sources: {dict(src_counts)}")
        print(f"  date range: {min(r['date'] for r in aud)} -> {max(r['date'] for r in aud)}")
        r0 = aud[0]
        print(f"  sample: currency={r0['currency']}, unit={r0['unit']}, "
              f"buy={r0['buy']}, sell={r0['sell']}, gold_type={r0.get('gold_type','?')}")
    except FileNotFoundError:
        print("  NOT FOUND")


def main() -> None:
    parser = argparse.ArgumentParser(description="Data-lake audit subcommands")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, fn in (("audit_fx", audit_fx),
                     ("audit_fx_source", audit_fx_source),
                     ("audit_premium", audit_premium),
                     ("audit_enriched", audit_enriched)):
        p = sub.add_parser(name, help=fn.__doc__)
        p.set_defaults(run=fn)

    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
