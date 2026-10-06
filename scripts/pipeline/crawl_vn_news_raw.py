#!/usr/bin/env python3
"""
Crawl raw Vietnamese + global gold news TEXT data.
Uses urllib + regex only. No Playwright needed.

Sources: Google News RSS, Kitco RSS, Investing.com RSS, goldprice.org,
         yfinance news, nhipcaudautu.vn direct articles.

Output: data/lake/news_raw_headlines_vietnam_gold.csv
Columns: crawl_date, event_date, headline, body_text, url, source, category, query_used
"""
import csv, sys, re, json
from datetime import date, datetime
from pathlib import Path
import urllib.request, urllib.parse
import html as ihtml
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

OUT = Path("data/lake/news_raw_headlines_vietnam_gold.csv")
MANIFEST = OUT.parent / "manifests" / "vn_news_raw_manifest.json"
OUT.parent.mkdir(parents=True, exist_ok=True)
MANIFEST.parent.mkdir(parents=True, exist_ok=True)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDRS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.5,en;q=0.3",
    "Accept-Encoding": "identity",
}


def safe_read(url, timeout=25):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _tag(item, tag):
    m = re.search(rf"<{tag}>(.*?)</{tag}>", item, re.DOTALL)
    return ihtml.unescape(m.group(1).strip()) if m else ""


def parse_pubdate(v):
    if not v:
        return None
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%a, %d %b %Y",
        "%d %b %Y %H:%M:%S %Z",
    ):
        try:
            return datetime.strptime(v.strip(), fmt).date().isoformat()
        except (ValueError, TypeError):
            pass
    m = re.search(r"(\d{4}-\d{2}-\d{2})", v)
    return m.group(1) if m else None


