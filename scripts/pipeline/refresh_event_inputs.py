#!/usr/bin/env python3
"""Làm mới tin tức và chỉ số GPR có nguồn, ngày công bố rõ ràng."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
LAKE = ROOT / "data" / "lake"
NEWS_PATH = LAKE / "news_raw_headlines_vietnam_gold.csv"
GPR_PATH = LAKE / "gpr_daily_geopolitical_risk.csv"
REGIME_PATH = LAKE / "pipeline_output_event_regime.csv"
MANIFEST_PATH = LAKE / "manifests" / "event_inputs_refresh.json"
GPR_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
QUERIES = (
    "giá vàng SJC when:14d",
    "Ngân hàng Nhà nước vàng miếng when:14d",
    "tỷ giá USD VND vàng when:14d",
    "Fed gold price when:14d",
    "geopolitical risk gold when:14d",
)


def fetch(url: str) -> bytes:
    """Tải dữ liệu gốc; lỗi mạng phải hiện ra để không gắn nhãn 'đã cập nhật' sai."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 GoldResearch/1.0"})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read()


def parse_rss_items(xml_bytes: bytes, query: str, today: date) -> list[dict[str, str]]:
    """Chỉ nhận tin có tiêu đề, URL và pubDate hợp lệ không ở tương lai."""
    rows: list[dict[str, str]] = []
    for item in ET.fromstring(xml_bytes).findall(".//item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        if not title or not url or not published or not url.startswith("https://"):
            continue
        try:
            published_day = parsedate_to_datetime(published).date()
        except (TypeError, ValueError, IndexError):
            continue
        if published_day > today:
            continue
        source_node = item.find("source")
        publisher = (source_node.text or "").strip() if source_node is not None else ""
        text = title.lower()
        category = (
            "gold_vn" if any(word in text for word in ("vàng", "sjc", "doji"))
            else "fx_vnd" if "vnd" in text or "tỷ giá" in text
            else "policy_rates" if "fed" in text or "rate" in text
            else "other"
        )
        rows.append({
            "crawl_date": today.isoformat(),
            "event_date": published_day.isoformat(),
            "headline": title,
            "body_text": "",
            "url": url,
            "source": f"google_news_rss:{publisher or 'unknown'}",
            "category": category,
            "query_used": query,
            "fetched_at": today.isoformat(),
            "published_at": published_day.isoformat(),
            "query": query,
            "provider": "google_news_rss",
            "url_hash": "",
            "availability_from": today.isoformat(),
            "feature_mode_strict": "backfilled_not_realtime",
            "backfill_lag_days": str((today - published_day).days),
        })
    return rows


def merge_news_rows(existing: list[dict[str, str]], new: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Giữ metadata cũ và tránh nhân đôi tin khi nhiều truy vấn cùng trả về URL."""
    merged = list(existing)
    seen = {row.get("url", "") for row in existing if row.get("url")}
    added = 0
    for row in new:
        url = row.get("url", "")
        if not url or url in seen:
            continue
        merged.append(row)
        seen.add(url)
        added += 1
    return merged, added


def prepare_gpr(source: pd.DataFrame, current: pd.DataFrame, today: date) -> pd.DataFrame:
    """Ghép GPR từ bản công bố chính thức theo ngày, không điền giá trị giả cho ngày trống."""
    required = {"date", "GPRD"}
    if not required.issubset(source.columns):
        raise ValueError(f"Nguồn GPR thiếu cột {sorted(required - set(source.columns))}")
    source = source.copy()
    source["date"] = pd.to_datetime(source["date"], errors="coerce")
    source = source.loc[source["date"].notna() & (source["date"].dt.date <= today)]
    source = source.loc[pd.to_numeric(source["GPRD"], errors="coerce").notna()]
    source["date"] = source["date"].dt.strftime("%Y-%m-%d")
    columns = current.columns.tolist()
    combined = pd.concat([current, source.reindex(columns=columns)], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"], keep="last").sort_values("date")
    return combined.reset_index(drop=True)


def new_regime_rows(news: list[dict[str, str]], existing: list[dict[str, str]], today: date) -> list[dict[str, str]]:
    """Biến tin vừa thu thập thành event proxy, giữ URL để truy lại bài gốc."""
    seen = {row.get("source_url", "") for row in existing if row.get("source_url")}
    rows: list[dict[str, str]] = []
    for item in news:
        published = item.get("event_date", "")
        url = item.get("url", "")
        title = item.get("headline", "")
        if not published or not url or url in seen:
            continue
        text = title.lower()
        # Thứ tự này ưu tiên chính sách và rủi ro vĩ mô trước biến động giá vàng.
        if any(term in text for term in ("ngân hàng nhà nước", "nhnn", "sbv", "đấu thầu vàng")):
            event_type, channel, severity, scope = "sbv_policy", "policy_auction", "high", "domestic_vietnam"
        elif any(term in text for term in ("chiến tranh", "xung đột", "geopolitical", "war", "iran", "ukraine")):
            event_type, channel, severity, scope = "geopolitical", "safe_haven_buy", "high", "global"
        elif any(term in text for term in ("tỷ giá", "usd/vnd")):
            event_type, channel, severity, scope = "fx_shock", "fx_pass_through", "medium", "domestic_vietnam"
        elif any(term in text for term in ("fed", "fomc", "interest rate")):
            event_type, channel, severity, scope = "policy_rate_global", "safe_haven_buy", "medium", "global"
        elif any(term in text for term in ("vàng", "gold", "sjc")):
            event_type, channel, severity, scope = "gold_price_move", "safe_haven_buy", "medium", "domestic_vietnam"
        else:
            continue
        seen.add(url)
        rows.append({
            "build_timestamp": datetime.now(timezone.utc).isoformat(),
            "data_lineage": f"Google News RSS; published_at={published}; fetched_at={today.isoformat()}",
            "effective_from": published,
            "effective_to": published,
            "event_date": published,
            "event_type": event_type,
            "expected_channel": channel,
            "is_active": str(published == today.isoformat()).lower(),
            "note": title,
            "scope": scope,
            "severity": severity,
            "source": "google_news_rss_event_proxy",
            "source_url": url,
        })
    return rows


def _write_news(rows: list[dict[str, str]]) -> None:
    """Ghi UTF-8 qua tệp tạm để lỗi ghi không làm hỏng bảng cũ."""
    fields = list(dict.fromkeys(key for row in rows for key in row))
    temp = NEWS_PATH.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(NEWS_PATH)


def refresh(today: date | None = None) -> dict[str, object]:
    """Lấy tin RSS và GPR; chỉ ghi dữ liệu khi nguồn mới vượt qua kiểm tra tối thiểu."""
    today = today or date.today()
    with NEWS_PATH.open(encoding="utf-8", newline="") as handle:
        old_news = list(csv.DictReader(handle))
    with REGIME_PATH.open(encoding="utf-8", newline="") as handle:
        regime_reader = csv.DictReader(handle)
        regime_fields = list(regime_reader.fieldnames or [])
        old_regime = list(regime_reader)
    current_gpr = pd.read_csv(GPR_PATH)
    old_gpr_max = str(current_gpr["date"].max())

    # Tải và kiểm tra tất cả nguồn trước khi thay đổi hai bảng đầu vào của model.
    news: list[dict[str, str]] = []
    for query in QUERIES:
        params = urllib.parse.urlencode({"q": query, "hl": "vi", "gl": "VN", "ceid": "VN:vi"})
        news.extend(parse_rss_items(fetch(f"https://news.google.com/rss/search?{params}"), query, today))
    if not news:
        raise ValueError("RSS không trả về tin có ngày công bố hợp lệ; dữ liệu cũ được giữ nguyên.")
    merged, added = merge_news_rows(old_news, news)
    regime_added = new_regime_rows(news, old_regime, today)

    try:
        import xlrd  # noqa: F401  # Excel .xls của tác giả GPR cần thư viện này.
    except ImportError as exc:
        raise RuntimeError("Cần cài xlrd để đọc GPR .xls chính thức.") from exc
    source = pd.read_excel(io.BytesIO(fetch(GPR_URL)), engine="xlrd")
    updated_gpr = prepare_gpr(source, current_gpr, today)
    new_gpr_max = str(updated_gpr["date"].max())
    if new_gpr_max < old_gpr_max:
        raise ValueError("Nguồn GPR cũ hơn bảng hiện có; không ghi đè dữ liệu.")

    _write_news(merged)
    # Event proxy được nối vào đúng bảng mà decision_support.py ưu tiên đọc.
    regime_temp = REGIME_PATH.with_suffix(".csv.tmp")
    with regime_temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=regime_fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(old_regime + regime_added)
    regime_temp.replace(REGIME_PATH)
    gpr_temp = GPR_PATH.with_suffix(".csv.tmp")
    updated_gpr.to_csv(gpr_temp, index=False, encoding="utf-8")
    gpr_temp.replace(GPR_PATH)
    result = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "news_source": "https://news.google.com/rss/search",
        "news_total": len(merged),
        "news_added": added,
        "regime_event_proxies_added": len(regime_added),
        "regime_total": len(old_regime) + len(regime_added),
        "news_latest_published": max(row["event_date"] for row in merged if row.get("event_date")),
        "news_new_min_published": min(row["event_date"] for row in news),
        "news_new_max_published": max(row["event_date"] for row in news),
        "gpr_source": GPR_URL,
        "gpr_old_latest": old_gpr_max,
        "gpr_latest": new_gpr_max,
        "gpr_rows": len(updated_gpr),
        "note": "Tin RSS có ngày công bố; ngày thu thập được lưu riêng. GPR theo bản phát hành chính thức.",
    }
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Làm mới tin vàng và chỉ số GPR có ngày nguồn.")
    parser.parse_args()
    print(json.dumps(refresh(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
