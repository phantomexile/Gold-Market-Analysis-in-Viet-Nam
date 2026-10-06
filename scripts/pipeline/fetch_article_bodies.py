#!/usr/bin/env python3
"""
Fetch article body text from URLs in news_raw_headlines_vietnam_gold.csv using Playwright Chromium.
This gives us REAL text content from Vietnamese news articles.

Updates news_raw_headlines_vietnam_gold.csv with body_text filled in.
"""
import csv, sys, asyncio, json, re
from datetime import date
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

try:
    from playwright.async_api import async_playwright, TimeoutError as PwTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: python -m pip install playwright")
    print("       then: python -m playwright install chromium")
    sys.exit(1)

NEWS_RAW = Path("data/lake/news_raw_headlines_vietnam_gold.csv")
MANIFEST = Path("data/lake/manifests") / "article_bodies_manifest.json"
MANIFEST.parent.mkdir(parents=True, exist_ok=True)

# Priority sources for body text extraction (Vietnamese gold news sites)
VN_SOURCES_PRIORITY = [
    "vnexpress.net", "tuoitre.vn", "thanhnien.vn", "vietnamnet.vn",
    "cafef.vn", "cafef", "laodong.vn", "congly.vn", "vov.vn",
    "vnnet.vn", "dantri.com.vn", "nhandan.com.vn", "vietnamnews.vn",
    "nhipcaudautu.vn",
]
GLOBAL_GOLD_SOURCES = [
    "kitco.com", "goldprice.org", "investing.com", "yahoo.com",
    "marketwatch.com", "cnbc.com", "reuters.com", "bloomberg",
]
TARGET_SELECTORS = [
    # cafef
    ".detail-cate .detail-content", ".detail-content",
    # tuoitre
    ".article-content", ".content-detail",
    # vnexpress
    ".fck_detail",
    # thanhnien
    ".body-content", ".article-body",
    # vietnamnet
    ".ArticleContent",
    # vietnaminer / vietnamnews
    ".vn-article-body",
    # dantri
    ".dt-news__body",
    # laodong
    ".article-body",
    # General
    "article", "[class*='content']", "[class*='article']",
]
SKIP_PATTERNS = [
    r'<(script|style|nav|header|footer|aside)[^>]*>',
    r'class="[^"]*(?:sidebar|related|comment|footer|header|nav|menu|social|share|advert)[^"]*"',
    r'id="[^"]*(?:sidebar|related|comment|footer|header|nav|menu|social|share)[^"]*"',
]
MIN_TEXT_LENGTH = 200


def clean_text(html_text: str) -> str:
    """Extract readable text from HTML."""
    text = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", "", html_text, flags=re.DOTALL | re.IGNORECASE)
    # Remove comments
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    # Remove common boilerplate
    text = re.sub(r'<(nav|header|footer|aside)[^>]*>.*?</\1>', "", text, flags=re.DOTALL | re.IGNORECASE)
    # Tag to text
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[pP][^>]*>", "\n", text)
    text = re.sub(r"</[pP]>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    # Whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n", "\n\n", text)
    return text.strip()


def extract_body_from_page(page_content: str, url: str) -> str:
    """Extract article body text from raw HTML."""
    # Try to find structured data first
    # 1. JSON-LD ArticleBody
    m = re.search(r'"articleBody"\s*:\s*"((?:[^"\\]|\\.)*)"', page_content)
    if m:
        text = m.group(1).replace("\\n", "\n").replace("\\\"", '"')
        text = re.sub(r'<[^>]+>', '', text)
        return text.strip()[:3000]

    # 2. og:description (long)
    m = re.search(r'property="og:description"\s+content="([^"]{100,})"', page_content, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:3000]

    # 3. meta[name=description] long
    m = re.search(r'name="description"\s+content="([^"]{150,})"', page_content, re.IGNORECASE)
    if m:
        return m.group(1).strip()[:3000]

    # Fallback: extract all paragraphs, clean
    return clean_text(page_content)[:3000]


async def fetch_article_text(context, url: str, timeout_ms: int = 15000) -> str:
    """Use Playwright to fetch and extract article text."""
    try:
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        # Wait a bit for JS rendering
        await asyncio.sleep(1.5)
        # Try targeted selectors first
        for sel in TARGET_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = await el.inner_text()
                    text = text.strip()
                    if len(text) > MIN_TEXT_LENGTH:
                        await page.close()
                        return text[:3000]
            except Exception:
                continue
        # Fallback: full page text
        body_text = await page.inner_text("body")
        await page.close()
        return body_text.strip()[:3000]
    except PwTimeout:
        return ""
    except Exception:
        return ""


