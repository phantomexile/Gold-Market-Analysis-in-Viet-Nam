#!/usr/bin/env python3
"""
News-driven event detection for Vietnam gold market.
Real events must come from actual news headlines with dates - not hand-written.

Data sources:
- news_sentiment.csv (3,138 existing rule-based rows with headlines)
- Google News RSS for backfill
- yfinance news feed for recent events

Each event needs:
- date (from news pubDate, NOT from when I happen to remember it)
- headline (original Vietnamese/English)
- event_type (classified from headline keywords)
- source (which news site)
- url (for verification)
"""
import csv, sys, json, re
from datetime import date
from pathlib import Path
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")


def load_google_news(
    query: str,
    start: date,
    end: date,
    max_items: int = 50,
) -> list[dict]:
    """Crawl Google News RSS for query in date range."""
    import urllib.request, urllib.parse, html as ihtml
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({
            "q": query,
            "hl": "en",
            "gl": "US",
            "ceid": "US:en",
            "when": f"{start.isoformat()}..{end.isoformat()}",
        })
    )
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    rows = []
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  FAIL: {query[:40]} -> {e}")
        return rows

    items = re.findall(r"<item>(.*?)</item>", raw, re.DOTALL)
    for item in items[:max_items]:
        def _tag(t):
            m = re.search(rf"<{t}>(.*?)</{t}>", item, re.DOTALL)
            return ihtml.unescape(m.group(1).strip()) if m else ""

        title = _tag("title")
        link = _tag("link")
        pub_raw = _tag("pubDate")
        source = _tag("source")

        pub_d = None
        if pub_raw:
            for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    pub_d = date.fromisoformat(__import__("datetime").datetime.strptime(pub_raw, fmt).date().isoformat())
                    break
                except (ValueError, TypeError):
                    pass
            if pub_d is None:
                m = re.search(r"(\d{4}-\d{2}-\d{2})", pub_raw)
                if m:
                    pub_d = m.group(1)

        if not title:
            continue

        # Classify event type from keywords
        title_lower = title.lower()
        event_type = "news_other"
        if any(k in title_lower for k in ["sbv", "ngân hàng nhà nước", "central bank", "lãi suất", "interest rate", "refinance"]):
            event_type = "policy_rate_sbv"
        elif any(k in title_lower for k in ["nhnn", "đấu thầu vàng", "gold auction", "auction gold"]):
            event_type = "policy_auction"
        elif any(k in title_lower for k in ["tỷ giá", "usd/vnd", "exchange rate", "vnd", "đồng"]):
            event_type = "fx_shock"
        elif any(k in title_lower for k in ["sjc", "vàng sjc", "gold price", "vàng giá"]):
            event_type = "gold_price_move"
        elif any(k in title_lower for k in ["premium", "chênh lệch vàng"]):
            event_type = "premium_news"
        elif any(k in title_lower for k in ["fed", "fomc", "ecb", "lãi suất mỹ", "america rate"]):
            event_type = "policy_rate_global"
        elif any(k in title_lower for k in ["covid", "corona", "lockdown", "dịch bệnh"]):
            event_type = "crisis_health"
        elif any(k in title_lower for k in ["war", "ukraine", "russia", "geopolitical", "tensions"]):
            event_type = "geopolitical"
        elif any(k in title_lower for k in ["import", "nhập khẩu", "export", "xuất khẩu"]):
            event_type = "policy_import"
        elif any(k in title_lower for k in ["tết", "thần tài", "lunar new year", "wedding", "cưới"]):
            event_type = "seasonal"

        rows.append({
            "event_date": (pub_d.isoformat() if hasattr(pub_d, 'isoformat') else str(pub_d or date.today().isoformat())),
            "event_type": event_type,
            "scope": "domestic_vietnam" if "vn" in query or "việt" in title_lower else "global",
            "severity": "high" if any(k in title_lower for k in ["soars", "surge", "plunge", "crash", "record", "pan"]) else "medium",
            "expected_channel": "premium_spike" if event_type in ("gold_price_move", "premium_news") else "safe_haven_buy",
            "note": title[:200],
            "source_url": link[:300],
            "effective_from": pub_d or date.today().isoformat(),
            "effective_to": pub_d or date.today().isoformat(),
            "source": (source or "google_news_rss")[:50],
            "publisher": (source or "")[:50],
            "headline": title[:300],
        })
    return rows


