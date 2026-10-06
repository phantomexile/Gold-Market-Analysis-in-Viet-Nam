#!/usr/bin/env python3
"""
RSS News/Sentiment Collector for Vietnam Gold Market.

Collects headlines from:
  - VnExpress (vnexpress.net/rss) — Vietnamese domestic news
  - Reuters Vietnam (reutersagency.com or RSS feed)
  - Tuoi Tre (tuoitrenews.vn/rss)
  - Thanh Nien (thanhnien.com.vn/rss)

Uses requests + XML parsing (no crawl4ai required for RSS).

Output schema (news_events table):
  - date: ISO date of publication
  - source: feed name
  - title: headline
  - url: article URL
  - lang: vi/en
  - category: politics | economy | gold | finance | general
  - keyword_matches: space-separated keywords found (gold, SBV, gia_vang, etc.)
  - sentiment_score: +1/-1 heuristic based on keyword polarity (placeholder for LLM scoring)

This is a baseline — later can upgrade to crawl4ai for paywalled content
or add LLM-based sentiment classification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib import request as _url_request, error as _url_error

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap
bootstrap()
from gold_collectors.full_pipeline import DataLakeWriter

# ---------------------------------------------------------------------------
# Feed configuration
# ---------------------------------------------------------------------------
FEEDS: list[dict[str, str]] = [
    {
        "name": "vnexpress",
        "url": "https://vnexpress.net/rss/gold.rss",
        "lang": "vi",
        "primary_category": "gold_vn",
    },
    {
        "name": "vnexpress_economy",
        "url": "https://vnexpress.net/rss/kinh-teh.rss",
        "lang": "vi",
        "primary_category": "economy",
    },
    {
        "name": "vnexpress_world",
        "url": "https://vnexpress.net/rss/the-gioi.rss",
        "lang": "vi",
        "primary_category": "geopolitics",
    },
    {
        "name": "reuters_world",
        "url": "https://feeds.reuters.com/reuters/worldNews",
        "lang": "en",
        "primary_category": "world",
    },
    {
        "name": "reuters_business",
        "url": "https://feeds.reuters.com/news/usmarkets",
        "lang": "en",
        "primary_category": "finance",
    },
    {
        "name": "tuoitre_news",
        "url": "https://tuoitrenews.vn/rss/front.rss",
        "lang": "vi",
        "primary_category": "news",
    },
]

# Keyword dictionaries for relevance-filtering and heuristic sentiment
_GOLD_KEYWORDS_VI = [
    "vàng", "sjc", "pnj", "giá vàng", "nhẫn", "l的解释", "quẩn vàng",
    "mua vàng", "bán vàng", "kim loại", "gold", "ounce", "oz",
    "tỷ giá vàng", "chênh lệch vàng", "premium",
    "lai suất", "lãi suất", "sbv", "ngân hàng nhà nước",
    "tỷ giá", "usd", "vnd", "đồng",
]
_GOLD_KEYWORDS_EN = [
    "gold", "sgold", "xau", "gld", "gold price", "gold futures", "spot gold",
    "lbma", "comex", "jewelry", "jewellery",
    "fed", "interest rate", "yield", "treasury",
    "usd", "dxy", "dollar",
    "inflation", "cpi", "tips",
]

_POSITIVE_VI = {"tăng", "tăng giá", "hưởng", "mua vào", "lãi", "lợi nhuận", "kỳ vọng", "tích cực", "phục hồi"}
_NEGATIVE_VI = {"giảm", "giảm giá", "bán ra", "lỗ", "suy thoái", "lo ngại", "căng thẳng", "khủng hoảng", "sụp đổ", "thất bại"}
_POSITIVE_EN = {"rise", "surge", "gain", "rally", "bullish", "positive", "recovery",
                 "strong", "outperform", "boost", "upgrade"}
_NEGATIVE_EN = {"fall", "plunge", "crash", "bearish", "negative", "recession",
                 "fear", "crisis", "collapse", "risk-off", "downgrade"}

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


@dataclass(frozen=True)
class NewsStatus:
    source: str
    status: str
    records: int
    warning: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect Vietnam gold news/sentiment from RSS feeds.")
    p.add_argument("--from", dest="from_date", default="2010-01-01")
    p.add_argument("--to", dest="to_date", default=date.today().isoformat())
    p.add_argument("--out-dir", default="data/lake")
    p.add_argument("--timeout", type=int, default=20)
    return p.parse_args()


def _fetch_rss(url: str, timeout: int = 20) -> str | None:
    try:
        req = _url_request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml,*/*"})
        with _url_request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        print(f" RSS fetch [{url[:50]}]: {type(exc).__name__}: {exc}")
        return None


def _parse_rss_items(xml_text: str, feed_name: str, lang: str, category: str) -> list[dict[str, Any]]:
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f" RSS parse error [{feed_name}]: {exc}")
        return items

    # RSS 2.0: <rss><channel><item>...
    # Atom is different — handle both
    entries = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
    if not entries:
        return items

    for entry in entries:
        title = ""
        link = ""
        pub_date = ""

        # RSS
        title_el = entry.find("title")
        link_el = entry.find("link")
        date_el = entry.find("pubDate")

        # Atom fallback
        if title_el is None:
            title_el = entry.find("{http://www.w3.org/2005/Atom}title")
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            date_el = entry.find("{http://www.w3.org/2005/Atom}updated") or entry.find("{http://www.w3.org/2005/Atom}published")

        title = (title_el.text or "").strip() if title_el is not None and title_el.text else ""
        if not title:
            continue
        link = (link_el.text or "").strip() if link_el is not None and link_el.text else ""
        # Atom link may have href attribute
        if not link and link_el is not None:
            link = (link_el.get("href") or "").strip()
        pub_date = (date_el.text or "").strip() if date_el is not None and date_el.text else ""

        # Parse date
        pub_iso = ""
        if pub_date:
            for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(pub_date[:len(fmt.replace('%Y','0000').replace('%b','MMM').replace('%z','+0000'))], fmt)
                    pub_iso = dt.date().isoformat()
                    break
                except (ValueError, TypeError):
                    continue
            if not pub_iso:
                pub_iso = pub_date[:10]

        # Score relevance & sentiment
        kw_list = _GOLD_KEYWORDS_VI if lang == "vi" else _GOLD_KEYWORDS_EN
        matched_kws = [kw for kw in kw_list if kw.lower() in title.lower()]
        relevance_score = len(matched_kws)

        pos_words = _POSITIVE_VI if lang == "vi" else _POSITIVE_EN
        neg_words = _NEGATIVE_VI if lang == "vi" else _NEGATIVE_EN
        pos_hits = sum(1 for w in pos_words if w.lower() in title.lower())
        neg_hits = sum(1 for w in neg_words if w.lower() in title.lower())
        sentiment = "neutral"
        if pos_hits > neg_hits:
            sentiment = "positive"
        elif neg_hits > pos_hits:
            sentiment = "negative"
        elif relevance_score == 0:
            sentiment = "irrelevant"

        # Hash for dedup
        raw_hash = hashlib.sha256(title.encode()).hexdigest()[:16]

        items.append({
            "date": pub_iso,
            "source": feed_name,
            "title": title,
            "url": link,
            "lang": lang,
            "category": category,
            "keyword_matches": " ".join(matched_kws),
            "relevance_score": relevance_score,
            "sentiment_heuristic": sentiment,
            "sentiment_score_raw": round((pos_hits - neg_hits) / max(pos_hits + neg_hits, 1), 2),
            "raw_hash": raw_hash,
        })
    return items


def collect_news_rss(from_date: str, to_date: str, timeout: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    from_dt = date.fromisoformat(from_date)
    to_dt = date.fromisoformat(to_date)
    seen_hashes: set[str] = set()

    for feed in FEEDS:
        xml = _fetch_rss(feed["url"], timeout)
        if not xml:
            continue
        items = _parse_rss_items(xml, feed["name"], feed["lang"], feed["primary_category"])
        added = 0
        for item in items:
            d_str = item["date"]
            if not d_str:
                continue
            try:
                d = date.fromisoformat(d_str)
            except ValueError:
                continue
            if d < from_dt or d > to_dt:
                continue
            if item["raw_hash"] in seen_hashes:
                continue
            seen_hashes.add(item["raw_hash"])
            rows.append(item)
            added += 1
        print(f" RSS [{feed['name']}]: {added} new items after dedup/filter")

    rows.sort(key=lambda x: (x["date"], x["source"]))
    return rows


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    norm = out_dir / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)

    try:
        rows = collect_news_rss(args.from_date, args.to_date, args.timeout)
        writer.write_dataset("news_events", rows)
        print(f"\nNews events: {len(rows)} rows")
        from collections import Counter
        src_counts = Counter(r["source"] for r in rows)
        for src, cnt in sorted(src_counts.items()):
            print(f"  {src}: {cnt}")
        sent_counts = Counter(r["sentiment_heuristic"] for r in rows)
        print(f"Sentiment: {dict(sent_counts)}")
    except Exception as exc:
        print(f"News RSS error: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
