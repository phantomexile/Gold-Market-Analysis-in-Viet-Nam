#!/usr/bin/env python3
"""
Discover SBV/NHNN public CMS sources with a real Playwright browser session.

Direct requests to the SBV headless CMS are often rejected by the edge layer.
This script opens official SBV pages first, then uses same-origin fetch calls
inside the browser session. It writes a source catalog; it does not invent a
deposit-rate dataset when the correct source cannot be identified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import sync_playwright
except Exception as exc:  # pragma: no cover
    raise SystemExit(f"Playwright is required for SBV discovery: {exc}")


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT / "data" / "lake" / "source_discovery"
SBV_ORIGIN = "https://sbv.gov.vn"
STRUCTURE_RE = re.compile(r"content-structures/(\d+)/structured-contents")
NUM_RE = re.compile(r"\b\d{5,}\b")

SEED_URLS = [
    "https://sbv.gov.vn/vi/",
    "https://sbv.gov.vn/vi/bieu-do-ty-gia-trung-tam",
    "https://sbv.gov.vn/vi/quan-ly-hoat-dong-ngoai-hoi-va-hoat-dong-kinh-doanh-vang",
]

# Known verified structure: central USD/VND rate, not deposit rates.
KNOWN_STRUCTURE_IDS = {"137473"}


def content_fields(item: dict[str, Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field in item.get("contentFields", []) or []:
        value = field.get("contentFieldValue") or {}
        fields[str(field.get("name", ""))] = str(value.get("data", "") or "")
    return fields


def classify_structure(field_names: list[str], titles: list[str], seed_hits: list[str]) -> tuple[str, str]:
    haystack = " ".join(field_names + titles + seed_hits).lower()
    if {"tygiaso", "tygiachu", "ngaybatdau"} & {f.lower() for f in field_names}:
        return "central_fx", "verified: fields match SBV central USD/VND rate"
    if any(k in haystack for k in ["lãi suất", "lai suat", "interest", "refinance", "tái cấp vốn", "liên ngân hàng"]):
        return "interest_rate_candidate", "candidate: text mentions SBV/market interest rates"
    if any(k in haystack for k in ["đấu thầu vàng", "dau thau vang", "vàng miếng", "sjc", "kinh doanh vàng"]):
        return "gold_policy_candidate", "candidate: text mentions gold auction/SJC/gold policy"
    if any(k in haystack for k in ["thông tư", "quyết định", "chỉ thị", "quy che", "quy chế"]):
        return "policy_document_candidate", "candidate: text mentions official policy documents"
    return "unknown", "not enough evidence to classify"


def browser_fetch_structure(page: Any, structure_id: str, page_size: int) -> dict[str, Any]:
    endpoint = f"/vi/o/headless-delivery/v1.0/content-structures/{structure_id}/structured-contents?pageSize={page_size}&sort=datePublished:desc"
    result = page.evaluate(
        """
        async ({endpoint}) => {
          const response = await fetch(endpoint, {method: "GET"});
          const text = await response.text();
          return {status: response.status, text};
        }
        """,
        {"endpoint": endpoint},
    )
    raw_text = result.get("text", "")
    payload: dict[str, Any]
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        payload = {"raw_text_prefix": raw_text[:500]}
    payload["_http_status"] = result.get("status")
    payload["_raw_hash"] = hashlib.sha256(raw_text.encode("utf-8", errors="replace")).hexdigest()
    payload["_endpoint"] = SBV_ORIGIN + endpoint
    return payload


def extract_candidate_ids(page_html: str, response_urls: list[str]) -> set[str]:
    ids = set(KNOWN_STRUCTURE_IDS)
    for url in response_urls:
        match = STRUCTURE_RE.search(url)
        if match:
            ids.add(match.group(1))
    for match in STRUCTURE_RE.finditer(page_html):
        ids.add(match.group(1))
    for raw in NUM_RE.findall(page_html):
        # Liferay content structure IDs observed on SBV are six digits. Keep the
        # filter broad enough for future IDs but avoid collecting dates/amounts.
        if 10000 <= int(raw) <= 9999999:
            around = page_html[max(0, page_html.find(raw) - 120): page_html.find(raw) + 120].lower()
            if "structure" in around or "structured-content" in around or "content" in around:
                ids.add(raw)
    return ids


def summarize_payload(structure_id: str, payload: dict[str, Any], seed_hits: list[str]) -> dict[str, Any]:
    items = payload.get("items", []) if isinstance(payload, dict) else []
    fields_seen: set[str] = set()
    titles: list[str] = []
    published: list[str] = []
    source_urls: list[str] = []
    sample_fields: list[dict[str, str]] = []

    for item in items[:10]:
        fields = content_fields(item)
        fields_seen.update(k for k in fields if k)
        if len(sample_fields) < 3:
            sample_fields.append(fields)
        title = str(item.get("title", "") or "")
        if title:
            titles.append(title[:180])
        pub = str(item.get("datePublished", "") or "")[:10]
        if pub:
            published.append(pub)
        source_url = str(item.get("friendlyUrlPath", "") or item.get("contentUrl", "") or item.get("renderedContents", "") or "")
        if source_url:
            source_urls.append(source_url[:250])

    field_names = sorted(fields_seen)
    classification, note = classify_structure(field_names, titles, seed_hits)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "content_structure_id": structure_id,
        "classification": classification,
        "classification_note": note,
        "http_status": payload.get("_http_status"),
        "row_count_sample": len(items),
        "date_min_sample": min(published) if published else "",
        "date_max_sample": max(published) if published else "",
        "field_names": "|".join(field_names),
        "title_samples": " || ".join(titles[:5]),
        "source_url_samples": " || ".join(source_urls[:5]),
        "seed_hits": " || ".join(seed_hits),
        "endpoint_url": payload.get("_endpoint", ""),
        "raw_hash": payload.get("_raw_hash", ""),
        "is_central_fx": classification == "central_fx",
        "is_interest_rate_candidate": classification == "interest_rate_candidate",
        "is_gold_policy_candidate": classification == "gold_policy_candidate",
        "sample_fields_json": json.dumps(sample_fields, ensure_ascii=False),
    }


def write_outputs(rows: list[dict[str, Any]], statuses: list[dict[str, Any]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "sbv_structures.json"
    csv_path = out_dir / "sbv_structures.csv"
    status_path = out_dir / "sbv_source_discovery_status.json"

    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    if rows:
        fieldnames = list(rows[0].keys())
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("", encoding="utf-8")

    central_fx_ok = any(r["content_structure_id"] == "137473" and r["classification"] == "central_fx" for r in rows)
    interest_candidates = [r for r in rows if r["classification"] == "interest_rate_candidate"]
    gold_candidates = [r for r in rows if r["classification"] == "gold_policy_candidate"]
    status_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "rows": len(rows),
        "central_fx_structure_137473_verified": central_fx_ok,
        "interest_rate_candidates": len(interest_candidates),
        "gold_policy_candidates": len(gold_candidates),
        "blockers": [],
        "navigation_statuses": statuses,
        "outputs": {
            "csv": str(csv_path),
            "json": str(json_path),
        },
    }
    if not interest_candidates:
        status_payload["blockers"].append(
            "No verified SBV deposit/interest-rate content structure found; structure 137473 is central USD/VND FX."
        )
    if not gold_candidates:
        status_payload["blockers"].append(
            "No SBV gold-policy content structure was discoverable from seed pages; use article/category crawl as fallback."
        )
    status_path.write_text(json.dumps(status_payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover SBV/NHNN content structures using Playwright.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--headful", action="store_true")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    response_urls: list[str] = []
    seed_hits: dict[str, list[str]] = {}
    page_html_parts: list[str] = []
    statuses: list[dict[str, Any]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headful)
        context = browser.new_context(locale="vi-VN")
        page = context.new_page()
        page.on("response", lambda response: response_urls.append(response.url))

        for seed in SEED_URLS:
            status_row = {"seed_url": seed, "status": "unknown", "error": ""}
            try:
                response = page.goto(seed, wait_until="networkidle", timeout=90000)
                status_row["status"] = str(response.status if response else "no_response")
                page.wait_for_timeout(1500)
                html = page.content()
                page_html_parts.append(html)
                title = page.title()
                body_text = page.locator("body").inner_text(timeout=10000)[:2000]
                for sid in extract_candidate_ids(html + body_text, response_urls):
                    seed_hits.setdefault(sid, []).append(f"{seed} :: {title}")
            except Exception as exc:  # noqa: BLE001
                status_row["status"] = "error"
                status_row["error"] = f"{type(exc).__name__}: {exc}"
            statuses.append(status_row)

        candidate_ids = extract_candidate_ids("\n".join(page_html_parts), response_urls)
        rows = []
        for sid in sorted(candidate_ids, key=lambda x: int(x)):
            try:
                payload = browser_fetch_structure(page, sid, args.page_size)
                rows.append(summarize_payload(sid, payload, seed_hits.get(sid, [])))
            except Exception as exc:  # noqa: BLE001
                rows.append(
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "content_structure_id": sid,
                        "classification": "error",
                        "classification_note": f"{type(exc).__name__}: {exc}",
                        "http_status": "",
                        "row_count_sample": 0,
                        "date_min_sample": "",
                        "date_max_sample": "",
                        "field_names": "",
                        "title_samples": "",
                        "source_url_samples": "",
                        "seed_hits": " || ".join(seed_hits.get(sid, [])),
                        "endpoint_url": "",
                        "raw_hash": "",
                        "is_central_fx": False,
                        "is_interest_rate_candidate": False,
                        "is_gold_policy_candidate": False,
                        "sample_fields_json": "[]",
                    }
                )
        browser.close()

    write_outputs(rows, statuses, Path(args.out_dir))
    print(json.dumps({"structures": len(rows), "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
