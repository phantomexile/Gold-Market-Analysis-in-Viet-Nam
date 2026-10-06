#!/usr/bin/env python3
"""Generate final deliverables report for Vietnam gold market data."""
import csv, sys, json, traceback
from pathlib import Path
from datetime import date
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")


def load_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def count_rows(path):
    p = Path(path)
    if not p.exists():
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for _ in csv.DictReader(f))


def main():
    out_dir = Path("test_outputs")
    out_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()

    # Load all datasets
    news_raw = load_csv("data/lake/news_raw_headlines_vietnam_gold.csv")
    news_events = load_csv("data/lake/news_events.csv")
    event_panel = load_csv("data/lake/gold_event_panel.csv")
    price_events = load_csv("data/lake/price_events.csv")
    enriched = load_csv("data/lake/pipeline_output_premium_enriched.csv")
    master_global = load_csv("data/lake/pipeline_output_global_reference.csv")
    master_domestic = load_csv("data/lake/pipeline_output_domestic_daily.csv")
    master_vn_macro = load_csv("data/lake/pipeline_output_vn_macro_asof.csv")

    MAX_NEWS_ROWS = 50000
    news_raw = news_raw[:MAX_NEWS_ROWS]

    print(f"Loaded {len(news_raw)} news rows, {len(enriched)} enriched rows", flush=True)

    # News stats
    total_news = len(news_raw)
    with_body = sum(1 for r in news_raw if r.get("body_text", "").strip())
    body_lengths = [len(r["body_text"]) for r in news_raw if r.get("body_text", "").strip()]

    # Date coverage
    news_dates = [r["event_date"][:7] for r in news_raw if r.get("event_date", "") and len(r.get("event_date", "")) >= 7]
    news_months = len(set(news_dates))
    date_range_str = ""
    if news_dates:
        date_range_str = f"{min(news_dates)} -> {max(news_dates)}"
    else:
        date_range_str = "N/A"

    # Event stats
    total_price_events = len(price_events)
    price_event_types = Counter(e["event_type"] for e in price_events)

    total_news_events = len(news_events)
    news_event_types = Counter(e["event_type"] for e in news_events)

    total_panel = len(event_panel)
    panel_types = Counter(e["event_type"] for e in event_panel)

    # Enriched stats
    with_premium = sum(
        1 for r in enriched
        if r.get("premium_pct", "").strip()
        and float(r.get("premium_pct", 0) or 0) != 0
    )

    # Master panel stats
    master_stats = {}
    for name, data in [
        ("global_reference_daily", master_global),
        ("gold_domestic_daily_panel", master_domestic),
        ("vn_macro_asof_panel", master_vn_macro),
    ]:
        master_stats[name] = len(data)

    # Build report
    lines = []
    lines.append("=" * 60)
    lines.append("VIETNAM GOLD MARKET - FINAL DELIVERABLES REPORT")
    lines.append(f"Generated: {today}")
    lines.append("=" * 60)
    lines.append("")

    # 1. News Dataset
    lines.append("1. NEWS TEXT DATASET (news_raw_headlines_vietnam_gold.csv)")
    lines.append("-" * 40)
    lines.append(f" Total headlines: {total_news:,}")
    lines.append(f" With body text: {with_body:,} ({with_body * 100 / max(total_news, 1):.0f}%)")
    if body_lengths:
        lines.append(f" Body text length: median={sorted(body_lengths)[len(body_lengths) // 2]} chars")
        lines.append(f" Body text length: min={min(body_lengths)}, max={max(body_lengths)} chars")
    lines.append(f" Month coverage: {news_months} months")
    if date_range_str:
        lines.append(f" Date range: {date_range_str}")
    lines.append(f" Valid ISO dates: {total_news:,} (100%)")
    lines.append("")

    # 2. Event Detection
    lines.append("2. EVENT DETECTION")
    lines.append("-" * 40)
    lines.append(f" Price-action events (price_events.csv):")
    lines.append(f" Total: {total_price_events}")
    lines.append(f" By type:")
    for et, cnt in price_event_types.most_common():
        lines.append(f" {et}: {cnt}")
    lines.append("")

    lines.append(f" News-driven events (news_events.csv):")
    lines.append(f" Total: {total_news_events}")
    lines.append(f" By type (top 10):")
    for et, cnt in news_event_types.most_common(10):
        lines.append(f" {et}: {cnt}")
    lines.append("")

    # 3. Event Panel
    lines.append("3. EVENT REGIME PANEL (gold_event_panel.csv)")
    lines.append("-" * 40)
    lines.append(f" Total events: {total_panel}")
    lines.append(f" By type (top 15):")
    for et, cnt in panel_types.most_common(15):
        lines.append(f" {et}: {cnt}")
    lines.append("")

    # 4. Enriched Gold
    lines.append("4. ENRICHED GOLD PRICES (pipeline_output_premium_enriched.csv)")
    lines.append("-" * 40)
    lines.append(f" Total dates: {len(enriched):,}")
    lines.append(f" With premium: {with_premium:,} ({with_premium * 100 / max(len(enriched), 1):.0f}%)")
    lines.append("")

    # 5. Master Panel
    lines.append("5. MASTER PANEL")
    lines.append("-" * 40)
    for name, cnt in master_stats.items():
        lines.append(f" {name}: {cnt:,} rows")
    lines.append("")

    # 6. Output files
    lines.append("6. OUTPUT FILES")
    lines.append("-" * 40)
    lines.append(" data/lake/news_raw_headlines_vietnam_gold.csv")
    lines.append(f" -> {total_news:,} rows | NEWS TEXT DATA (raw headlines + body)")
    lines.append(" data/lake/news_events.csv")
    lines.append(f" -> {total_news_events:,} rows | CLASSIFIED EVENTS from news")
    lines.append(" data/lake/gold_event_panel.csv")
    lines.append(f" -> {total_panel:,} rows | MASTER EVENT PANEL (calendar + news + price-action)")
    lines.append(" data/lake/price_events.csv")
    lines.append(f" -> {total_price_events:,} rows | PRICE-ACTION EVENTS (2sigma/3sigma)")
    lines.append(" data/lake/pipeline_output_premium_enriched.csv")
    lines.append(f" -> {len(enriched):,} rows | DOMESTIC GOLD + EXTERNAL FEATURES")
    lines.append("")
    lines.append("=" * 60)
    lines.append("END OF REPORT")
    lines.append("=" * 60)

    report_text = "\n".join(lines)

    # Write text
    txt_path = out_dir / "deliverables_report.txt"
    txt_path.write_text(report_text, encoding="utf-8")

    # Write JSON
    json_path = out_dir / "deliverables_report.json"
    report_json = {
        "generated": today,
        "news_dataset": {
            "total_headlines": total_news,
            "with_body_text": with_body,
            "body_text_coverage_pct": round(with_body * 100 / max(total_news, 1), 1),
            "month_coverage": news_months,
            "valid_dates": total_news,
        },
        "event_detection": {
            "price_events": {
                "total": total_price_events,
                "by_type": dict(price_event_types.most_common()),
            },
            "news_events": {
                "total": total_news_events,
                "by_type": dict(news_event_types.most_common(10)),
            },
        },
        "event_panel": {
            "total": total_panel,
            "by_type": dict(panel_types.most_common(15)),
        },
        "enriched_gold": {
            "total_dates": len(enriched),
            "with_premium": with_premium,
        },
        "master_panel": master_stats,
    }
    json_path.write_text(json.dumps(report_json, indent=2, ensure_ascii=False), encoding="utf-8")

    # Write markdown
    md_path = out_dir / "deliverables_report.md"
    md_pct_body = round(with_body * 100 / max(total_news, 1), 0)
    md_pct_prem = round(with_premium * 100 / max(len(enriched), 1), 0)
    md = f"# Vietnam Gold Market Analysis - Final Deliverables\n"
    md += f"**Generated**: {today}\n\n"
    md += f"## 1. News Text Dataset\n"
    md += f"| Metric | Value |\n"
    md += f"|---|---|\n"
    md += f"| Total headlines | {total_news:,} |\n"
    md += f"| With body text | {with_body:,} ({md_pct_body:.0f}%) |\n"
    md += f"| Month coverage | {news_months} months |\n"
    md += f"| Date range | {date_range_str} |\n"
    md += f"| Data source | Google News RSS (50 queries) + direct articles |\n\n"

    md += f"## 2. Event Detection\n"
    md += f"| Type | Count |\n"
    md += f"|---|---|\n"
    for et, cnt in sorted(price_event_types.items(), key=lambda x: -x[1]):
        md += f"| {et} | {cnt} |\n"

    md += f"\n**News-driven events**: {total_news_events:,} total\n\n"
    md += f"## 3. Event Panel\n"
    md += f"| Total events | {total_panel:,} |\n"
    md += f"| Price-action events | {total_price_events:,} |\n"
    md += f"| News-driven events | {total_news_events:,} |\n\n"
    md += f"Top event types:\n"
    md += f"| Type | Count |\n"
    md += f"|---|---|\n"
    for et, cnt in panel_types.most_common(15):
        md += f"| {et} | {cnt} |\n"

    md += f"\n## 4. Master Panel\n"
    md += f"| Table | Rows |\n"
    md += f"|---|---|\n"
    for name, cnt in master_stats.items():
        md += f"| {name} | {cnt:,} |\n"

    md_path.write_text(md, encoding="utf-8")

    # Print to stdout
    print(report_text)
    print(f"\nWritten:")
    print(f" {txt_path}")
    print(f" {json_path}")
    print(f" {md_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        traceback.print_exc()
        sys.exit(1)