async def run_batch(urls: list[tuple[int, str, str]], batch_size: int = 10) -> dict:
    """Fetch body text for URLs and return {row_idx: body_text}."""
    results = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="vi-VN",
        )
        total = len(urls)
        done = 0
        for i in range(0, total, batch_size):
            batch = urls[i:i + batch_size]
            tasks = []
            for idx, url, _src in batch:
                tasks.append(fetch_article_text(context, url))
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for (idx, url, src), body in zip(batch, batch_results):
                if isinstance(body, str) and body:
                    results[idx] = body
                done += 1
            sys.stdout.write(f"\r  Fetched {done}/{total} articles ({len(results)} with text)   ")
            sys.stdout.flush()
        await browser.close()
    sys.stdout.write("\n")
    return results


def is_target_url(url: str) -> bool:
    """Return True if this URL is worth trying to fetch body text from."""
    if not url.startswith("http"):
        return False
    # Google News redirect URLs are always worth fetching
    if "news.google.com" in url:
        return True
    host = url.split("/")[2] if "/" in url else url
    return any(h in host for h in VN_SOURCES_PRIORITY + GLOBAL_GOLD_SOURCES)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(NEWS_RAW))
    parser.add_argument("--max-articles", type=int, default=300,
                        help="Max articles to fetch body text for")
    parser.add_argument("--min-text-len", type=int, default=200)
    parser.add_argument("--priority-only", action="store_true",
                        help="Only fetch VN-specific sources")
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    print("=" * 55)
    print(" FETCH ARTICLE BODY TEXT (Playwright Chromium)")
    print("=" * 55)

    today_str = date.today().isoformat()

    # Load existing CSV
    rows = []
    with open(NEWS_RAW, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"Loaded: {len(rows)} rows from {NEWS_RAW}")

    # Find rows that need body text (empty body_text + target URL)
    candidates = []
    for i, r in enumerate(rows):
        if r.get("body_text", "").strip():
            continue
        url = r.get("url", "")
        if not is_target_url(url):
            continue
        if args.priority_only:
            host = url.split("/")[2] if "/" in url else ""
            if not any(h in host for h in VN_SOURCES_PRIORITY):
                continue
        candidates.append((i, url, r.get("source", "")))

    print(f"Candidates needing body text: {len(candidates)}")
    if not candidates:
        print("Nothing to fetch. Done.")
        return

    # Limit
    candidates = candidates[:args.max_articles]
    print(f"Will fetch: {len(candidates)} articles")

    # Fetch body text via Playwright
    print(f"\nLaunching Chromium (batch={args.batch_size})...")
    results = asyncio.run(run_batch(candidates, batch_size=args.batch_size))

    # Update rows
    updated = 0
    for idx, body in results.items():
        if len(body) >= args.min_text_len:
            rows[idx]["body_text"] = body[:3000]
            updated += 1

    print(f"Updated body_text: {updated} rows")

    # Write back
    fields = ["crawl_date", "event_date", "headline", "body_text",
              "url", "source", "category", "query_used"]
    with open(NEWS_RAW, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Written: {NEWS_RAW}")

    with_body = sum(1 for r in rows if r.get("body_text", "").strip())
    print(f"Total rows with body_text: {with_body}")

    # Source breakdown for fetched articles
    fetched_sources = Counter()
    for idx in results:
        fetched_sources[rows[idx]["source"]] += 1
    print("\nFetched by source:")
    for s, c in fetched_sources.most_common():
        print(f"  {s}: {c}")

    # Manifest
    manifest = {
        "generated_at": today_str,
        "total_rows": len(rows),
        "with_body_text": with_body,
        "articles_fetched_this_run": updated,
        "candidates": len(candidates),
        "batch_size": args.batch_size,
        "min_text_len": args.min_text_len,
        "priority_only": args.priority_only,
        "fetched_by_source": dict(fetched_sources),
        "notes": f"Playwright Chromium body text extraction. {updated} articles updated.",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifest: {MANIFEST}")
    print("\nDONE")


if __name__ == "__main__":
    raise SystemExit(main())
