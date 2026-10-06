#!/usr/bin/env python3
"""
Enhanced external features collector (v2).

FRED JSON API: DFII10, T10YIE, T5YIE, STLFSI2, NFCI, BAA10Y, AAA10Y, M2SL,
DGS10, VIXCLS, DTWEXBGS, DCOILWTICO, GLD.

yfinance Ticker: GLD ETF, GC=F futures, GLD shares outstanding (SEC XBRL + snapshot).

crawl4ai: LBMA Gold Fix (intercepts Next.js data fetch).

SBV/NHNN interest-rate sources must be discovered with Playwright first.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import sys
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import request as _url_request, error as _url_error, parse as _url_parse

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.full_pipeline import DataLakeWriter

# ---------------------------------------------------------------------------
# FRED series mapping
# ---------------------------------------------------------------------------
ENHANCED_FRED_SERIES: dict[str, tuple[str, str]] = {
    "DGS10": ("us_10y_nominal", "pct"),
    "DCOILWTICO": ("wti_crude", "usd_barrel"),
    "VIXCLS": ("vix", "index"),
    "DTWEXBGS": ("dxy_broad", "index"),
    "DFII10": ("us_10y_real_tips_yield", "pct"),
    "T10YIE": ("us_10y_breakeven_inflation", "pct"),
    "T5YIE": ("us_5y_breakeven_inflation", "pct"),
    "STLFSI2": ("st_louis_financial_stress", "index"),
    "NFCI": ("chicago_fed_national_fin_conditions", "index"),
    "BAA10Y": ("baa_corp_bond_yield", "pct"),
    "AAA10Y": ("aaa_corp_bond_yield", "pct"),
    "M2SL": ("m2_money_supply", "billions_usd"),
    "GLD": ("gld_spdr_gold_etf_close", "usd"),
}

FRED_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# FRED collector via JSON API
# ---------------------------------------------------------------------------
def collect_enhanced_fred(start: str, end: str) -> list[dict[str, Any]]:
    api_key = os.environ.get("FRED_API_KEY", "")
    if not api_key:
        print(" FRED: No FRED_API_KEY found, skipping")
        return []
    rows: list[dict[str, Any]] = []
    for series_id, (asset, unit) in ENHANCED_FRED_SERIES.items():
        url = (
            "https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}&file_type=json&api_key={api_key}"
            f"&observation_start={start}&observation_end={end}"
            "&limit=50000&sort_order=asc"
        )
        try:
            req = _url_request.Request(
                url,
                headers={"User-Agent": FRED_USER_AGENT, "Accept": "application/json"},
            )
            with _url_request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                payload = json.loads(raw.decode("utf-8", errors="replace"))
                raw_hash = hashlib.sha256(raw).hexdigest()
        except _url_error.HTTPError as exc:
            print(f" FRED {series_id}: HTTP {exc.code} - {exc.reason}")
            continue
        except Exception as exc:
            print(f" FRED {series_id}: {type(exc).__name__}: {exc}")
            continue
        if "error_message" in payload:
            print(f" FRED {series_id}: API error - {payload['error_message']}")
            continue
        obs_count = 0
        for item in payload.get("observations", []):
            val = item.get("value", "")
            if val in ("", ".", None):
                continue
            try:
                value = float(val)
            except ValueError:
                continue
            obs_date = item.get("date", "")
            if not obs_date:
                continue
            rows.append(
                {
                    "date": obs_date[:10],
                    "series_id": series_id,
                    "asset": asset,
                    "value": value,
                    "unit": unit,
                    "source": "fred_json_v2",
                    "raw_hash": raw_hash,
                    "available_from": item.get("realtime_start", obs_date[:10]),
                }
            )
            obs_count += 1
        print(f" FRED {series_id}: {obs_count} observations")
    return rows

# ---------------------------------------------------------------------------
# yfinance Ticker-based collector
# ---------------------------------------------------------------------------
def _collect_yfinance_ticker(
    symbol: str, asset_name: str, start: str, end: str
) -> list[dict[str, Any]]:
    import yfinance as yf
    rows: list[dict[str, Any]] = []
    ticker = yf.Ticker(symbol)
    end_excl = (
        datetime.strptime(end, "%Y-%m-%d").date() + timedelta(days=1)
    ).isoformat()
    frame = ticker.history(
        start=start, end=end_excl, auto_adjust=False, repair=False
    )
    if frame.empty:
        return rows
    for idx, row in frame.iterrows():
        d = idx.date().isoformat()
        close_v = row.get("Close")
        if close_v is None:
            continue
        rows.append(
            {
                "date": d,
                "series_id": symbol,
                "asset": asset_name,
                "value": round(float(close_v), 4),
                "open": round(float(row["Open"]), 4) if row.get("Open") is not None else None,
                "high": round(float(row["High"]), 4) if row.get("High") is not None else None,
                "low": round(float(row["Low"]), 4) if row.get("Low") is not None else None,
                "volume": round(float(row["Volume"]), 0) if row.get("Volume") is not None else None,
                "unit": "usd_per_share",
                "source": "yfinance_ticker_v2",
                "note": "no_shares_outstanding",
                "available_from": (
                    datetime.strptime(d, "%Y-%m-%d").date() + timedelta(days=1)
                ).isoformat(),
            }
        )
    return rows

def collect_gld_etf(start: str, end: str) -> list[dict[str, Any]]:
    return _collect_yfinance_ticker("GLD", "gld_spdr_gold_etf", start, end)

def collect_gc_futures(start: str, end: str) -> list[dict[str, Any]]:
    return _collect_yfinance_ticker("GC=F", "gold_futures_front_continuous", start, end)

def collect_gold_futures_basis(start: str, end: str) -> list[dict[str, Any]]:
    return collect_gc_futures(start, end)

# ---------------------------------------------------------------------------
# LBMA Gold Fix — intercept Next.js RSC payload via JS hook
# ---------------------------------------------------------------------------
def collect_lbma_gold_price() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        from crawl4ai import AsyncWebCrawler, CacheMode
    except ImportError:
        print(" LBMA: crawl4ai not installed, skipping")
        return rows

    async def _crawl() -> None:
        async with AsyncWebCrawler(
            headless=True, cache_mode=CacheMode.BYPASS
        ) as crawler:
            url = "https://www.lbma.org.uk/lbma-gold-price-data"
            try:
                r = await crawler.arun(
                    url=url,
                    word_count_threshold=1,
                    page_timeout=30_000,
                    js_code="""
                        // Intercept fetch() calls and capture price data API responses
                        window._lbmaPriceData = null;
                        window._lbmaApiUrls = [];
                        const origFetch = window.fetch;
                        window.fetch = function(...args) {
                            const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
                            if (url.includes('price') || url.includes('gold') || url.includes('data')) {
                                window._lbmaApiUrls.push(url);
                            }
                            return origFetch.apply(this, args).then(resp => {
                                if (url.includes('price') || url.includes('gold') || resp.status === 200) {
                                    const clone = resp.clone();
                                    clone.text().then(t => {
                                        try {
                                            const j = JSON.parse(t);
                                            if (j && (j.gold || j.prices || j.data || j.results)) {
                                                window._lbmaPriceData = j;
                                            }
                                        } catch(e) {}
                                    }).catch(() => {});
                                }
                                return resp;
                            });
                        };
                        // Also intercept XMLHttpRequest
                        const origOpen = XMLHttpRequest.prototype.open;
                        XMLHttpRequest.prototype.open = function(m, u) {
                            this._url = u;
                            return origOpen.apply(this, arguments);
                        };
                        const origSend = XMLHttpRequest.prototype.send;
                        XMLHttpRequest.prototype.send = function() {
                            const xhr = this;
                            xhr.addEventListener('load', function() {
                                if (xhr._url && xhr.status === 200) {
                                    window._lbmaApiUrls.push(xhr._url);
                                }
                            });
                            return origSend.apply(this, arguments);
                        };
                    """,
                )
                text = r.markdown or ""
                raw_hash = hashlib.sha256(text.encode()).hexdigest()

                count = 0
                # Strategy 1: Fallback — parse markdown text for price patterns
                if count == 0:
                    print(" LBMA: trying markdown text fallback...")
                    for line in text.split("\n"):
                        m = re.search(
                            r"(\d{1,2}[/-]\d{1,2}[/-]\d{4}|\d{4}-\d{2}-\d{2})[\s:]+(\d{2,5}[.,]\d{2,4})",
                            line,
                        )
                        if m:
                            date_str, val = m.group(1), m.group(2)
                            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
                                try:
                                    d = datetime.strptime(date_str, fmt).date().isoformat()
                                    break
                                except ValueError:
                                    continue
                            else:
                                continue
                            try:
                                v = float(val.replace(",", "."))
                            except ValueError:
                                continue
                            # Sanity: price should be >$1000 for post-2000 gold
                            if v < 500 or v > 100000:
                                continue
                            rows.append(
                                {
                                    "date": d,
                                    "series_id": "LBMA_GOLD_FIX",
                                    "asset": "lbma_gold_fix_usd_oz",
                                    "value": v,
                                    "unit": "usd_per_oz",
                                    "source": "lbma_crawl4ai",
                                    "raw_hash": raw_hash,
                                    "available_from": d,
                                }
                            )
                            count += 1

                print(f" LBMA total rows extracted: {count}")
            except Exception as exc:
                print(f" LBMA error: {type(exc).__name__}: {exc}")

    try:
        import asyncio
        asyncio.run(_crawl())
    except RuntimeError:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(_crawl())).result(timeout=120)
    return rows

# ---------------------------------------------------------------------------
# GLD shares outstanding
# ---------------------------------------------------------------------------
def collect_gld_shares_outstanding() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        t = yf.Ticker("GLD")
        so_val = t.info.get("sharesOutstanding")
        if so_val and so_val > 0:
            today = date.today().isoformat()
            rows.append(
                {
                    "date": today,
                    "series_id": "GLD_SHARES_OUTSTANDING_CURRENT",
                    "asset": "gld_etf_shares_outstanding_current",
                    "value": float(so_val),
                    "unit": "shares",
                    "source": "yfinance_gld_info",
                    "available_from": today,
                    "note": f"SPDR Gold Shares - {so_val/1e6:.1f}M shares; current snapshot",
                }
            )
            print(f" GLD shares outstanding (yfinance): {so_val/1e6:.1f}M")
        else:
            print(" GLD shares outstanding: yfinance returned null/zero")
    except Exception as exc:
        print(f" GLD shares outstanding error: {type(exc).__name__}: {exc}")
    return rows

def collect_gld_shares_historical(from_date: str, to_date: str) -> list[dict[str, Any]]:
    """Fetch GLD shares outstanding from SEC EDGAR XBRL."""
    rows: list[dict[str, Any]] = []
    try:
        sec_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001108524.json"
        req = _url_request.Request(
            sec_url,
            headers={
                "User-Agent": "vn-gold-pipeline research@example.com",
                "Accept": "application/json",
            },
        )
        with _url_request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            payload = json.loads(raw.decode("utf-8", errors="replace"))
            raw_hash = hashlib.sha256(raw).hexdigest()

        facts = payload.get("facts", {}).get("us-gaap", {})
        shares_key = "CommonStockSharesOutstanding"
        if shares_key not in facts:
            shares_key = "WeightedAverageNumberOfSharesOutstandingBasic"
        if shares_key in facts:
            from_dt = date.fromisoformat(from_date)
            to_dt = date.fromisoformat(to_date)
            units = facts[shares_key].get("units", {}).get("shares", [])
            cnt = 0
            for u in units:
                end_d = u.get("end", "")[:10]
                if not end_d:
                    continue
                try:
                    d = date.fromisoformat(end_d)
                except ValueError:
                    continue
                if from_dt <= d <= to_dt:
                    val = u.get("val")
                    if val and val > 0:
                        rows.append(
                            {
                                "date": end_d,
                                "series_id": "GLD_SHARES_OUTSTANDING_HIST",
                                "asset": "gld_etf_shares_outstanding_hist",
                                "value": float(val),
                                "unit": "shares",
                                "source": "sec_edgar_xbrl",
                                "raw_hash": raw_hash,
                                "available_from": end_d,
                                "note": f"SEC XBRL {shares_key}",
                            }
                        )
                        cnt += 1
            print(f" GLD shares (SEC XBRL): {cnt} rows")
        else:
            print(f" GLD shares (SEC): key '{shares_key}' not found in {sorted(facts.keys())[:10]}")
    except Exception as exc:
        print(f" GLD shares (SEC): {type(exc).__name__}: {str(exc)[:80]}")
    return rows

# ---------------------------------------------------------------------------
# SBV deposit / interest rates
# ---------------------------------------------------------------------------
_VN_DEPOSIT_CONTENT_STRUCTURE_ID = ""

def collect_vietnam_deposit_rates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    discovery_path = Path("data/lake/source_discovery/sbv_structures.json")
    if discovery_path.exists():
        try:
            discovered = json.loads(discovery_path.read_text(encoding="utf-8"))
        except Exception:
            discovered = []
        candidates = [
            r for r in discovered
            if r.get("classification") == "interest_rate_candidate"
            and str(r.get("content_structure_id", "")) != "137473"
        ]
        if candidates:
            print(
                " SBV deposit rates: candidate structures found but field semantics "
                "are not yet verified: "
                + ", ".join(str(c.get("content_structure_id")) for c in candidates)
            )
        else:
            print(
                " SBV deposit rates: no verified interest-rate structure found; "
                "skipping to avoid mislabeling central FX as deposit rates"
            )
        return rows

    print(
        " SBV deposit rates: skipped. Run scripts/pipeline/discover_sbv_sources.py; "
        "structure 137473 is central USD/VND FX, not deposit rates."
    )
    return rows

def _parse_sbv_rate_text(fields: dict[str, str]) -> float | None:
    """Extract rate from SBV content fields.

    Known field names: TyGiaSo (rate value), TyGiaChu (currency),
    ChuThich (description), SoVanBan (doc number).
    """
    # Priority 1: Known direct rate field (raw value; unit may not be pct)
    for key in ("TyGiaSo", "ty_gia_so", "TyGia", "ty_gia"):
        val = fields.get(key, "")
        if val:
            try:
                return float(str(val).replace(",", ".").replace("%", "").strip())
            except (ValueError, TypeError):
                pass

    # Priority 2: Field name contains rate keywords (raw value)
    rate_kw = ["laisuat", "lai_suat", "rate", "ty_le", "tyle", "lai", "gui", "tien"]
    candidates: list[float] = []
    for name, value in fields.items():
        if not value:
            continue
        if any(kw in name.lower() for kw in rate_kw):
            try:
                candidates.append(float(str(value).replace(",", ".").replace("%", "").strip()))
            except (ValueError, TypeError):
                pass
    if candidates:
        candidates.sort()
        mid = len(candidates) // 2
        return candidates[mid] if len(candidates) % 2 == 1 else (candidates[mid - 1] + candidates[mid]) / 2

    # Priority 3: Scan all values for % patterns
    for value in fields.values():
        text = str(value)
        m = re.search(r"(\d{1,2}[.,]\d{1,2})\s*%", text)
        if m:
            try:
                return float(m.group(1).replace(",", "."))
            except ValueError:
                pass

    return None
# ---------------------------------------------------------------------------
# VN macro extractor (inline)
# ---------------------------------------------------------------------------
_HIGH_SIGNAL: dict[str, tuple[str, str, str]] = {
    "PCPI_IX": ("cpi_headline_yoy_pct", "pct", "M"),
    "AIP_ISIC4_IX": ("ip_total_index", "index_2015=100", "M"),
    "AIP_ISIC4_B_IX": ("ip_mining_quarrying_index", "index_2015=100", "M"),
    "AIP_ISIC4_C_IX": ("ip_manufacturing_index", "index_2015=100", "M"),
    "AIP_ISIC4_D_IX": ("ip_electricity_index", "index_2015=100", "M"),
    "AIP_ISIC4_E_IX": ("ip_water_waste_index", "index_2015=100", "M"),
    "LE_PE_NUM": ("labour_employed_10k", "10k_persons", "Q"),
    "LLF_PE_NUM": ("labour_force_10k", "10k_persons", "Q"),
    "LEU_PT": ("unemployment_rate_pct", "pct", "Q"),
    "TMG_CIF_USD": ("total_imports_cif_m_usd", "M_USD", "M"),
    "TMGIOT_CIF_USD": ("imports_all_cif_m_usd", "M_USD", "M"),
    "TMGISO_CIF_USD": ("imports_direct_m_usd", "M_USD", "M"),
    "VNM_HNX_EOP_IX": ("hnx_index_eop", "index", "M"),
    "VNM_VN_EOP_IX": ("vnindex_eop", "index", "M"),
    "LP_PE_NUM": ("population_10k", "10k_persons", "A"),
}
_SERIES_LOOKUP: dict[str, tuple[str, str, str]] = dict(_HIGH_SIGNAL)

def _extract_vn_macro_inline(
    input_csv: str, from_date: str, to_date: str
) -> tuple[list[dict[str, Any]], dict]:
    from_dt = date.fromisoformat(from_date)
    to_dt = date.fromisoformat(to_date)
    merged: dict[str, list[dict]] = {sid: [] for sid in _HIGH_SIGNAL}
    with open(input_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sid = row.get("series_id", "")
            if sid not in _SERIES_LOOKUP:
                continue
            d_str = row.get("date", "")[:10]
            if not d_str:
                continue
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d < from_dt or d > to_dt:
                continue
            val_raw = row.get("value", "")
            if not val_raw:
                continue
            try:
                val = float(val_raw)
            except (ValueError, TypeError):
                continue
            friendly_name, unit, _ = _SERIES_LOOKUP[sid]
            available_from = row.get("release_date", "") or d.isoformat()
            merged[sid].append(
                {
                    "date": d.isoformat(),
                    "series_id": sid,
                    "series_name": friendly_name,
                    "frequency": row.get("frequency", ""),
                    "value": val,
                    "unit": unit,
                    "source": "gso_macro_monitor_curated",
                    "domain": row.get("domain", ""),
                    "available_from": available_from[:10] if available_from else d.isoformat(),
                    "release_date": row.get("release_date", ""),
                }
            )
    out: list[dict[str, Any]] = []
    for sid, rows_list in merged.items():
        out.extend(rows_list)
    out.sort(key=lambda x: (x["date"], x["series_id"]))
    manifest = {
        "generated_at": date.today().isoformat(),
        "from": from_date,
        "to": to_date,
        "indicators_extracted": len(_HIGH_SIGNAL),
        "indicators_with_data": sum(1 for r in merged.values() if r),
        "indicators_missing": [sid for sid, r in merged.items() if not r],
        "total_rows": len(out),
    }
    return out, manifest

def collect_vn_macro(from_date: str, to_date: str) -> list[dict[str, Any]]:
    input_csv = "data/lake/macro_series_wb_gso.csv"
    try:
        rows, _ = _extract_vn_macro_inline(input_csv, from_date, to_date)
        return rows
    except Exception as exc:
        print(f" VN macro extract: {type(exc).__name__}: {exc}")
        return []

# ---------------------------------------------------------------------------
# Wedding season
# ---------------------------------------------------------------------------
def collect_wedding_season(from_date: str, to_date: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fd = date.fromisoformat(from_date)
    td = date.fromisoformat(to_date)
    year = fd.year
    while year <= td.year:
        # Spring: Apr 15-May 31
        for month, day, sev in [(4, 15, "medium"), (5, 1, "high")]:
            d = date(year, month, day)
            if fd <= d <= td:
                rows.append({
                    "event_date": d.isoformat(),
                    "event_type": "wedding_season",
                    "severity": sev,
                    "scope": "domestic_vietnam",
                    "expected_channel": "premium_spike",
                    "note": "Spring wedding season — gold jewelry demand surge",
                    "source": "rule_based_calendar",
                    "available_from": d.isoformat(),
                })
        # Autumn: Aug 15-Oct 5
        for month, day, sev in [(8, 15, "high"), (9, 1, "high"), (10, 1, "high")]:
            d = date(year, month, day)
            if fd <= d <= td:
                rows.append({
                    "event_date": d.isoformat(),
                    "event_type": "wedding_season",
                    "severity": sev,
                    "scope": "domestic_vietnam",
                    "expected_channel": "premium_spike",
                    "note": "Autumn wedding season — gold jewelry demand surge",
                    "source": "rule_based_calendar",
                    "available_from": d.isoformat(),
                })
        year += 1
    print(f" Wedding season: {len(rows)} event rows")
    return rows

# ---------------------------------------------------------------------------
# News/sentiment via RSS (with crawl4ai fallback)
# ---------------------------------------------------------------------------
_FEEDS: list[dict[str, str]] = [
    {"name": "vnexpress_economy", "url": "https://vnexpress.net/rss/kinh-te.rss", "lang": "vi", "category": "economy"},
    {"name": "vnexpress_world", "url": "https://vnexpress.net/rss/the-gioi.rss", "lang": "vi", "category": "geopolitics"},
    {"name": "vnexpress_gold", "url": "https://vnexpress.net/rss/gold.rss", "lang": "vi", "category": "gold_vn"},
    {"name": "tuoitre_news", "url": "https://tuoitrenews.vn/rss/front.rss", "lang": "vi", "category": "news"},
    {"name": "bbc_vietnamese", "url": "https://www.bbc.com/vietnamese/index.xml", "lang": "vi", "category": "news"},
    {"name": "vietnamnet", "url": "https://www.vietnamnet.vn/rss/home.rss", "lang": "vi", "category": "news"},
    {"name": "google_news_vn_gold", "url": "https://news.google.com/rss/search?q=vietnam+gold+sjc&hl=vi&gl=VN&ceid=VN:vi", "lang": "vi", "category": "gold_vn"},
    {"name": "google_news_gold", "url": "https://news.google.com/rss/search?q=gold+price+lbma&hl=en&gl=US&ceid=US:en", "lang": "en", "category": "gold_global"},
]

_GOLD_KEYWORDS_VI = [
    "vàng", "sjc", "pnj", "giá vàng", "nhẫn", "quẩn vàng",
    "mua vàng", "bán vàng", "kim loại", "gold", "ounce", "oz",
    "tỷ giá vàng", "chênh lệch", "premium",
    "lãi suất", "lai suat", "sbv", "ngân hàng nhà nước", "nnvn",
    "tỷ giá", "usd", "vnd", "đồng",
]
_GOLD_KEYWORDS_EN = [
    "gold", "sgold", "xau", "gld", "gold price", "gold futures",
    "spot gold", "lbma", "comex", "jewelry",
    "fed", "interest rate", "yield", "treasury",
    "usd", "dxy", "dollar", "inflation", "cpi", "tips",
]
_POSITIVE_VI = {"tăng", "tăng giá", "hưởng", "mua vào", "lãi", "lợi nhuận", "kỳ vọng", "tích cực", "phục hồi"}
_NEGATIVE_VI = {"giảm", "giảm giá", "bán ra", "lỗ", "suy thoái", "lo ngại", "căng thẳng", "khủng hoảng"}
_POSITIVE_EN = {"rise", "surge", "gain", "rally", "bullish", "positive", "recovery", "strong"}
_NEGATIVE_EN = {"fall", "plunge", "crash", "bearish", "negative", "recession", "fear", "crisis", "collapse"}

def _fetch_rss(url: str, timeout: int = 20) -> str | None:
    try:
        req = _url_request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0",
                "Accept": "application/rss+xml,application/xml,*/*",
            },
        )
        with _url_request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f" RSS fetch [{url[:60]}]: {type(exc).__name__}")
        return None

def collect_news_rss(from_date: str, to_date: str, timeout: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    from_dt = date.fromisoformat(from_date)
    to_dt = date.fromisoformat(to_date)
    seen_hashes: set[str] = set()

    for feed in _FEEDS:
        xml = _fetch_rss(feed["url"], timeout)
        if not xml:
            continue
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml)
            entries = root.findall(".//item") or root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )
        except ET.ParseError as exc:
            print(f" RSS parse [{feed['name']}]: {exc}")
            continue
        if not entries:
            print(f" RSS [{feed['name']}]: 0 items in feed")
            continue

        items_added = 0
        lang = feed["lang"]
        kws = _GOLD_KEYWORDS_VI if lang == "vi" else _GOLD_KEYWORDS_EN
        pos = _POSITIVE_VI if lang == "vi" else _POSITIVE_EN
        neg = _NEGATIVE_VI if lang == "vi" else _NEGATIVE_EN

        for entry in entries:
            title_el = entry.find("title")
            link_el = entry.find("link")
            date_el = entry.find("pubDate") or entry.find(
                "{http://www.w3.org/2005/Atom}updated"
            ) or entry.find("{http://www.w3.org/2005/Atom}published")
            title = ""
            if title_el is not None:
                title = (title_el.text or "").strip()
            if not title:
                continue
            link = ""
            if link_el is not None:
                link = (link_el.text or "").strip() or link_el.get("href", "")
            pub_raw = (date_el.text or "").strip() if date_el is not None else ""

            pub_iso = ""
            if pub_raw:
                for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        dt = datetime.strptime(
                            pub_raw[:len(fmt.replace("%Y", "0000").replace("%b", "MMM").replace("%z", "+0000"))],
                            fmt,
                        )
                        pub_iso = dt.date().isoformat()
                        break
                    except (ValueError, TypeError):
                        continue
                if not pub_iso:
                    pub_iso = pub_raw[:10]
            if not pub_iso:
                continue
            try:
                d = date.fromisoformat(pub_iso)
            except ValueError:
                continue
            if d < from_dt or d > to_dt:
                continue

            h = hashlib.sha256(title.encode()).hexdigest()[:16]
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            matched = [kw for kw in kws if kw.lower() in title.lower()]
            relevance = len(matched)
            pos_hits = sum(1 for w in pos if w.lower() in title.lower())
            neg_hits = sum(1 for w in neg if w.lower() in title.lower())
            if pos_hits > neg_hits:
                sentiment = "positive"
            elif neg_hits > pos_hits:
                sentiment = "negative"
            elif relevance == 0:
                sentiment = "irrelevant"
            else:
                sentiment = "neutral"

            rows.append(
                {
                    "date": pub_iso,
                    "source": feed["name"],
                    "title": title,
                    "url": link,
                    "lang": lang,
                    "category": feed["category"],
                    "keyword_matches": " ".join(matched),
                    "relevance_score": relevance,
                    "sentiment_heuristic": sentiment,
                    "sentiment_score_raw": round(
                        (pos_hits - neg_hits) / max(pos_hits + neg_hits, 1), 2
                    ),
                    "raw_hash": h,
                    "available_from": pub_iso,
                }
            )
            items_added += 1
        print(f" RSS [{feed['name']}]: {items_added} items")
    rows.sort(key=lambda x: (x["date"], x["source"]))
    return rows

# ---------------------------------------------------------------------------
# Policy events (manual curation)
# ---------------------------------------------------------------------------
def collect_policy_events() -> list[dict[str, Any]]:
    return [
        {
            "event_date": "2024-03-14",
            "event_type": "policy_auction",
            "severity": "high",
            "scope": "domestic_vietnam",
            "expected_channel": "premium_shrink",
            "note": "NHNN restarts gold auction after 11-year hiatus (Decision 319/QD-NHNN)",
            "source": "manual_curation",
            "available_from": "2024-03-14",
        },
        {
            "event_date": "2024-06-14",
            "event_type": "policy_auction",
            "severity": "medium",
            "scope": "domestic_vietnam",
            "expected_channel": "premium_shrink",
            "note": "5th NHNN gold auction — 300 taels sold at floor price",
            "source": "manual_curation",
            "available_from": "2024-06-14",
        },
        {
            "event_date": "2025-01-03",
            "event_type": "policy_rate_increase",
            "severity": "high",
            "scope": "domestic_vietnam",
            "expected_channel": "premium_shrink",
            "note": "SBV raised refinance rate 4.5% -> 5.0% — first hike in years",
            "source": "manual_curation",
            "available_from": "2025-01-03",
        },
        {
            "event_date": "2015-01-05",
            "event_type": "geopolitical_crisis",
            "severity": "high",
            "scope": "global",
            "expected_channel": "premium_spike",
            "note": "NĐ devaluation ~2% — major VND shock, domestic gold surged",
            "source": "manual_curation",
            "available_from": "2015-01-05",
        },
        {
            "event_date": "2022-03-08",
            "event_type": "geopolitical_crisis",
            "severity": "high",
            "scope": "global",
            "expected_channel": "premium_spike",
            "note": "Russia-Ukraine war started — safe haven demand spike",
            "source": "manual_curation",
            "available_from": "2022-03-08",
        },
        {
            "event_date": "2024-07-18",
            "event_type": "policy_import",
            "severity": "medium",
            "scope": "domestic_vietnam",
            "expected_channel": "liquidity_improve",
            "note": "SBV imported additional gold to boost domestic supply",
            "source": "manual_curation",
            "available_from": "2024-07-18",
        },
        {
            "event_date": "2024-11-18",
            "event_type": "policy_import",
            "severity": "medium",
            "scope": "domestic_vietnam",
            "expected_channel": "liquidity_improve",
            "note": "SBV 2nd gold import batch announced — 20 tonnes",
            "source": "manual_curation",
            "available_from": "2024-11-18",
        },
    ]

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class FeatureStatus:
    source: str
    dataset: str
    status: str
    records: int
    warning: str = ""

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect enhanced external features v2.")
    p.add_argument("--from", dest="from_date", default="2010-01-01")
    p.add_argument("--to", dest="to_date", default=date.today().isoformat())
    p.add_argument("--out-dir", default="data/lake")
    p.add_argument("--format", default="csv")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--retries", type=int, default=1)
    return p.parse_args()

def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    norm = out_dir / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    writer = DataLakeWriter(
        out_dir,
        formats=[f.strip().lower() for f in args.format.split(",") if f.strip()],
    )

    datasets: dict[str, list[dict]] = {
        "macro_enhanced": [],
        "futures_basis": [],
        "etf_proxy": [],
        "lbma_spot": [],
        "gld_shares": [],
        "vn_deposit_rates": [],
        "vn_macro": [],
                "news_events": [],
    }
    statuses: list[FeatureStatus] = []

    # 1. FRED enhanced
    try:
        fred_rows = collect_enhanced_fred(args.from_date, args.to_date)
        datasets["macro_enhanced"].extend(fred_rows)
        statuses.append(FeatureStatus("fred_json_v2", "macro_enhanced", "ok", len(fred_rows)))
        print(f"FRED enhanced: {len(fred_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("fred_json_v2", "macro_enhanced", "error", 0, str(exc)))
        print(f"FRED enhanced error: {exc}")

    # 2. Futures basis (GC=F)
    try:
        fut_rows = collect_gc_futures(args.from_date, args.to_date)
        datasets["futures_basis"].extend(fut_rows)
        statuses.append(FeatureStatus("yfinance_gc_ticker", "futures_basis", "ok", len(fut_rows)))
        print(f"Futures basis: {len(fut_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("yfinance_gc_ticker", "futures_basis", "error", 0, str(exc)))
        print(f"Futures basis error: {exc}")

    # 3. GLD ETF volume
    try:
        gld_rows = collect_gld_etf(args.from_date, args.to_date)
        datasets["etf_proxy"].extend(gld_rows)
        statuses.append(FeatureStatus("yfinance_gld_ticker", "etf_proxy", "ok", len(gld_rows)))
        print(f"GLD ETF: {len(gld_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("yfinance_gld_ticker", "etf_proxy", "error", 0, str(exc)))
        print(f"GLD ETF error: {exc}")

    # 3b. LBMA gold spot
    try:
        lbma_rows = collect_lbma_gold_price()
        datasets["lbma_spot"].extend(lbma_rows)
        statuses.append(
            FeatureStatus(
                "lbma_crawl4ai", "lbma_spot",
                "ok" if lbma_rows else "empty",
                len(lbma_rows),
                warning="" if lbma_rows else "Next.js SPA — needs JS intercept or API discovery",
            )
        )
        print(f"LBMA gold fix: {len(lbma_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("lbma_crawl4ai", "lbma_spot", "error", 0, str(exc)))
        print(f"LBMA gold fix error: {exc}")

    # 3c. GLD shares (historical SEC + current snapshot)
    try:
        hist_shares = collect_gld_shares_historical(args.from_date, args.to_date)
        cur_shares = collect_gld_shares_outstanding()
        all_shares = hist_shares + cur_shares
        datasets["gld_shares"].extend(all_shares)
        statuses.append(FeatureStatus("gld_shares_multi", "gld_shares", "ok" if all_shares else "empty", len(all_shares)))
        print(f"GLD shares: {len(hist_shares)} historical + {len(cur_shares)} current = {len(all_shares)}")
    except Exception as exc:
        statuses.append(FeatureStatus("gld_shares_multi", "gld_shares", "error", 0, str(exc)))
        print(f"GLD shares error: {exc}")

    # 4. VN deposit rates
    try:
        dep_rows = collect_vietnam_deposit_rates()
        datasets["vn_deposit_rates"].extend(dep_rows)
        non_null = sum(1 for r in dep_rows if r.get("value") is not None)
        statuses.append(
            FeatureStatus(
                "sbv_deposit_json",
                "vn_deposit_rates",
                "ok" if dep_rows else "empty",
                len(dep_rows),
                warning="" if non_null > 0 else "all values null — check SBV field name mapping",
            )
        )
        print(f"VN deposit rates: {len(dep_rows)} rows ({non_null} non-null)")
    except Exception as exc:
        statuses.append(FeatureStatus("sbv_deposit_json", "vn_deposit_rates", "error", 0, str(exc)))
        print(f"VN deposit rates error: {exc}")

    # 5. VN macro (GSO)
    try:
        macro_rows = collect_vn_macro(args.from_date, args.to_date)
        datasets["vn_macro"].extend(macro_rows)
        statuses.append(FeatureStatus("gso_macro_curated", "vn_macro", "ok", len(macro_rows)))
        print(f"VN macro: {len(macro_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("gso_macro_curated", "vn_macro", "error", 0, str(exc)))
        print(f"VN macro error: {exc}")
    # 6. News RSS
    try:
        news_rows = collect_news_rss(args.from_date, args.to_date, args.timeout)
        datasets["news_events"].extend(news_rows)
        statuses.append(FeatureStatus("rss_feeds", "news_events", "ok" if news_rows else "empty", len(news_rows)))
        print(f"News RSS: {len(news_rows)} rows")
    except Exception as exc:
        statuses.append(FeatureStatus("rss_feeds", "news_events", "error", 0, str(exc)))
        print(f"News RSS error: {exc}")

    # Write all datasets
    for dataset, rows in datasets.items():
        if rows:
            writer.write_dataset(dataset, rows)

    manifest = {
        "generated_at": date.today().isoformat(),
        "from": args.from_date,
        "to": args.to_date,
        "statuses": [
            {
                "source": s.source,
                "dataset": s.dataset,
                "status": s.status,
                "records": s.records,
                "warning": s.warning,
            }
            for s in statuses
        ],
        "total_records": sum(s.records for s in statuses),
    }
    (out_dir / "manifests" / "enhanced_features_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nDone. Total records: {manifest['total_records']}")
    print(f"Output: {out_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
