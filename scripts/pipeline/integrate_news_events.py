#!/usr/bin/env python3
"""
Integrate raw news headlines into the event panel.
Takes news_raw_headlines_vietnam_gold.csv headlines, classifies them into event types,
merges with existing news_events.csv and gold_event_panel.csv.
"""
import csv, sys, json, re
from datetime import date
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")

NEWS_RAW = Path("data/lake/news_raw_headlines_vietnam_gold.csv")
NEWS_EVENTS = Path("data/lake/news_events.csv")
EVENT_PANEL = Path("data/lake/gold_event_panel.csv")
OUT_EVENTS = Path("data/lake/news_events.csv")
MANIFEST = Path("data/lake/manifests") / "news_integration_manifest.json"
MANIFEST.parent.mkdir(parents=True, exist_ok=True)


def classify_headline_to_event(title: str) -> tuple[str, str, str]:
    """Classify headline into (event_type, scope, severity)."""
    t = title.lower()
    # Gold price up
    if any(k in t for k in ["vàng tăng", "vàng lên", "vàng bứt phá", "vàng vượt",
                              "vàng đỉnh", "vàng cao", "vàng sốt", "vàng nóng",
                              "gold surge", "gold rally", "gold soar", "gold spike",
                              "gold record", "gold high", "gold climbs"]):
        return "gold_price_up", "domestic_vietnam", "high"
    # Gold price down
    if any(k in t for k in ["vàng giảm", "vàng rơi", "vàng sập", "vàng lao dốc",
                              "vàng thấp", "vàng đáy", "vàng biến động giảm",
                              "gold plunge", "gold drop", "gold fall", "gold slide",
                              "gold tumble", "gold weak"]):
        return "gold_price_down", "domestic_vietnam", "high"
    # SJC specific
    if any(k in t for k in ["sjc tăng", "sjc giảm", "sjc giá", "sjc hôm nay",
                              "vàng miếng sjc"]):
        base = "gold_price_up" if "tăng" in t or "lên" in t or "cao" in t else ("gold_price_down" if "giảm" in t or "rơi" in t or "thấp" in t else "gold_price_move")
        return base, "domestic_vietnam", "medium"
    # NHNN policy / auction
    if any(k in t for k in ["ngân hàng nhà nước", "nhnn", "đấu thầu vàng",
                              "nhập vàng", "xuất vàng", "dự trữ vàng",
                              "sbv", "thông tư", "quyết định vàng"]):
        return "sbv_policy", "domestic_vietnam", "high"
    # Exchange rate / USD
    if any(k in t for k in ["tỷ giá", "usd/vnd", "usd tăng", "usd giảm",
                              "đồng usd", "đồng mất giá", "đồng tăng giá",
                              "usd/vnd biến động"]):
        return "fx_shock", "domestic_vietnam", "medium"
    # Fed / global rates
    if any(k in t for k in ["fed", "fomc", "lãi suất mỹ", "interest rate",
                              "ecb", "ngân hàng trung ương", "central bank",
                              "cut rate", "hike rate", "cắt lãi", "tăng lãi"]):
        return "policy_rate_global", "global", "high"
    # Crisis / war / geopolitical
    if any(k in t for k in ["chiến tranh", "xung đột", "căng thẳng", "tấn công",
                              "ukraine", "russia", "israel", "iran", "trung đông",
                              "war", "invasion", "sanctions", "geopolitical"]):
        return "geopolitical", "global", "high"
    # COVID / health crisis
    if any(k in t for k in ["covid", "corona", "dịch bệnh", "lockdown",
                              "phong tỏa", "đại dịch"]):
        return "crisis_health", "domestic_vietnam", "high"
    # Import / export gold
    if any(k in t for k in ["nhập siêu vàng", "vàng nhập khẩu", "vàng xuất khẩu",
                              "gold import", "gold export", "nhập vàng"]):
        return "trade_gold", "domestic_vietnam", "medium"
    # Inflation / macro
    if any(k in t for k in ["lạm phát", "inflation", "cpi", "consumer price",
                              "giá cả", "sản xuất", "gdp", "tăng trưởng"]):
        return "macro_shock", "domestic_vietnam", "medium"
    # Tết / seasonal
    if any(k in t for k in ["tết", "thần tài", "ngày vía thần tài",
                              "lunar new year", "gold buying season",
                              "mua vàng cầu may"]):
        return "seasonal_tet", "domestic_vietnam", "low"
    # Gold price general (no direction)
    if any(k in t for k in ["vàng giá", "giá vàng", "gold price",
                              "bảng giá vàng", "cập nhật giá vàng",
                              "gold fix", "lbma", "london gold"]):
        return "gold_price_move", "domestic_vietnam", "medium"
    # Default
    return "news_other", "global", "low"