def clean_html(html_text, max_chars=3000):
    text = re.sub(r"<script[^>]*>.*?</script>", "", html_text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = ihtml.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n", "\n", text)
    return text.strip()[:max_chars]


def category_of(text):
    t = text.lower()
    if any(k in t for k in ["vàng", "sjc", "doji", "phú quý", "bảo tín minh châu"]):
        return "gold_vn"
    if any(k in t for k in ["lãi suất", "fed", "fomc", "ecb", "interest rate"]):
        return "policy_rates"
    if any(k in t for k in ["tỷ giá", "usd/vnd", "đồng", "exchange rate"]):
        return "fx_vnd"
    if any(k in t for k in ["lạm phát", "inflation", "cpi", "ppi"]):
        return "macro"
    if any(k in t for k in ["chứng khoán", "vnindex", "vn-index", "stock market"]):
        return "equity"
    return "other"


def extract_items(raw, max_items=100):
    results = []
    for item_m in re.finditer(r"<item>(.*?)</item>", raw, re.DOTALL):
        item = item_m.group(1)
        title = _tag(item, "title") or _tag(item, "description")
        if not title:
            continue
        link = _tag(item, "link")
        pub_raw = _tag(item, "pubDate")
        pub_iso = parse_pubdate(pub_raw) or ""
        source = _tag(item, "source")
        results.append((title[:300], link[:500], pub_iso, source[:60]))
        if len(results) >= max_items:
            break
    return results


# ============================================================
# SOURCE 1: Google News RSS (broad + targeted VN queries)
# ============================================================
ALL_QUERIES = [
    "vàng sjc giá hôm nay", "giá vàng Việt Nam", "vàng miếng SJC",
    "giá vàng DOJI hôm nay", "giá vàng phú quý",
    "NHNN ngân hàng nhà nước vàng đấu thầu",
    "lãi suất Mỹ giảm vàng tăng", "Fed FOMC quyết định vàng",
    "lạm phát vàng Mỹ", "quân đội Israel Iran vàng",
    "tỷ giá USD VND hôm nay", "USD giảm giá vàng tăng",
    "gold price today", "gold LBMA AM",
    "gold traders London", "Shanghai gold premium",
    "LBMA gold fix", "gold central bank",
    "site:vnexpress.net vàng giá", "site:tuoitre.vn vàng giá",
    "site:thanhnien.vn vàng miếng sjc",
    "site:vietnamnet.vn giá vàng hôm nay",
    "site:cafef.vn vàng giá", "site:nhipcaudautu.vn vàng",
    "vàng tăng mạnh", "giá vàng đỉnh lịch sử",
    "vàng nhập siêu", "thị trường vàng châu á",
    "china gold import", "usd/vnd biến động",
    "vàng giá 2022", "vàng giá 2023", "vàng giá 2024",
    "vàng giá 2025", "vàng giá 2026",
    "gold price spike 2024", "gold price spike 2025", "gold price spike 2026",
    "vàng ngày mai dự báo", "toàn cảnh thị trường vàng",
    "giá vàng thế giới hôm nay", "giá vàng trung quốc",
    "xu hướng giá vàng", "tin tức kinh tế hôm nay",
    "dự báo giá vàng 2026", "ngân hàng vàng",
    "trung tâm giao dịch vàng", "quỹ vàng",
    "đầu tư vàng", "sjc official price",
]


def crawl_google_news(all_rows, seen_set):
    today_str = date.today().isoformat()
    n = len(ALL_QUERIES)
    for idx, q in enumerate(ALL_QUERIES, 1):
        raw = safe_read(
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode({"q": q, "hl": "vi", "gl": "US", "ceid": "US:vi"}),
        )
        if not raw or len(raw) < 500:
            raw = safe_read(
                "https://news.google.com/rss/search?"
                + urllib.parse.urlencode({"q": q, "hl": "en", "gl": "US", "ceid": "US:en"}),
            )
        if not raw or len(raw) < 300:
            continue
        items = extract_items(raw, 100)
        added = 0
        for title, link, pub_iso, src in items:
            key = (title[:65], link[:45])
            if key in seen_set:
                continue
            seen_set.add(key)
            all_rows.append({
                "crawl_date": today_str,
                "event_date": pub_iso,
                "headline": title,
                "body_text": "",
                "url": link,
                "source": f"google_news_rss:{src or 'unknown'}",
                "category": category_of(title),
                "query_used": q[:60],
            })
            added += 1
        sys.stdout.write(
            f"\r  GNews {idx:2d}/{n} [{q[:30]:30s}] +{added:3d} "
            f"(total={len(all_rows):5d})  "
        )
        sys.stdout.flush()
    sys.stdout.write("\n")


def crawl_kitco(all_rows, seen_set):
    today_str = date.today().isoformat()
    raw = safe_read("https://www.kitco.com/rss/newsfeed.xml")
    if not raw:
        return 0
    cnt = 0
    for title, link, pub_iso, src in extract_items(raw, 60):
        if not any(k in title.lower() for k in [
            "gold", "silver", "precious", "fed", "rate",
            "dollar", "inflation", "yield", "central",
        ]):
            continue
        key = (title[:65], link[:45])
        if key in seen_set:
            continue
        seen_set.add(key)
        all_rows.append({
            "crawl_date": today_str,
            "event_date": pub_iso,
            "headline": title,
            "body_text": "",
            "url": link,
            "source": "kitco_rss",
            "category": "gold_global",
            "query_used": "kitco_rss",
        })
        cnt += 1
    return cnt


def crawl_investing(all_rows, seen_set):
    today_str = date.today().isoformat()
    raw = safe_read("https://www.investing.com/rss/news_25.rss")
    if not raw:
        return 0
    cnt = 0
    for title, link, pub_iso, src in extract_items(raw, 60):
        if not any(k in title.lower() for k in [
            "gold", "precious", "fed", "rate", "silver",
            "inflation", "yield", "dollar", "commodity",
        ]):
            continue
        key = (title[:65], link[:45])
        if key in seen_set:
            continue
        seen_set.add(key)
        all_rows.append({
            "crawl_date": today_str,
            "event_date": pub_iso,
            "headline": title,
            "body_text": "",
            "url": link,
            "source": "investing_com_rss",
            "category": "gold_global",
            "query_used": "investing_rss",
        })
        cnt += 1
    return cnt


def crawl_goldprice_org(all_rows, seen_set):
    today_str = date.today().isoformat()
    raw = safe_read("https://goldprice.org/news")
    if not raw:
        return 0
    links = set(re.findall(r'href="(https://[^"]*goldprice[^"]+)"', raw))
    links |= set(
        "https://goldprice.org" + m.group(1)
        for m in re.finditer(r'href="(/news/[^"]+)"', raw)
    )
    cnt = 0
    for link in list(links)[:8]:
        art = safe_read(link, timeout=15)
        if not art or len(art) < 2000:
            continue
        title = ""
        for pat in [
            r"<title>(.*?)</title>",
            r'content="([^"]{20,150})"[^>]+property="og:title"',
        ]:
            m = re.search(pat, art, re.DOTALL | re.IGNORECASE)
            if m:
                title = ihtml.unescape(re.sub(r"<[^>]+>", "", m.group(1).strip()))
                if len(title) > 15:
                    break
        if not title:
            continue
        key = (title[:65], link[:45])
        if key in seen_set:
            continue
        seen_set.add(key)
        all_rows.append({
            "crawl_date": today_str,
            "event_date": today_str,
            "headline": title[:300],
            "body_text": "",
            "url": link[:500],
            "source": "goldprice.org",
            "category": "gold_global",
            "query_used": "goldprice_org",
        })
        cnt += 1
    return cnt


def crawl_yfinance(all_rows, seen_set):
    today_str = date.today().isoformat()
    try:
        import yfinance as yf
    except ImportError:
        return 0
    cnt = 0
    for sym in ["GC=F", "SI=F", "XAUUSD=X", "GOLD", "^VIX"]:
        try:
            ticker = yf.Ticker(sym)
        except Exception:
            continue
        for item in (ticker.news or [])[:15]:
            title = (item.get("title") or "").strip()
            if not title:
                continue
            pub_ts = item.get("providerPublishTime") or item.get("publishTime")
            pub = today_str
            if pub_ts:
                try:
                    pub = datetime.utcfromtimestamp(int(pub_ts)).date().isoformat()
                except Exception:
                    pass
            link = item.get("link") or item.get("url") or ""
            key = (title[:65], link[:45])
            if key in seen_set:
                continue
            seen_set.add(key)
            all_rows.append({
                "crawl_date": today_str,
                "event_date": pub,
                "headline": title[:300],
                "body_text": "",
                "url": link[:500],
                "source": f"yfinance:{sym}",
                "category": "gold_global",
                "query_used": "yfinance",
            })
            cnt += 1
    return cnt


def crawl_nhipcaudau(all_rows, seen_set):
    today_str = date.today().isoformat()
    raw = safe_read("https://nhipcaudautu.vn/tim-kiem?q=v%C3%A0ng+sjc")
    if not raw:
        return 0
    links_seen = set()
    links = []
    for m in re.finditer(r'href="(/[^"]*)"', raw):
        ref = m.group(1)
        if any(k in ref.lower() for k in ["vàng", "gold", "sjc", "tỷ", "usd", "kinh"]):
            full = "https://nhipcaudautu.vn" + ref
            if full not in links_seen:
                links_seen.add(full)
                links.append(full)
    cnt = 0
    for link in links[:8]:
        art = safe_read(link, timeout=15)
        if not art or len(art) < 800:
            continue
        title = ""
        for pat in [r"<title>(.*?)</title>", r"<h1[^>]*>(.*?)</h1>"]:
            m = re.search(pat, art, re.DOTALL | re.IGNORECASE)
            if m:
                title = ihtml.unescape(re.sub(r"<[^>]+>", "", m.group(1).strip()))
                if len(title) > 15:
                    break
        if not title:
            continue
        body = clean_html(art, 2000)
        key = (title[:65], link[:45])
        if key in seen_set:
            continue
        seen_set.add(key)
        all_rows.append({
            "crawl_date": today_str,
            "event_date": today_str,
            "headline": title[:300],
            "body_text": body,
            "url": link[:500],
            "source": "nhipcaudau",
            "category": category_of(title),
            "query_used": "nhipcaudau_search",
        })
        cnt += 1
    return cnt


# ============================================================
# MAIN
# ============================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="Crawl raw VN + global gold news text")
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print(" VN GOLD NEWS CRAWLER - Raw Text Data (multi-source)")
    print("=" * 55)

    today_str = date.today().isoformat()
    all_rows = []
    seen_set = set()
    existing_count = 0

    # Load existing
    if out_path.exists():
        with open(out_path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                k = (r["headline"][:65], r["url"][:45])
                if k not in seen_set:
                    seen_set.add(k)
                    all_rows.append(r)
                    existing_count += 1
        print(f"Loaded {existing_count} existing rows (dedup keys: {len(seen_set)})")

    # Phase 1: Google News RSS (broad VN + global coverage)
    print(f"\n--- Phase 1: Google News RSS ({len(ALL_QUERIES)} queries) ---")
    crawl_google_news(all_rows, seen_set)

    # Phase 2-6: Direct source RSS feeds
    print("\n--- Phase 2: Kitco ---")
    kitco_n = crawl_kitco(all_rows, seen_set)
    print(f"  +{kitco_n} from Kitco")

    print("--- Phase 3: Investing.com ---")
    inv_n = crawl_investing(all_rows, seen_set)
    print(f"  +{inv_n} from Investing.com")

    print("--- Phase 4: goldprice.org ---")
    gp_n = crawl_goldprice_org(all_rows, seen_set)
    print(f"  +{gp_n} from goldprice.org")

    print("--- Phase 5: yfinance news ---")
    yf_n = crawl_yfinance(all_rows, seen_set)
    print(f"  +{yf_n} from yfinance")

    print("--- Phase 6: nhipcaudautu.vn direct ---")
    ncd_n = crawl_nhipcaudau(all_rows, seen_set)
    print(f"  +{ncd_n} from nhipcaudau")

    # Stats
    print(f"\n{'=' * 55}")
    print(f"TOTAL: {len(all_rows)} rows  (new: {len(all_rows) - existing_count})")

    by_src = Counter(r["source"] for r in all_rows)
    print("By source:")
    for s, c in by_src.most_common():
        print(f"  {s}: {c}")

    by_cat = Counter(r["category"] for r in all_rows)
    print("By category:")
    for c, n in by_cat.most_common():
        print(f"  {c}: {n}")

    with_body = sum(1 for r in all_rows if r["body_text"].strip())
    print(f"Rows with body_text: {with_body}")

    monthly = Counter()
    for r in all_rows:
        d = r["event_date"] or r["crawl_date"]
        if len(d) >= 7:
            monthly[d[:7]] += 1
    print(f"\nMonth coverage: {len(monthly)} months, "
          f"range {min(monthly)} -> {max(monthly)}")

    # Write CSV
    fieldnames = [
        "crawl_date", "event_date", "headline", "body_text",
        "url", "source", "category", "query_used",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)
    print(f"\nWritten: {out_path} ({len(all_rows)} rows)")

    manifest = {
        "generated_at": today_str,
        "total_records": len(all_rows),
        "existing_inherited": existing_count,
        "new_rows": len(all_rows) - existing_count,
        "by_source": dict(by_src),
        "by_category": dict(by_cat),
        "rows_with_body_text": with_body,
        "date_range": {
            "from": min((r["event_date"] or r["crawl_date"]) for r in all_rows)
            if all_rows else "",
            "to": max((r["event_date"] or r["crawl_date"]) for r in all_rows)
            if all_rows else "",
        },
        "month_coverage": len(monthly),
        "queries_used": len(ALL_QUERIES),
        "sources_crawled": [
            "google_news_rss", "kitco_rss", "investing_com_rss",
            "goldprice_org", "yfinance", "nhipcaudau",
        ],
        "notes": (
            "Raw text news headlines + article bodies where fetched. "
            "Google News RSS: ~30-day lookback with indexed history. "
            "Dates are actual publication dates from RSS pubDate fields."
        ),
    }
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Manifest: {MANIFEST}")
    print("\nDONE")


if __name__ == "__main__":
    raise SystemExit(main())