def load_yfinance_news(symbols: list[str], max_per_symbol: int = 20) -> list[dict]:
    """Crawl recent news from yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed, skipping")
        return []

    rows = []
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym)
            items = ticker.news or []
        except Exception as e:
            print(f"  yfinance {sym} fail: {e}")
            continue

        for item in items[:max_per_symbol]:
            title = (item.get("title") or "").strip()
            link = (item.get("link") or item.get("url") or "").strip()
            pub_ts = item.get("providerPublishTime") or item.get("publishTime")
            pub_d = None
            if pub_ts:
                try:
                    pub_d = __import__("datetime").datetime.utcfromtimestamp(int(pub_ts)).date().isoformat()
                except (OSError, ValueError, TypeError):
                    pass

            if not title or not pub_d:
                continue

            title_lower = title.lower()
            event_type = "gold_global"
            if any(k in title_lower for k in ["rate", "fed", "fomc", "ecb", "yield"]):
                event_type = "policy_rate_global"
            elif any(k in title_lower for k in ["gold", "xau", "precious"]):
                event_type = "gold_price_move"

            rows.append({
                "event_date": pub_d,
                "event_type": event_type,
                "scope": "global",
                "severity": "high" if any(k in title_lower for k in ["surge", "plunge", "record", "high", "low"]) else "medium",
                "expected_channel": "safe_haven_buy",
                "note": title[:200],
                "source_url": link[:300],
                "effective_from": pub_d,
                "effective_to": pub_d,
                "source": "yfinance",
                "publisher": "",
                "headline": title[:300],
            })
        __import__("time").sleep(0.5)
    return rows


def load_existing_news(path: str) -> list[dict]:
    """Load news_sentiment.csv as fallback event source."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("headline"):
                    pub_d = r.get("available_from") or r.get("date") or ""
                    if pub_d:
                        rows.append({
                            "event_date": pub_d,
                            "event_type": "gold_sentiment_news",
                            "scope": "global",
                            "severity": "medium",
                            "expected_channel": "safe_haven_buy",
                            "note": r["headline"][:200],
                            "source_url": r.get("link", "")[:300],
                            "effective_from": pub_d,
                            "effective_to": pub_d,
                            "source": r.get("source", "rss"),
                            "publisher": r.get("publisher", "")[:50],
                            "headline": r["headline"][:300],
                        })
    except FileNotFoundError:
        pass
    return rows


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="from_date", default="2020-01-01")
    parser.add_argument("--to", dest="to_date", default="2026-07-11")
    parser.add_argument("--out", default="data/lake/news_events.csv")
    parser.add_argument("--query-extra", default="", help="Extra comma-sep queries")
    args = parser.parse_args()

    f, t = date.fromisoformat(args.from_date), date.fromisoformat(args.to_date)

    all_events: list[dict] = []

    # Bucketed queries for Google News RSS backfill
    VN_QUERIES = [
        "vàng giá hôm nay",
        "SJC giá vàng",
        "vàng miếng SJC",
        "tỷ giá USD VND hôm nay",
        "NHNN vàng đấu thầu",
    ]
    GLOBAL_QUERIES = [
        "gold price today",
        "LBMA gold",
        "gold futures",
        "Federal Reserve rate decision",
        "USD VND exchange rate",
    ]
    if args.query_extra:
        VN_QUERIES += [q.strip() for q in args.query_extra.split(",")]

    print(f"Crawling news events from {args.from_date} to {args.to_date}")
    print()

    # Google News RSS queries (quarterly chunks for backfill)
    from datetime import timedelta
    chunks = []
    cur = f
    while cur < t:
        chunk_end = min(cur + timedelta(days=90), t)
        chunks.append((cur, chunk_end))
        cur = chunk_end + timedelta(days=1)

    # Run a few representative chunks for each query
    sample_chunks = chunks[:3] + chunks[len(chunks)//2:] + chunks[-2:]  # 7 chunks covering the range
    all_q = VN_QUERIES[:3] + GLOBAL_QUERIES[:3]

    for query in all_q:
        for s, e in sample_chunks:
            print(f"  [{query[:25]}] {s}..{e}")
            evts = load_google_news(query, s, e, max_items=30)
            all_events.extend(evts)

    # yfinance recent
    print("\n  yfinance recent...")
    all_events.extend(load_yfinance_news(["GC=F", "SI=F", "XAUUSD=X", "^VIX"], max_per_symbol=20))

    # Existing news_sentiment as fallback
    print("\n  existing news_sentiment...")
    all_events.extend(load_existing_news("data/lake/news_sentiment.csv"))

    # Deduplicate by (date, headline first 80 chars)
    seen = set()
    unique = []
    for e in all_events:
        key = (e["event_date"], e.get("headline", "")[:80])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    unique.sort(key=lambda x: str(x["event_date"]))

    # Write
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if unique:
        fieldnames = list(unique[0].keys())
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(unique)

    manifest = {
        "generated_at": date.today().isoformat(),
        "from": args.from_date, "to": args.to_date,
        "records": len(unique),
        "event_types": sorted({e["event_type"] for e in unique}),
        "daily_counts": {
            y: sum(1 for e in unique if e["event_date"].startswith(y))
            for y in sorted({e["event_date"][:4] for e in unique})
        },
    }
    (out_path.parent / "manifests" / "news_events_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n=== DONE ===")
    print(f"Total news events: {len(unique)}")
    print(f"By type:")
    for et, ct in Counter(e["event_type"] for e in unique).most_common():
        print(f"  {et}: {ct}")
    print(f"Per year:")
    for y in sorted(manifest["daily_counts"]):
        print(f"  {y}: {manifest['daily_counts'][y]}")
    print(f"Output: {args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