def infer_channel(event_type: str) -> str:
    mapping = {
        "gold_price_up": "premium_spike",
        "gold_price_down": "premium_drop",
        "gold_price_move": "safe_haven_buy",
        "sbv_policy": "policy_auction",
        "fx_shock": "fx_pass_through",
        "policy_rate_global": "safe_haven_buy",
        "geopolitical": "safe_haven_buy",
        "crisis_health": "safe_haven_buy",
        "trade_gold": "supply_scarcity",
        "macro_shock": "inflation_hedge",
        "seasonal_tet": "seasonal_demand",
    }
    return mapping.get(event_type, "unknown")


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_news_headlines() -> list[dict]:
    with open(NEWS_RAW, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT_EVENTS))
    parser.add_argument("--min-score", type=int, default=0,
                        help="Only keep headlines with category score >= min")
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print("=" * 55)
    print(" INTEGRATE NEWS HEADLINES INTO EVENT PANEL")
    print("=" * 55)

    # Load existing events
    existing = load_events(NEWS_EVENTS)
    print(f"\nExisting gold_news_events: {len(existing)} rows")

    # Load headlines
    headlines = load_news_headlines()
    print(f"Loaded headlines: {len(headlines)}")

    # Map category -> score (higher = more gold-relevant)
    cat_scores = {
        "gold_vn": 2,
        "gold_price": 2,
        "policy_rates": 1,
        "fx_vnd": 1,
        "macro": 1,
        "equity": 0,
        "other": 0,
    }

    # Convert headlines to event records
    new_events = []
    seen_dates = set()
    if existing:
        seen_dates = {(e["event_date"], e.get("note", "")[:60])
                      for e in existing}

    for h in headlines:
        cat = h.get("category", "other")
        score = cat_scores.get(cat, 0)
        if score < args.min_score:
            continue

        event_type, scope, severity = classify_headline_to_event(h["headline"])
        note = h["headline"][:200]
        # Dedup key: date + first 60 chars of headline
        dedup_key = (h.get("event_date", ""), note[:60])
        if dedup_key in seen_dates:
            continue
        seen_dates.add(dedup_key)

        new_events.append({
            "event_date": h.get("event_date", ""),
            "event_type": event_type,
            "scope": scope,
            "severity": severity,
            "expected_channel": infer_channel(event_type),
            "note": note,
            "source_url": h.get("url", "")[:300],
            "effective_from": h.get("event_date", ""),
            "effective_to": h.get("event_date", ""),
            "source": h.get("source", "google_news_rss"),
            "publisher": "",
            "headline": h["headline"][:300],
            "body_text": h.get("body_text", "")[:500],
            "query_used": h.get("query_used", ""),
            "relevance_score": str(score),
        })

    print(f"New events from headlines: {len(new_events)}")

    # Merge (dedup by event_date + note first 60 chars)
    merged = list(existing)
    existing_keys = {(e["event_date"], e.get("note", "")[:60]) for e in existing}
    added = 0
    for e in new_events:
        k = (e["event_date"], e.get("note", "")[:60])
        if k not in existing_keys:
            existing_keys.add(k)
            merged.append(e)
            added += 1

    print(f"Added to merged: {added}")
    merged.sort(key=lambda x: x.get("event_date", ""))

    # Write merged events
    fieldnames = [
        "event_date", "event_type", "scope", "severity", "expected_channel",
        "note", "source_url", "effective_from", "effective_to",
        "source", "publisher", "headline", "body_text", "query_used", "relevance_score",
    ]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(merged)

    print(f"\nWritten: {out} ({len(merged)} rows, +{added} new)")

    # Also update event_regime_panel if it exists
    panel_updated = False
    if EVENT_PANEL.exists():
        panel_rows = load_events(EVENT_PANEL)
        panel_keys = {(r["event_date"], r["event_type"]) for r in panel_rows}
        PANEL_FIELDS = ["event_date", "event_type", "scope", "severity",
                        "expected_channel", "note", "source"]
        panel_added = 0
        for e in merged:
            k = (e["event_date"], e["event_type"])
            if k not in panel_keys:
                panel_keys.add(k)
                panel_rows.append({f: e.get(f, "") for f in PANEL_FIELDS})
                panel_added += 1
        panel_rows.sort(key=lambda x: x.get("event_date", ""))
        with open(EVENT_PANEL, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=PANEL_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(panel_rows)
        print(f"event_regime_panel updated: {len(panel_rows)} rows (+{panel_added})")
        panel_updated = True

    # Statistics
    from collections import Counter
    type_dist = Counter(e["event_type"] for e in merged)
    print(f"\nEvent type distribution (top 15):")
    for et, cnt in type_dist.most_common(15):
        print(f"  {et}: {cnt}")

    cat_dist = Counter()
    for e in merged:
        h_text = e.get("headline", "") + " " + e.get("note", "")
        if e["event_type"] in ("gold_price_up", "gold_price_down", "gold_price_move"):
            cat_dist["gold_directed"] += 1
        elif e["event_type"] == "sbv_policy":
            cat_dist["sbv_policy"] += 1
        elif e["event_type"] == "fx_shock":
            cat_dist["fx_shock"] += 1
        elif e["event_type"] == "policy_rate_global":
            cat_dist["policy_global"] += 1
        elif e["event_type"] == "geopolitical":
            cat_dist["geopolitical"] += 1
        elif e["event_type"] == "macro_shock":
            cat_dist["macro"] += 1
        elif e["event_type"] == "seasonal_tet":
            cat_dist["seasonal"] += 1
        else:
            cat_dist["other"] += 1
    print("By semantic category:")
    for c, n in cat_dist.most_common():
        print(f"  {c}: {n}")

    monthly = Counter()
    for e in merged:
        d = e.get("event_date", "")
        if len(d) >= 7:
            monthly[d[:7]] += 1
    print(f"\nMonth coverage: {len(monthly)} months ({min(monthly)} -> {max(monthly)})")

    # Manifest
    manifest = {
        "generated_at": date.today().isoformat(),
        "news_events_output": str(out),
        "existing_events": len(existing),
        "new_events_added": added,
        "total_events": len(merged),
        "by_event_type": dict(type_dist),
        "by_semantic": dict(cat_dist),
        "month_coverage": len(monthly),
        "date_range": {"from": min(monthly), "to": max(monthly)},
        "event_panel_updated": panel_updated,
        "headlines_source": str(NEWS_RAW),
        "notes": "Integrated 3441 Google News RSS headlines as news-driven events.",
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nManifest: {MANIFEST}")
    print("\nDONE")


if __name__ == "__main__":
    raise SystemExit(main())
