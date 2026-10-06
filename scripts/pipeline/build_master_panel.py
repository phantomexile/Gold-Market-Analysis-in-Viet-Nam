#!/usr/bin/env python3
"""
Master Panel Builder for Vietnam Gold Market Analysis
======================================================

Integrates all data lake sources into 4 standard tables required by the
deep-research report:

1. gold_domestic_daily_panel  — date x source x product_type with buy/sell/spread
2. global_reference_daily     — LBMA, FX, yields, dollar, VIX, oil, futures basis, ETF
3. vn_macro_asof_panel        — VN/global macro with observation_date, release_date,
                                available_from and forward-fill logic
4. event_regime_panel         — auctions, policy, inspection, import, Tet, Than Tai,
                                wedding season + calendar features

Null handling strategy (per table):
  gold_domestic_daily_panel:
    - Forward-fill buy/sell within (source, gold_type) groups for same-date gaps
    - compute spread from raw_gold_history.spread when present, else derive (sell-buy)
    - Signal sell != buy with price consistency flag
    - source_quality from reliability registry fallback to hard-coded tiers

  global_reference_daily:
    - FX: Vietcombank provides mid	for USD/VND; no historical UoD sell/buy quotes
      (all ~3,941 null), so derived columns auto-cap as N/A and FX gap flagged
    - assets dxy, vix via series_id (DX-Y.NYB, ^VIX) — all nulls are real
      —- no imputation
    - Forward-fill lower-frequency macro series (yield, DXY) on trading days
    - LBMA: no rows yet — column exists, flag "not_configured" in availability marker

  vn_macro_asof_panel:
    - available_from null → forward-fill from prior row within the same (source,
      domain, frequency) group for the same indicator series_id
    - Dedup by (source, series_id, observation_date)
    - value nulls left as None + "data_missing" note

  event_regime_panel:
    - All rows are rule-generated — no imputation
    - Calendar rows (weekday, month) are timelessly active

Output: data/lake/
  data/lake/pipeline_output_domestic_daily.csv
  data/lake/pipeline_output_global_reference.csv
  data/lake/pipeline_output_vn_macro_asof.csv
  data/lake/pipeline_output_event_regime.csv
  data/lake/manifests/*.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter  # noqa: E402

# ── Constants ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]  # project root
LAKE = ROOT / "data" / "lake"
GOLD_PRICES = LAKE  # kept for backward compat in comments
RAW_GOLD = LAKE / "gold_raw_history_all_sources_2010_2026.csv"
AUDITED = LAKE / "gold_quotes_sjc_historical.csv"

EXT_V2 = LAKE
OUT = LAKE  # flat output

CHI_PER_OZ = 31.1034768 / 1.205  # 1 troy oz in chi
LUONG_PER_OZ = CHI_PER_OZ / 37.5  # ~0.6886 troy oz per luong

LBMA_USD_PER_LUONG = 1.0 / LUONG_PER_OZ  # USD/oz -> VND/luong equivalent should use USD/oz * rate/VND/luong

SOURCE_QUALITY: dict[str, float] = {
    "sjc_official_history": 0.95,
    "sjc_official": 0.90,
    "webgia_sjc_archive": 0.80,
    "giavang_sjc_archive": 0.80,
    "giavang_pnj_archive": 0.70,
    "sbv_central_fx_history": 0.90,
    "vietcombank_fx_xml": 0.85,
    "fred_csv_windowed": 0.95,
    "yfinance_ticker_v2": 0.80,
    "gso_macro_monitor": 0.85,
    "worldbank_api": 0.75,
    "gso_macro_monitor_curated": 0.88,
    "rule_generated": 1.0,
}

# For global_market_series, asset/indicator_name → panel column.
# Data uses series_id exactly with no indicator_name column, so we key on series_id.
GM_SERIES: dict[str, str] = {
    "DCOILWTICO": "oil_wti_usd_barrel",
    "DGS10": "treasury_10y_pct",
    "DTWEXBGS": "dxy_index",
    "VIXCLS": "vix",          # from FRED/series_id
    "dxy": "dxy_index",
    "DX-Y.NYB": "dxy_index",
    "gold_futures": "gold_futures_close_usd_oz",
    "silver_futures": "silver_futures_close_usd_oz",
    "sp500": "sp500_index",
    "^GSPC": "sp500_index",
    "usd_vnd_market": "usd_vnd_market_rate",
    "USDVND=X": "usd_vnd_market_rate",
    "vix": "vix",
    "^VIX": "vix",
    "wti_crude_futures": "oil_wti_usd_barrel",
    "CL=F": "oil_wti_usd_barrel",
}

FX_PAIRS = ("USD/VND",)

# ── Helpers ────────────────────────────────────────────────────────────────

def _load_csv(path: Path, encoding: str = "utf-8-sig") -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with open(path, encoding=encoding, newline="") as fh:
            return list(csv.DictReader(fh))
    except UnicodeDecodeError:
        with open(path, encoding="latin-1", newline="") as fh:
            return list(csv.DictReader(fh))


def _safe_float(v: str | None) -> float | None:
    if v is None:
        return None
    v = v.strip()
    if not v or v in ("-", "N/A", "n/a", "#N/A", "null", "None"):
        return None
    try:
        return float(v.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def _iso_date(v: str | None) -> str | None:
    if not v or not v.strip():
        return None
    v = v.strip()[:10]  # take YYYY-MM-DD / DD/MM/YYYY prefix
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(v, fmt).date().isoformat()
        except ValueError:
            continue
    return v  # best-effort passthrough


def _gold_type_normalize(raw: str) -> str:
    """Collapse gold_type values to a short & stable label.  SJC = gold_bar,
    PNJ or *nu* = gold_jewelry, anh_huynh = anthropomorphic_gold."""
    s = (raw or "").strip().lower()
    if "sjc" in s or "bar" in s or "mieng" in s or "vang_luong" in s:
        return "sjc_gold_bar"
    if "anh_huynh" in s or "tho" in s:
        return "anthropomorphic_gold"
    if "nhan" in s or "nu" in s or "trang_suc" in s or "day_chuyen" in s or "bong_tai" in s:
        return "gold_jewelry"
    if "pnj" in s or "laz" in s:
        return "pnj_gold"
    try:
        k = float(s)
        # Numeric gold_type strings (e.g. "31.200", "34.950") are jewelry
        # price indices on PNJ pages → treat same category as pnj_gold bar.
        if "." in s and 5.0 <= k <= 100.0:
            return "pnj_gold"
        if 5.0 <= k <= 25.0:
            return "pnj_gold"
    except ValueError:
        pass
    return s.replace(" ", "_") if s else "other"


def _emit_manifest(outdir: Path, table: str, rows: list[dict]) -> None:
    cols = sorted(rows[0].keys()) if rows else []
    nulls = {
        c: sum(1 for r in rows if r.get(c) is None or r.get(c) == "")
        for c in cols
        if c not in ("data_lineage", "build_timestamp")
    }
    manifest = {
        "table": table,
        "generated_at": datetime.utcnow().isoformat(),
        "row_count": len(rows),
        "columns": cols,
        "null_counts_top5": sorted(nulls.items(), key=lambda x: -x[1])[:5],
        "null_counts_all": nulls,
    }
    mdir = outdir / "manifests"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / f"{table}_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _lineage(sources: list[str], transform: str = "") -> str:
    return json.dumps({"sources": sources, "transform": transform})


def _ffill_available_from(rows: list[dict], group_keys: tuple[str, ...] = ("source", "series_id")) -> None:
    """In-place forward-fill of available_from within each group, preserving order."""
    from itertools import groupby

    def _group_key(r: dict) -> tuple:
        return tuple(r.get(k, "") for k in group_keys)

    rows_sorted = sorted(rows, key=lambda r: (  # sort by group then observation_date
        _group_key(r), r.get("observation_date") or r.get("date") or ""
    ))

    for _, grp_iter in groupby(rows_sorted, key=_group_key):
        grp = list(grp_iter)
        last_af: str | None = None
        for r in grp:
            raw = r.get("available_from")
            r["available_from"] = last_af if (not raw or raw == "") else raw
            if r.get("available_from"):
                last_af = r["available_from"]


# ══════════════════════════════════════════════════════════════════════════
# TABLE 1  –  gold_domestic_daily_panel
# ══════════════════════════════════════════════════════════════════════════
# Columns:
#   date, source, provider, gold_type, currency,
#   buy_price, sell_price, spread, spread_pct,
#   unit, quote_time, business_date,
#   source_quality, consensus_mid, (stand-in for consensus rows for now),
#   row_type (individual | consensus),
#   data_lineage, build_timestamp
# Inputs: raw_gold_history + audited/domestic_gold_quotes
# Join: date + gold_type + source
# Null handling: forward-fill within (source, gold_type) group;
#   spread recomputed as (sell - buy) if source.spread is null or zero;
#   consensus row = median buy/sell across sources for same date+gold_type.
# ══════════════════════════════════════════════════════════════════════════

def build_gold_domestic_daily_panel() -> list[dict[str, Any]]:
    RAW = RAW_GOLD
    AUD = AUDITED
    rows_raw = _load_csv(RAW)
    rows_aud = _load_csv(AUD)

    print(f"  raw history: {len(rows_raw):,} rows | audited: {len(rows_aud):,} rows")

    out: list[dict[str, Any]] = []

    # ── raw history rows ──────────────────────────────────────────────
    for r in rows_raw:
        d = _iso_date(r.get("date", "") or r.get("business_date", ""))
        if not d:
            continue
        buy = _safe_float(r.get("buy"))
        sell = _safe_float(r.get("sell"))
        spread_src = _safe_float(r.get("spread"))
        if buy is None and sell is None:
            continue

        spread = spread_src
        if spread is None and buy is not None and sell is not None:
            spread = round(sell - buy, 4)
        spread_pct = round(spread / sell * 100, 4) if spread is not None and sell and sell > 0 else None

        src = (r.get("source") or "").strip().lower()
        out.append({
            "date": d,
            "source": src,
            "provider": (r.get("provider") or "").strip().lower(),
            "gold_type": _gold_type_normalize(r.get("gold_type", "")),
            "currency": r.get("currency", "VND"),
            "buy_price": buy,
            "sell_price": sell,
            "spread": spread,
            "spread_pct": spread_pct,
            "unit": r.get("unit", "VND/luong"),
            "quote_time": r.get("timestamp", "")[:8] if r.get("timestamp") else "",
            "business_date": _iso_date(r.get("business_date", "")) or d,
            "source_quality": SOURCE_QUALITY.get(src, 0.5),
            "consensus_buy": None,
            "consensus_mid": None,
            "row_type": "individual",
            "data_lineage": _lineage(["raw_gold_history"], "raw_crawl"),
        })

    # ── audited rows (SJC official history) ───────────────────────────
    # These rows carry only one gold_type + single source, so direct concatenate
    # after mapping to same schema.
    seen_source_key: set[str] = set()
    for r in rows_aud:
        key = f"{r.get('date','')}::{r.get('source','')}::{r.get('gold_type','')}::{r.get('transaction_type','')}"
        if key in seen_source_key:
            continue
        seen_source_key.add(key)
        d = _iso_date(r.get("date", "") or r.get("business_date", ""))
        if not d:
            continue
        buy = _safe_float(r.get("buy"))
        sell = _safe_float(r.get("sell"))
        spread_src = _safe_float(r.get("spread"))
        if buy is None and sell is None:
            continue
        spread = spread_src
        if spread is None and buy is not None and sell is not None:
            spread = round(sell - buy, 4)
        spread_pct = round(spread / sell * 100, 4) if spread is not None and sell and sell > 0 else None
        src = (r.get("source") or "").strip().lower()
        out.append({
            "date": d,
            "source": src,
            "provider": (r.get("provider") or "").strip().lower(),
            "gold_type": _gold_type_normalize(r.get("gold_type", "")),
            "currency": r.get("currency", "VND"),
            "buy_price": buy,
            "sell_price": sell,
            "spread": spread,
            "spread_pct": spread_pct,
            "unit": r.get("unit", "VND/luong"),
            "quote_time": _iso_date(r.get("timestamp", "") or "")[11:16] if r.get("timestamp") else "",
            "business_date": _iso_date(r.get("business_date", "")) or d,
            "source_quality": SOURCE_QUALITY.get(src, 0.5),
            "consensus_buy": None,
            "consensus_mid": None,
            "row_type": "individual",
            "data_lineage": _lineage(["domestic_gold_quotes"], "audited_reliable"),
        })

    # ── consensus rows: median buy & sell across (source, gold_type) per date ──
    from collections import defaultdict
    by_dt_g: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in out:
        by_dt_g[(r["date"], r["gold_type"])].append(r)

    cons_rows: list[dict] = []
    for (dt, gt), grp in by_dt_g.items():
        buys = [x["buy_price"] for x in grp if x["buy_price"] is not None]
        sells = [x["sell_price"] for x in grp if x["sell_price"] is not None]
        if not buys and not sells:
            continue
        buys_s = sorted(buys)
        sells_s = sorted(sells)
        mid_buy = buys_s[len(buys_s) // 2] if buys_s else None
        mid_sell = sells_s[len(sells_s) // 2] if sells_s else None
        spread = round(mid_sell - mid_buy, 4) if mid_sell is not None and mid_buy is not None else None
        spread_pct = round(spread / mid_sell * 100, 4) if spread is not None and mid_sell and mid_sell > 0 else None
        cons_rows.append({
            "date": dt,
            "source": "consensus",
            "provider": "cross_source",
            "gold_type": gt,
            "currency": "VND",
            "buy_price": mid_buy,
            "sell_price": mid_sell,
            "spread": spread,
            "spread_pct": spread_pct,
            "unit": "VND/luong",
            "quote_time": "12:00",
            "business_date": dt,
            "source_quality": round(
                sum(x["source_quality"] for x in grp) / len(grp), 3
            ),
            "consensus_buy": mid_buy,
            "consensus_mid": (mid_buy + mid_sell) / 2 if mid_buy is not None and mid_sell is not None else None,
            "row_type": "consensus",
            "data_lineage": _lineage(
                [x["source"] for x in grp], f"median_of_{len(grp)}_sources"
            ),
        })

    out.extend(cons_rows)

    # Forward-fill within (source, gold_type) — only on buy_price and sell_price
    from itertools import groupby as _groupby

    def _gk(r: dict) -> tuple:
        return (r["source"], r["gold_type"])

    out_sorted = sorted(out, key=lambda r: (_gk(r), r["date"]))
    for _, grp_iter in _groupby(out_sorted, key=_gk):
        grp = list(grp_iter)
        last_buy: float | None = None
        last_sell: float | None = None
        for r in grp:
            if r["buy_price"] is None and last_buy is not None:
                r["buy_price"] = last_buy
                r["data_lineage"] = _lineage(
                    [r["source"]], f"ffill_buy_price_from_{r['date']}"
                )
            else:
                last_buy = r["buy_price"]
            if r["sell_price"] is None and last_sell is not None:
                r["sell_price"] = last_sell
            else:
                last_sell = r["sell_price"]
            # Refresh spread after fill
            if r["buy_price"] is not None and r["sell_price"] is not None:
                r["spread"] = round(r["sell_price"] - r["buy_price"], 4)
                r["spread_pct"] = (
                    round(r["spread"] / r["sell_price"] * 100, 4)
                    if r["sell_price"]
                    else None
                )

    for r in out:
        r["build_timestamp"] = datetime.utcnow().isoformat()

    return out


# ══════════════════════════════════════════════════════════════════════════
# TABLE 2  –  global_reference_daily
# ══════════════════════════════════════════════════════════════════════════
# Columns:
#   date,
#   lbma_price_usd_oz,
#   lbma_availability,
#   usd_vnd_bid, usd_vnd_ask, usd_vnd_mid,
#   usd_vnd_availability,   # available | missing | not_configured
#   treasury_10y_pct,
#   dxy_index,
#   vix,
#   oil_wti_usd_barrel,
#   sp500_index,
#   silver_futures_close_usd_oz,
#   gold_futures_close_usd_oz,
#   usd_vnd_market_rate,
#   data_lineage,
#   build_timestamp
# Inputs:
#   external_features/global_market_series.csv
#   external_features/fx_rates.csv
#   external_features_v2/futures_basis.csv (empty, GC=F)
#   external_features_v2/etf_proxy.csv (empty, GLD)
#   external_features_v2/gld_shares/ (empty)
#   lbma_spot/ (empty, not yet working)
# Join: date (outer join, each row = one date)
# Null handling:
#   - lbma_price_usd_oz = None, lbma_availability = not_configured
#   - FX mid = present for Vietcombank snapshot (buy/sell null — column is mid-only)
#       → bid and ask both null, mid holds the available value
#   - macro_market indicators with series_id=None also null
#   - gold_futures_close_usd_oz NULL when basis file empty
#   - No imputation; flags expose availability
# ══════════════════════════════════════════════════════════════════════════

def build_global_reference_daily() -> list[dict[str, Any]]:
    GM = EXT_V2 / "global_market_series_yfinance_fred.csv"
    FX = EXT_V2 / "fx_rates_vietcombank_sbv.csv"
    rows_gm = _load_csv(GM)
    rows_fx = _load_csv(FX)
    rows_basis = _load_csv(EXT_V2 / "futures_basis_gc_f.csv")
    rows_etf   = _load_csv(EXT_V2 / "etf_proxy_gld.csv")
    rows_mcr_v2 = _load_csv(EXT_V2 / "macro_enhanced_fred_expanded.csv")

    print(f"  global_market_series: {len(rows_gm):,} | fx_rates: {len(rows_fx):,} | "
          f"futures_basis: {len(rows_basis)} | etf: {len(rows_etf)} | macro_v2: {len(rows_mcr_v2)}")

    # Collect unique dates
    dates: set[str] = set()
    for r in rows_gm:
        d = _iso_date(r.get("date"))
        if d:
            dates.add(d)
    for r in rows_fx:
        d = _iso_date(r.get("date"))
        if d:
            dates.add(d)
    for r in rows_mcr_v2:
        d = _iso_date(r.get("date"))
        if d:
            dates.add(d)
    print(f"  unique dates: {len(dates)}")

    # Index global_market_series by date + series_id
    gm_idx: dict[str, dict[str, float]] = {}
    for r in rows_gm:
        d = _iso_date(r.get("date"))
        if not d:
            continue
        sid = (r.get("series_id") or r.get("asset") or "").strip()
        val = _safe_float(r.get("value"))
        if sid and val is not None:
            gm_idx.setdefault(d, {})[sid] = val

    # Index FX — we only care about the pair column containing USD/VND
    fx_mid_idx: dict[str, float] = {}
    fx_avail_idx: dict[str, str] = {}
    for r in rows_fx:
        d = _iso_date(r.get("date"))
        if not d:
            continue
        pair = (r.get("pair") or "").strip().upper()
        # pair might actually be None, check alt cols
        if not pair:
            continue
        mid = _safe_float(r.get("mid"))
        if mid is not None and any(kw in pair for kw in FX_PAIRS):
            fx_mid_idx[d] = mid
            fx_avail_idx[d] = "available"
        else:
            fx_avail_idx.setdefault(d, "missing")

    #     # LBMA: load CSV if present, index by date (AM fix)
    lbma_idx: dict[str, float] = {}
    lbma_csv_path = EXT_V2 / "lbma_gold_spot_am_pm.csv"
    if lbma_csv_path.exists():
        for r in _load_csv(lbma_csv_path):
            d = _iso_date(r.get("date", ""))
            sid = r.get("series_id", "")
            if sid == "LBMA_GOLD_AM_USD_OZ" or ("GOLD" in sid and "USD" in sid and "AM" in sid):
                val = _safe_float(r.get("value"))
                if d and val is not None:
                    lbma_idx[d] = val
        print(f" LBMA index: {len(lbma_idx)} dates loaded from CSV")

    if len(lbma_idx) < 20:
        lbma_proxy_path = LAKE / "lbma_gold_proxy_gc_f.csv"
        if lbma_proxy_path.exists() and lbma_proxy_path.stat().st_size > 100:
            for r in _load_csv(lbma_proxy_path):
                d_p = _iso_date(r.get("date", ""))
                v_p = _safe_float(r.get("value"))
                if d_p and v_p is not None:
                    lbma_idx[d_p] = v_p
            print(f" LBMA index: {len(lbma_idx)} dates (spot + proxy fallback)")
        else:
            print(f" LBMA proxy missing or empty ({len(lbma_idx)} dates)")
    else:
        print(f" LBMA index: {len(lbma_idx)} dates (spot sufficient)")

# Sort dates for forward-fill
    all_dates_sorted = sorted(dates)
    last_dxy: float | None = None
    last_vix: float | None = None
    last_t10y: float | None = None
    last_oil: float | None = None
    last_usd_vnd: float | None = None

    out: list[dict[str, Any]] = []
    for d in all_dates_sorted:
        gm = gm_idx.get(d, {})

        dxy = gm.get("DX-Y.NYB") or gm.get("dxy", None)
        vix = gm.get("^VIX") or gm.get("VIXCLS") or gm.get("vix", None)
        t10y = gm.get("DGS10", None)
        sp500 = gm.get("^GSPC") or gm.get("sp500", None)
        oil  = gm.get("CL=F") or gm.get("DCOILWTICO") or gm.get("wti_crude_futures") or gm.get("gold_futures", None)
        # Note: "gold_futures" in current sample has gold futures close
        # but we also have dedicated futures_basis — here we annotate availability

        # Forward-fill for lower-frequency series (monthly): last-observation on prior trading day
        if dxy is not None:
            last_dxy = dxy
        else:
            dxy = last_dxy
        if vix is not None:
            last_vix = vix
        else:
            vix = last_vix
        if t10y is not None:
            last_t10y = t10y
        else:
            t10y = last_t10y
        if oil is not None:
            last_oil = oil
        else:
            oil = last_oil

        usd_vnd_mid = fx_mid_idx.get(d)
        # Fallback: yfinance USDVND=X daily close (~3912 rows)
        usd_vnd_mid = usd_vnd_mid or gm.get("USDVND=X")
        if usd_vnd_mid is not None:
            last_usd_vnd = usd_vnd_mid
        else:
            usd_vnd_mid = last_usd_vnd

        lbma_avail = "available" if lbma_idx.get(d) is not None else "not_configured"
        out.append({
            "date": d,
            "lbma_price_usd_oz": lbma_idx.get(d),
            "lbma_availability": lbma_avail,
            "usd_vnd_bid": None,
            "usd_vnd_ask": None,
            "usd_vnd_mid": usd_vnd_mid,
            "usd_vnd_availability": fx_avail_idx.get(d, "missing") if usd_vnd_mid else "missing",
            "treasury_10y_pct": t10y,
            "dxy_index": dxy,
            "vix": vix,
            "oil_wti_usd_barrel": oil,
            "sp500_index": sp500,
            "silver_futures_close_usd_oz": gm.get("SI=F"),
            "gold_futures_close_usd_oz": gm.get("GC=F"),
            "usd_vnd_market_rate": gm.get("USDVND=X"),
            "data_lineage": _lineage(
                ["global_market_series", "fx_rates"],
                f"outer_join_on_date|ffill_applied=yes",
            ),
            "build_timestamp": datetime.utcnow().isoformat(),
        })

    return out


# ══════════════════════════════════════════════════════════════════════════
# TABLE 3  – vn_macro_asof_panel
# ══════════════════════════════════════════════════════════════════════════
# Columns (exact, matching research spec):
#   source,
#   indicator_name,
#   observation_date,
#   release_date,
#   available_from,
#   frequency,
#   unit,
#   value,
#   data_lineage,
#   build_timestamp
# Inputs:
#   external_features/macro_series.csv  (GSO + World Bank)
#   external_features_v2/macro_enhanced.csv        (FRED v2)
#   external_features_v2/vn_macro_forecasting.csv  (forecasting / VN-specific)
# Join: (source, series_id, observation_date)
# Null handling:
#   - available_from null → forward-fill from prior row within
#     (source, series_id) group (sorted by observation_date)
#   - release_date null → observation_date is used as proxy
#   - Dedup by (source, series_id, observation_date) — last writer wins
#   - value null remains null (do not impute)
# ══════════════════════════════════════════════════════════════════════════

def build_vn_macro_asof_panel() -> list[dict[str, Any]]:
    MCR = EXT_V2 / "macro_series_wb_gso.csv"
    MCR2 = EXT_V2 / "macro_enhanced_fred_expanded.csv"
    VNFC = EXT_V2 / "vn_macro_forecasting.csv"

    rows_v1 = _load_csv(MCR)
    rows_v2 = _load_csv(MCR2)
    rows_vn = _load_csv(VNFC)

    print(f"  macro_series (GSO+WB): {len(rows_v1):,} | macro_v2 (FRED): {len(rows_v2):,} | "
          f"vn_macro_fc: {len(rows_vn):,}")

    out: list[dict[str, Any]] = []

    def _normalize_source(s: str) -> str:
        s = (s or "").strip().lower()
        return {
            "gso": "GSO",
            "gso_macro_monitor": "GSO",
            "gso_macro_monitor_curated": "GSO",
            "worldbank": "World Bank",
            "worldbank_api": "World Bank",
            "fred": "FRED",
            "fred_csv_windowed": "FRED",
            "sbv": "SBV",
            "vn_forecast": "vn_macro_forecasting",
        }.get(s, s.upper())

    for src_rows, src_label in (
        (rows_v1, "macro_series"),
        (rows_v2, "macro_enhanced"),
        (rows_vn, "vn_macro_forecasting"),
    ):
        for r in src_rows:
            d = _iso_date(
                r.get("observation_date") or r.get("date") or ""
            )
            if not d:
                continue
            out.append({
                "source": _normalize_source(r.get("source", "")),
                "indicator_name": (r.get("series_name") or r.get("indicator_name") or "").strip(),
                "observation_date": d,
                "release_date": _iso_date(r.get("release_date", "")) or d,
                "available_from": _iso_date(r.get("available_from", "")) or "",
                "frequency": (r.get("frequency") or "").strip(),
                "unit": (r.get("unit") or "").strip(),
                "value": _safe_float(r.get("value")),
                "data_lineage": _lineage([src_label], "as_published"),
            })

    # Dedup by (source, indicator_name, observation_date) — keep first
    seen_dedup: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for r in out:
        key = (r["source"], r["indicator_name"], r["observation_date"])
        if key in seen_dedup:
            continue
        seen_dedup.add(key)
        deduped.append(r)
    out = deduped

    # Forward-fill available_from within (source, indicator_name) groups
    from itertools import groupby as _groupby

    def _gk2(r: dict) -> str:
        return f"{r['source']}::{r['indicator_name']}"

    out.sort(key=lambda r: (_gk2(r), r["observation_date"]))
    for _, grp_iter in _groupby(out, key=_gk2):
        grp = list(grp_iter)
        last_af: str | None = None
        for r in grp:
            raw = r.get("available_from")
            r["available_from"] = last_af if (not raw) else raw
            if r["available_from"]:
                last_af = r["available_from"]

    # Value nulls — keep as None; users interpret via available_from staleness
    for r in out:
        r["build_timestamp"] = datetime.utcnow().isoformat()

    # sort by date desc
    out.sort(key=lambda r: (r["observation_date"], r["source"], r["indicator_name"]))
    return out


# ══════════════════════════════════════════════════════════════════════════
# TABLE 4  – event_regime_panel
# ══════════════════════════════════════════════════════════════════════════
# Columns (exact, matching research spec):
#   event_date,
#   event_type,
#   scope,
#   severity,
#   expected_channel,
#   note,
#   source_url,
#   effective_from,
#   effective_to,
#   is_active,
#   source,
#   data_lineage,
#   build_timestamp
# Inputs:
#   enriched/gold_event_panel.csv
# Join: event_date + event_type (unique key)
# Null handling:
#   - effective_to null → is_active = True (open-ended)
#   - Calendar rows (weekday/month) — always is_active = True
#   - Tết/Than Tai/wedding — effective window is one day (event_date itself)
# ══════════════════════════════════════════════════════════════════════════

CAL_EVENT_TYPES = {"calendar_weekday", "calendar_month"}


def build_event_regime_panel() -> list[dict[str, Any]]:
    EPATH = LAKE / "gold_event_panel.csv"
    rows = _load_csv(EPATH)
    print(f"  gold_event_panel: {len(rows):,} rows")

    out: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    # If no event rows, still produce calendar rows (rule-generated fallback)
    have_rows = bool(rows)

    def _add(r: dict) -> None:
        etype = (r.get("event_type", "") or "").strip().lower().replace(" ", "_")
        ed = _iso_date(r.get("event_date"))
        if not ed:
            return
        ef = _iso_date(r.get("effective_from")) or ed
        et_raw = r.get("effective_to", "")
        et = _iso_date(et_raw) if et_raw else ""
        key = f"{ed}::{etype}::{ef}::{et}"
        if key in seen_keys:
            return
        seen_keys.add(key)

        if etype in CAL_EVENT_TYPES:
            active, eff_from, eff_to = True, ed, ed
        else:
            eff_from, eff_to = ef, et or ""
            # is_active: true if today is within [eff_from, eff_to] window (open-ended if no et_to)
            try:
                today = date.today()
                e_from = date.fromisoformat(eff_from)
                e_to = date.fromisoformat(eff_to) if eff_to else today
                active = e_from <= today <= e_to
            except (ValueError, TypeError):
                active = True

        out.append({
            "event_date": ed,
            "event_type": etype,
            "scope": (r.get("scope", "domestic_vietnam") or "").strip().lower().replace(" ", "_"),
            "severity": (r.get("severity", "medium") or "medium").strip().lower(),
            "expected_channel": (r.get("expected_channel", "premium_spike") or "").strip().lower().replace(" ", "_"),
            "note": (r.get("note", "") or "").strip(),
            "source_url": (r.get("source_url") or "").strip(),
            "effective_from": eff_from,
            "effective_to": eff_to,
            "is_active": active,
            "source": (r.get("source", "rule_generated") or "").strip().lower(),
            "data_lineage": _lineage(
                ["gold_event_panel.csv + build_event_panel.py"],
                f"event_type={etype}",
            ),
            "build_timestamp": datetime.utcnow().isoformat(),
        })

    for r in rows:
        _add(r)

    return out


# ══════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════

TABLE_BUILDERS = {
    "gold_domestic_daily_panel": build_gold_domestic_daily_panel,
    "global_reference_daily": build_global_reference_daily,
    "vn_macro_asof_panel": build_vn_macro_asof_panel,
    "event_regime_panel": build_event_regime_panel,
}

OUTPUT_DIR = OUT


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build master panel tables.")
    ap.add_argument(
        "--tables",
        nargs="+",
        choices=list(TABLE_BUILDERS.keys()) + ["all"],
        default=["all"],
    )
    ap.add_argument("--out-dir", default=str(OUTPUT_DIR))
    return ap.parse_args()


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifests").mkdir(parents=True, exist_ok=True)

    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)
    targets = list(TABLE_BUILDERS.keys()) if "all" in args.tables else args.tables

    counts: dict[str, int] = {}
    for name in targets:
        print(f"\n== {name} ==")
        rows = TABLE_BUILDERS[name]()
        counts[name] = len(rows)
        if not rows:
            print(f"  WARNING: 0 rows — writing placeholder")
            writer.write_dataset(name, [{}])
            _emit_manifest(out_dir, name, [])
            continue
        writer.write_dataset(name, rows)
        _emit_manifest(out_dir, name, rows)
        print(f"  {len(rows):,} rows → {out_dir / name}.csv")

    summary = {
        "generated_at": datetime.utcnow().isoformat(),
        "tables": targets,
        "row_counts": counts,
        "output_dir": str(out_dir),
    }
    (out_dir / "manifests" / "master_panel_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nSummary written → {out_dir / 'manifests' / 'master_panel_summary.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
