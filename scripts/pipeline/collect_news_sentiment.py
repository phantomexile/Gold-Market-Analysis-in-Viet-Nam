#!/usr/bin/env python3
"""Gold news sentiment collector via Google News RSS (quarterly backfill 2010+).

Strategies:
  Primary: Google News RSS with date-range queries (quarterly chunks back to 2010)
  Fallback: yfinance Ticker.news (last ~2 weeks only)

Output: data/lake/news_sentiment.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Any

OUT_DIR = Path("data/lake")
NORMALIZED = OUT_DIR / "normalized"
NORMALIZED.mkdir(parents=True, exist_ok=True)

_POSITIVE_WORDS: set[str] = {
    "surge", "rally", "bullish", "jump", "soar", "rise", "gain", "climb",
    "higher", "record", "outperform", "strength", "recovery", "boost",
    "upgrade", "positive", "breakthrough", "safe-haven",
}
_NEGATIVE_WORDS: set[str] = {
    "plunge", "crash", "bearish", "tumble", "plummet", "fall", "drop",
    "slide", "lower", "weak", "decline", "loss", "fear", "recession",
    "downgrade", "negative", "risk", "pressure", "worst", "slump",
}
_GOLD_HINTS: re.Pattern = re.compile(
    r"\bgold\b|\bXAU\b|\bSJC\b|v[aươ]n[g]\b|\bprecious\s+metals?\b|\bspot\s+gold\b",
    re.IGNORECASE,
)
_NEWS_QUERIES: list[str] = [
    "gold price",
    "gold market outlook",
    "SJC gold price",
    "vàng giá hôm nay",
    "gold investment",
]


def _score_headline(headline: str) -> int:
    h = headline.lower()
    if not _GOLD_HINTS.search(h):
        return 0
    pos = sum(h.count(w) for w in _POSITIVE_WORDS)
    neg = sum(h.count(w) for w in _NEGATIVE_WORDS)
    return pos - neg


def _parse_pub_date(raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    from datetime import datetime as _dt
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return _dt.strptime(raw, fmt).date().isoformat()
        except (ValueError, TypeError):
            continue
    # Try ISO-like extract
    m = re.search(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        return m.group(1)
    return None


def fetch_google_news_rss(query: str, start_d: date, end_d: date,
                          max_items: int = 80) -> list[dict[str, Any]]:
    url = (
        "https://news.google.com/rss/search?"
        + urllib.parse.urlencode({
            "q": query,
            "hl": "en-US",
            "gl": "US",
            "ceid": "US:en",
            "when": f"{start_d.isoformat()}..{end_d.isoformat()}",
        })
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0 Safari/537.36"
            ),
        },
    )
    rows: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw_xml = r.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f"  WARN GoogleNews fail [{query[:25]}]: {type(exc).__name__}", file=sys.stderr)
        return rows

    items = re.findall(r"<item>(.*?)</item>", raw_xml, re.DOTALL)
    for item in items[:max_items]:
        def _tag(t):
            m = re.search(rf"<{t}>(.*?)</{t}>", item, re.DOTALL)
            return html.unescape(m.group(1).strip()) if m else ""
        title = _tag("title")
        link = _tag("link")
        pub_raw = _tag("pubDate")
        pub_d = _parse_pub_date(pub_raw)
        source = _tag("source")
        if not title:
            continue
        score = _score_headline(title)
        rows.append({
            "date": pub_d or start_d.isoformat(),
            "series_id": "NEWS_GOLD_SENTIMENT",
            "asset": "gold_news_sentiment",
            "value": float(score),
            "unit": "sentiment_score",
            "source": "google_news_rss",
            "available_from": pub_d or start_d.isoformat(),
            "headline": title[:200],
            "publisher": source[:50],
            "link": link[:200],
            "note": "Google News RSS; quarterly backfill",
        })
    return rows


def fetch_yfinance_news(symbol: str = "GC=F", pause: float = 1.0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        news = ticker.news
    except Exception as exc:
        print(f"  WARN yfinance news: {type(exc).__name__}", file=sys.stderr)
        return rows
    if not isinstance(news, list) or not news:
        return rows
    for item in news:
        headline = (item.get("title") or "").strip()
        link = (item.get("link") or item.get("url") or "").strip()
        pub_ts = item.get("providerPublishTime") or item.get("publishTime")
        pub_d = None
        if pub_ts:
            try:
                from datetime import datetime
                pub_d = datetime.utcfromtimestamp(int(pub_ts)).date().isoformat()
            except (OSError, ValueError, TypeError):
                pass
        if not headline:
            continue
        rows.append({
            "date": pub_d or date.today().isoformat(),
            "series_id": "NEWS_GOLD_SENTIMENT",
            "asset": "gold_news_sentiment",
            "value": float(_score_headline(headline)),
            "unit": "sentiment_score",
            "source": "yfinance_news",
            "available_from": pub_d or date.today().isoformat(),
            "headline": headline[:200],
            "publisher": "",
            "link": link[:200],
            "note": "yfinance last 2 weeks",
        })
        time.sleep(pause)
    return rows


def _quarter_chunks(start, end):
    """Generate (start, end) tuples for each quarter in a date range."""
    from datetime import date, timedelta
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    chunks = []
    cur = date(s.year, s.month, 1)
    while cur <= e:
        # Determine last day of current quarter
        qm = ((cur.month - 1) // 3 + 1) * 3
        if qm == 12:
            nxt = date(cur.year + 1, 1, 1)
        else:
            nxt = date(cur.year, qm + 1, 1)
        q_end = nxt - timedelta(days=1)
        seg_s = max(cur, s)
        seg_e = min(q_end, e)
        if seg_s <= seg_e:
            chunks.append((seg_s, seg_e))
        cur = nxt
    return chunks



def load_existing(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def merge_and_write(existing: list[dict[str, Any]], new_rows: list[dict[str, Any]],
                    out_path: Path) -> None:
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for r in existing:
        by_key[(r.get("date", ""), r.get("headline", "")[:60])] = r
    for r in new_rows:
        by_key[(r.get("date", ""), r.get("headline", "")[:60])] = r
    merged = sorted(by_key.values(), key=lambda x: x.get("date", ""))
    if not merged:
        return
    fieldnames = sorted(merged[0].keys())
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(merged)


def write_manifest(records: int, out_dir: Path = OUT_DIR) -> None:
    import json
    (out_dir / "manifests").mkdir(parents=True, exist_ok=True)
    (out_dir / "manifests" / "news_sentiment_manifest.json").write_text(
        json.dumps({
            "generated_at": date.today().isoformat(),
            "source": "google_news_rss+yfinance",
            "records": records,
            "note": "Gold headline sentiment; quarterly Google News RSS backfill to 2010+",
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Collect gold news sentiment via Google News RSS.")
    ap.add_argument("--from", dest="start", default="2010-01-01")
    ap.add_argument("--to", dest="end", default="2026-07-17")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    out_path = NORMALIZED / "news_sentiment.csv"
    existing = load_existing(out_path)
    print(f"Existing news_sentiment: {len(existing)} rows")

    chunks = _quarter_chunks(args.start, args.end)
    queries = _NEWS_QUERIES[:4]
    print(f"Backfill: {len(chunks)} quarters x {len(queries)} queries")

    all_new: list[dict[str, Any]] = []
    for i, (qs, qe) in enumerate(chunks, 1):
        for q in queries:
            rows = fetch_google_news_rss(q, qs, qe, max_items=40)
            all_new.extend(rows)
            time.sleep(0.35)
        if i % 4 == 0:
            print(f"  progress: {i}/{len(chunks)} quarters, {len(all_new)} items")

    print("Trying yfinance news fallback...")
    yf = fetch_yfinance_news("GC=F")
    if yf:
        all_new.extend(yf)

    seen = {r.get("headline", "")[:60] for r in existing}
    deduped = [r for r in all_new if r.get("headline", "")[:60] not in seen]

    print(f"New unique items: {len(deduped)}")
    merge_and_write(existing, deduped, out_path)
    write_manifest(len(deduped) + len(existing))

    if deduped:
        scores = [float(r["value"]) for r in deduped]
        print(f"Score dist: +{sum(1 for s in scores if s>0)} bull / "
              f"{sum(1 for s in scores if s==0)} neut / "
              f"{sum(1 for s in scores if s<0)} bear")
        srcs: dict[str, int] = {}
        for r in deduped:
            srcs[r["source"]] = srcs.get(r["source"], 0) + 1
        for k, v in sorted(srcs.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")

    print(f"Total → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
