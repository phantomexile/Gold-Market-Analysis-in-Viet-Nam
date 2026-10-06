#!/usr/bin/env python3
"""
Collect official SBV/NHNN gold-policy and auction events.

This crawler uses Playwright because SBV pages and same-origin CMS APIs can be
blocked for direct HTTP clients. It only records events with an official SBV URL
and never expands weekly synthetic auction schedules.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Playwright is required for SBV event collection: {exc}")


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "data" / "lake" / "events"
DISCOVERY_JSON = ROOT / "data" / "lake" / "source_discovery" / "sbv_structures.json"
SBV_HOST = "sbv.gov.vn"
SEEDS = [
    "https://sbv.gov.vn/vi/quan-ly-hoat-dong-ngoai-hoi-va-hoat-dong-kinh-doanh-vang",
    "https://sbv.gov.vn/vi/",
]

KEYWORDS = [
    "đấu thầu vàng",
    "dau thau vang",
    "vàng miếng",
    "vang mieng",
    "sjc",
    "kinh doanh vàng",
    "kinh doanh vang",
    "bán vàng",
    "ban vang",
    "nhnn bán vàng",
    "ngân hàng nhà nước bán vàng",
    "quản lý thị trường vàng",
]


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def infer_event_type(text: str) -> tuple[str, str]:
    lower = text.lower()
    if "đấu thầu" in lower or "dau thau" in lower:
        return "policy_auction", "high"
    if "bán vàng" in lower or "ban vang" in lower or "vàng miếng" in lower or "vang mieng" in lower:
        return "gold_sale_policy", "medium"
    if "thanh tra" in lower or "kiểm tra" in lower or "kiem tra" in lower:
        return "inspection", "medium"
    if "thông tư" in lower or "quyết định" in lower or "quyet dinh" in lower or "nghị định" in lower:
        return "circular_decision", "medium"
    if "nhập khẩu" in lower or "nhap khau" in lower or "nguồn cung" in lower:
        return "import_supply", "medium"
    return "gold_policy", "low"


def parse_date_from_text(text: str) -> str:
    patterns = [
        (r"(\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),
        (r"(\d{1,2}/\d{1,2}/\d{4})", "%d/%m/%Y"),
        (r"(\d{1,2}-\d{1,2}-\d{4})", "%d-%m-%Y"),
    ]
    for pattern, fmt in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            return datetime.strptime(match.group(1), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def official_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.endswith(SBV_HOST)


def collect_candidate_links(page: Any, seeds: list[str], max_links: int) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    candidates: dict[str, dict[str, str]] = {}
    statuses: list[dict[str, Any]] = []
    for seed in seeds:
        row = {"seed_url": seed, "status": "unknown", "links_seen": 0, "candidate_links": 0, "error": ""}
        try:
            response = page.goto(seed, wait_until="networkidle", timeout=90000)
            row["status"] = response.status if response else "no_response"
            page.wait_for_timeout(1500)
            anchors = page.evaluate(
                """
                () => Array.from(document.querySelectorAll('a')).map(a => ({
                  href: a.href || '',
                  text: (a.innerText || a.textContent || '').trim()
                }))
                """
            )
            row["links_seen"] = len(anchors)
            for anchor in anchors:
                href = urljoin(seed, str(anchor.get("href") or ""))
                text = normalize_text(anchor.get("text"))
                hay = f"{href} {text}".lower()
                if not official_url(href):
                    continue
                if any(keyword in hay for keyword in KEYWORDS):
                    candidates[href] = {"url": href, "anchor_text": text, "seed_url": seed}
                    if len(candidates) >= max_links:
                        break
            row["candidate_links"] = len(candidates)
        except Exception as exc:  # noqa: BLE001
            row["status"] = "error"
            row["error"] = f"{type(exc).__name__}: {exc}"
        statuses.append(row)
    return list(candidates.values())[:max_links], statuses


def collect_discovery_endpoint_candidates() -> list[dict[str, str]]:
    if not DISCOVERY_JSON.exists():
        return []
    try:
        rows = json.loads(DISCOVERY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return []
    candidates: list[dict[str, str]] = []
    for row in rows:
        if row.get("classification") not in {"gold_policy_candidate", "policy_document_candidate"}:
            continue
        for raw in str(row.get("source_url_samples", "")).split(" || "):
            url = raw.strip()
            if url.startswith("/"):
                url = urljoin("https://sbv.gov.vn", url)
            if official_url(url):
                candidates.append({"url": url, "anchor_text": row.get("title_samples", ""), "seed_url": "discovery_catalog"})
    return candidates


def parse_article(page: Any, candidate: dict[str, str]) -> dict[str, Any] | None:
    url = candidate["url"]
    try:
        response = page.goto(url, wait_until="networkidle", timeout=90000)
        status = response.status if response else None
        page.wait_for_timeout(1000)
        title = normalize_text(page.title())
        body = normalize_text(page.locator("body").inner_text(timeout=15000))
        html = page.content()
    except Exception as exc:  # noqa: BLE001
        return {
            "event_date": "",
            "published_at": "",
            "title": normalize_text(candidate.get("anchor_text")),
            "event_type": "crawl_error",
            "severity": "low",
            "source_url": url,
            "source_type": "official_sbv_article",
            "confidence": 0.0,
            "raw_hash": "",
            "note": f"{type(exc).__name__}: {exc}",
        }

    if not body:
        return None
    hay = f"{title} {candidate.get('anchor_text', '')} {body[:5000]}"
    if not any(keyword in hay.lower() for keyword in KEYWORDS):
        return None

    event_type, severity = infer_event_type(hay)
    published = parse_date_from_text(body) or parse_date_from_text(title) or ""
    event_date = published
    headline = normalize_text(candidate.get("anchor_text")) or title
    if len(headline) < 10:
        # Use the first body line that looks like a headline.
        headline = normalize_text(body.split(".")[0])[:240] or title
    confidence = 0.92 if published and status and 200 <= int(status) < 300 else 0.70
    return {
        "event_date": event_date,
        "published_at": published,
        "title": headline[:280],
        "event_type": event_type,
        "severity": severity,
        "source_url": url,
        "source_type": "official_sbv_article",
        "confidence": confidence,
        "raw_hash": hashlib.sha256(html.encode("utf-8", errors="replace")).hexdigest(),
        "note": f"seed={candidate.get('seed_url', '')}; http_status={status}",
    }


def write_outputs(rows: list[dict[str, Any]], statuses: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sbv_gold_policy_events.csv"
    status_path = out_dir / "sbv_gold_policy_events_status.json"
    fieldnames = [
        "event_date",
        "published_at",
        "title",
        "event_type",
        "severity",
        "source_url",
        "source_type",
        "confidence",
        "raw_hash",
        "note",
    ]
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for row in sorted(rows, key=lambda r: (r.get("event_date") or "9999-99-99", r.get("source_url", ""))):
        key = (str(row.get("event_date", "")), str(row.get("source_url", "")), str(row.get("event_type", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(deduped)

    status_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(deduped),
        "date_min": min((r["event_date"] for r in deduped if r.get("event_date")), default=""),
        "date_max": max((r["event_date"] for r in deduped if r.get("event_date")), default=""),
        "synthetic_events_used": False,
        "blockers": [],
        "navigation_statuses": statuses,
        "output_csv": str(csv_path),
    }
    if not deduped:
        status_payload["blockers"].append(
            "No verified official SBV gold-policy events were extracted from the current seed pages."
        )
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect official SBV gold policy/auction events.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--max-links", type=int, default=80)
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rows: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        link_candidates, nav_statuses = collect_candidate_links(page, SEEDS, args.max_links)
        statuses.extend(nav_statuses)
        endpoint_candidates = collect_discovery_endpoint_candidates()
        all_candidates = {c["url"]: c for c in link_candidates + endpoint_candidates}
        for candidate in list(all_candidates.values())[: args.max_links]:
            event = parse_article(page, candidate)
            if event:
                rows.append(event)
        browser.close()

    write_outputs(rows, statuses, Path(args.out_dir))
    print(json.dumps({"events": len(rows), "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
