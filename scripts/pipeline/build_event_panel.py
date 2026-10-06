#!/usr/bin/env python3
"""
Vietnam Gold Event Panel Builder.

Creates a structured event table for Vietnamese gold market regimes:
- NHNN gold auctions
- Policy changes (import limits, distribution rules)
- Tết / Thần Tài / lunar calendar events
- Wedding season windows (Apr-May, Aug-Oct)
- Geopolitical / global crisis events affecting Vietnam gold

These are rule-generated from known calendars + historical research.
Outputs to data/lake/
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from datetime import date, datetime

try:
    from ._bootstrap import bootstrap
except ImportError:
    from _bootstrap import bootstrap

bootstrap()

from gold_collectors.full_pipeline import DataLakeWriter

SO_LUNAR_2026 = {
    (1, 1): ("2026-01-29", "Tết Nguyên Đán"),
    (1, 2): ("2026-01-30", "Mùng 2"),
    (1, 3): ("2026-01-31", "Mùng 3"),
    (1, 4): ("2026-02-01", "Mùng 4"),
    (1, 5): ("2026-02-02", "Mùng 5"),
}

# R approximates to lunar new year Proximity weight
TET_PROXIMITY_DAYS = [
    (2024, 2, 8), # START: near Tết 2024
    (2024, 2, 16), # END
    (2025, 1, 28),
    (2025, 2, 4),
    (2026, 1, 19),
    (2026, 1, 29),
]

THAN_TAI_DAY = {
    2024: "2024-02-10", # 10th day of lunar new year
    2025: "2025-01-29",
    2026: "2026-02-17", # will update after conversion
}


@dataclass
class EventRecord:
    event_date: str # ISO date
    event_type: str # tet_proximity|than_tai|wedding_season|policy_auction|policy_import|geopolitical_crisis|financial_crisis|policy_rate_change
    scope: str # domestic_vietnam | global | regional
    severity: str # high | medium | low
    expected_channel: str # premium_spike | safe_haven_buy | liquidity_squeeze | rate_sensitivity
    note: str = ""
    source_url: str = ""
    effective_from: str = "" # for policy events
    effective_to: str = ""


def parse_args():
    parser = argparse.ArgumentParser(description="Build Vietnam gold event panel.")
    parser.add_argument("--from", dest="from_date", default="2010-01-01")
    parser.add_argument("--to", dest="to_date", default="2027-12-31")
    parser.add_argument("--out-dir", default="data/lake")
    return parser.parse_args()


def build_tet_windows(from_date: str, to_date: str) -> list[EventRecord]:
    """
    Build Tết proximity events. Vietnamese typically buy gold heavily
    in the 2 weeks before Lunar New Year.
    """
    records: list[EventRecord] = []
    tet_dates = {
        2011: "2011-02-03", 2012: "2012-01-23", 2013: "2013-02-10",
        2014: "2014-01-31", 2015: "2015-02-19", 2016: "2016-02-08",
        2017: "2017-01-28", 2018: "2018-02-16", 2019: "2019-02-05",
        2020: "2020-01-25", 2021: "2021-02-12", 2022: "2022-02-01",
        2023: "2023-01-22", 2024: "2024-02-10", 2025: "2025-01-29",
        2026: "2026-02-17",
    }

    for year, tet_iso in tet_dates.items():
        tet_dt = date.fromisoformat(tet_iso)
        # Two-week window before Tết
        for delta in range(-14, 1):
            d = tet_dt + __import__("datetime").timedelta(days=delta)
            if d.isoformat() < from_date or d.isoformat() > to_date:
                continue
            intensity = "high" if delta >= -5 else ("medium" if delta >= -9 else "low")
            records.append(EventRecord(
                event_date=d.isoformat(),
                event_type="tet_proximity",
                scope="domestic_vietnam",
                severity=intensity,
                expected_channel="premium_spike",
                note=f"Tết proximity (Tết {year}: {tet_iso})",
            ))

    # Thần Tài day (5th day of Tết - huge gold buying)
    than_tai_dates = {
        2011: "2011-02-07", 2012: "2012-01-27", 2013: "2013-02-14",
        2014: "2014-02-03", 2015: "2015-02-23", 2016: "2016-02-12",
        2017: "2017-02-01", 2018: "2018-02-20", 2019: "2019-02-09",
        2020: "2020-01-29", 2021: "2021-02-16", 2022: "2022-02-05",
        2023: "2023-01-26", 2024: "2024-02-14", 2025: "2025-02-02",
        2026: "2026-02-21",
    }

    for year, tt_iso in than_tai_dates.items():
        if tt_iso < from_date or tt_iso > to_date:
            continue
        records.append(EventRecord(
            event_date=tt_iso,
            event_type="than_tai",
            scope="domestic_vietnam",
            severity="high",
            expected_channel="premium_spike",
            note=f"Thần Tài day (ngày vía Thần Tài) - peak gold shopping {year}",
        ))

    return records


def build_wedding_season(from_date: str, to_date: str) -> list[EventRecord]:
    """
    Wedding season windows in Vietnam. Gold jewelry demand spikes during
    peak wedding months. Two windows per year:
    - Spring: Apr 15 - May 31 (peak gold buying season)
    - Late autumn: Aug 15 - Oct 5 (lunar Aug-Oct peak)
    """
    records: list[EventRecord] = []
    for year in range(2010, 2028):
        # Spring window: Apr 15 - May 31
        # April: moderate intensity (medium), May: peak (high)
        for month, day_end, severity, label in [
            (4, 30, "medium", "Apr"),
            (5, 31, "high", "May"),
        ]:
            start_day = 1 if month != 4 else 15
            for day in range(start_day, day_end + 1):
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                d_str = d.isoformat()
                if d_str < from_date or d_str > to_date:
                    continue
                records.append(EventRecord(
                    event_date=d_str,
                    event_type="wedding_season",
                    scope="domestic_vietnam",
                    severity=severity,
                    expected_channel="premium_spike",
                    note=f"Wedding season spring window {year} ({label})",
                ))

        # Autumn window: Aug 15 - Oct 5 (lunar Aug-Oct peak)
        for month, day_end in [(8, 31), (9, 30)]:
            for day in range(15, day_end + 1):
                try:
                    d = date(year, month, day)
                except ValueError:
                    continue
                d_str = d.isoformat()
                if d_str < from_date or d_str > to_date:
                    continue
                records.append(EventRecord(
                    event_date=d_str,
                    event_type="wedding_season",
                    scope="domestic_vietnam",
                    severity="high",
                    expected_channel="premium_spike",
                    note=f"Wedding season autumn window {year} ({d.strftime('%b')})",
                ))
        # Oct 1-5
        for day in range(1, 6):
            try:
                d = date(year, 10, day)
            except ValueError:
                continue
            d_str = d.isoformat()
            if d_str < from_date or d_str > to_date:
                continue
            records.append(EventRecord(
                event_date=d_str,
                event_type="wedding_season",
                scope="domestic_vietnam",
                severity="high",
                expected_channel="premium_spike",
                note=f"Wedding season autumn window {year} (Oct early)",
            ))
    return records


def build_historical_policy_events(from_date: str, to_date: str) -> list[EventRecord]:
    """
    Key Vietnam gold policy events identified from deep research.
    These are manually tagged based on the research report citations.
    """
    records: list[EventRecord] = []

    # Known events from research (NHNN auction restart 2024, policy tightening)
    # Expanded with historical VN gold market events from deep-research-report
    policy_events = [
    # 2024-2026: Recent auction & import policy
    ("2024-03-15", "2024-03-25", "policy_auction", "domestic_vietnam", "high",
    "NHNN restarts gold auctions after 10+ year hiatus to narrow domestic premium",
    "https://www.sbv.gov.vn/"),
    ("2024-04-03", "2024-12-31", "policy_import", "domestic_vietnam", "medium",
    "Industry calls for eased import restrictions to increase gold liquidity",
    "https://www.sbv.gov.vn/"),
    ("2024-07-18", "2024-12-31", "policy_import", "domestic_vietnam", "medium",
    "SBV imported additional gold to boost domestic supply",
    "https://www.sbv.gov.vn/"),
    ("2024-11-18", "2025-06-30", "policy_import", "domestic_vietnam", "medium",
    "SBV 2nd gold import batch announced - 20 tonnes",
    "https://www.sbv.gov.vn/"),
    # 2025: SBV policy rate hike
    ("2025-01-03", "2025-12-31", "policy_rate_increase", "domestic_vietnam", "high",
    "SBV raised refinance rate 4.5% -> 5.0% - first hike in years",
    "https://www.sbv.gov.vn/"),
    # 2023: Market inspection
    ("2023-06-15", "2023-12-31", "policy_inspection", "domestic_vietnam", "medium",
    "Market inspection operations tighten supply chains",
    ""),
    # 2019: Market inspection crackdown
    ("2019-01-15", "2019-12-31", "policy_inspection", "domestic_vietnam", "medium",
    "SBV strengthened gold market inspection - reduced smuggling channels",
    "https://www.sbv.gov.vn/"),
    # 2018: Gold trading floor closures
    ("2018-04-01", "2018-09-30", "policy_inspection", "domestic_vietnam", "high",
    "SBV closed major gold trading floors in HCMC/Hanoi - centralized to SJC",
    "https://www.sbv.gov.vn/"),
    # 2018: Gold import quota tightening
    ("2018-07-01", "2018-12-31", "policy_import", "domestic_vietnam", "medium",
    "Vietnam tightened gold import quotas - domestic premium widened",
    ""),
    # 2022: Russia-Ukraine war impact
    ("2022-03-08", "2022-06-30", "geopolitical_crisis", "global", "high",
    "Russia-Ukraine war breakout - safe haven gold surge",
    ""),
    # 2022: import quota liberalization
    ("2022-11-01", "2023-03-31", "policy_import", "domestic_vietnam", "medium",
    "Vietnam gold import quota liberalization discussions - premium elevated",
    ""),
    # 2020: COVID-19
    ("2020-03-16", "2020-06-30", "financial_crisis", "global", "high",
    "COVID-19 global market crash - unprecedented volatility",
    ""),
    # 2020: Fed rate cut to zero
    ("2020-03-15", "2020-12-31", "policy_rate_decrease", "global", "high",
    "Fed cut rates to near zero globally, gold rally to all-time high",
    ""),
    # 2015: Dong devaluation
    ("2015-01-05", "2015-06-30", "geopolitical_crisis", "domestic_vietnam", "high",
    "ND devaluation ~2% against USD - major VND shock, domestic gold surged",
    ""),
    # 2011: Vietnam import restrictions
    ("2011-02-10", "2011-12-31", "policy_import", "domestic_vietnam", "high",
    "Vietnam gold import restrictions tightened - domestic premium spiked",
    ""),
    # 2011: Eurozone crisis global impact
    ("2011-07-06", "2012-06-30", "financial_crisis", "global", "high",
    "Eurozone debt crisis, gold all-time high in USD, safe haven demand peak",
    ""),
    # 2012: Gold smuggling crackdown
    ("2012-04-01", "2012-12-31", "policy_inspection", "domestic_vietnam", "medium",
    "Vietnam cracked down on gold smuggling along Cambodia border",
    ""),
    # 2016: SBV rate tightening
    ("2016-11-01", "2017-03-31", "policy_rate_increase", "domestic_vietnam", "low",
    "SBV interest rate tightening cycle begins",
    "https://www.sbv.gov.vn/"),
    ]

    for event_date, effective_to, event_type, scope, severity, note, url in policy_events:
        if event_date > to_date or effective_to < from_date:
            continue
        records.append(EventRecord(
            event_date=event_date,
            event_type=event_type,
            scope=scope,
            severity=severity,
            expected_channel="premium_spike" if "premium" in event_type or "auction" in event_type else "safe_haven_buy",
            note=note,
            source_url=url,
            effective_from=event_date,
            effective_to=effective_to,
        ))

    return records


def build_global_crisis_windows(from_date: str, to_date: str) -> list[EventRecord]:
    """
    Global crisis periods known to drive gold prices.
    """
    records: list[EventRecord] = []

    crises = [
        ("2008-09-15", "2009-06-30", "financial_crisis", "high", "Global Financial Crisis"),
        ("2011-01-01", "2011-12-31", "eurozone_crisis", "high", "Eurozone sovereign debt crisis"),
        ("2016-06-24", "2016-12-31", "geopolitical_crisis", "medium", "Brexit vote"),
        ("2020-02-20", "2020-04-30", "financial_crisis", "high", "COVID-19 market crash"),
        ("2022-02-24", "2022-09-30", "geopolitical_crisis", "high", "Russia-Ukraine war"),
        ("2022-06-01", "2023-01-31", "financial_stress", "medium", "Global tightening cycle"),
        ("2023-03-01", "2023-06-30", "banking_stress", "medium", "SVB / regional banking crisis"),
        ("2024-10-01", "2025-01-31", "geopolitical_crisis", "medium", "Middle East tensions"),
    ]

    for start, end, event_type, severity, note in crises:
        if end < from_date or start > to_date:
            continue
        # Create one record per month within the crisis window
        s = date.fromisoformat(start)
        e = date.fromisoformat(end)
        cur = s
        while cur <= e:
            if cur.isoformat() >= from_date and cur.isoformat() <= to_date:
                records.append(EventRecord(
                    event_date=cur.isoformat(),
                    event_type=event_type,
                    scope="global",
                    severity=severity,
                    expected_channel="safe_haven_buy",
                    note=note,
                ))
            # Monthly step
            month = cur.month - 1 + 1
            year = cur.year + month // 12
            month = month % 12 + 1
            cur = cur.replace(year=year, month=month)

    return records


def build_weekday_calendar(from_date: str, to_date: str) -> list[EventRecord]:
    """
    Rule-based calendar features (no leakage - all known in advance).
    """
    records: list[EventRecord] = []
    for d_str in date_range(from_date, to_date):
        d = date.fromisoformat(d_str)
        # weekday
        wd = d.weekday() # 0=Mon
        records.append(EventRecord(
            event_date=d_str,
            event_type="calendar_weekday",
            scope="domestic_vietnam",
            severity="low",
            expected_channel="volume_pattern",
            note=f"weekday_{d.strftime('%A')}",
        ))
        # month
        records.append(EventRecord(
            event_date=d_str,
            event_type="calendar_month",
            scope="domestic_vietnam",
            severity="low",
            expected_channel="seasonal_pattern",
            note=f"month_{d.month}",
        ))
    return records


def date_range(start: str, end: str) -> list[str]:
    """Simple date range generator."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    out = []
    cur = s
    while cur <= e:
        out.append(cur.isoformat())
        cur += __import__("datetime").timedelta(days=1)
    return out


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    writer = DataLakeWriter(out_dir, formats=["csv"], flat=True)

    events: list[dict] = []

    print("Building Tết windows...")
    events.extend(asdict(e) for e in build_tet_windows(args.from_date, args.to_date))
    print(f" Tết events: {len(events)} (running total)")

    print("Building wedding season events...")
    events.extend(asdict(e) for e in build_wedding_season(args.from_date, args.to_date))
    print(f" + wedding season events (running total)")

    print("Building historical policy events...")
    events.extend(asdict(e) for e in build_historical_policy_events(args.from_date, args.to_date))

    print("Building global crisis windows...")
    events.extend(asdict(e) for e in build_global_crisis_windows(args.from_date, args.to_date))

    # Deduplicate by (date, type)
    seen = set()
    unique = []
    for e in events:
        key = (e["event_date"], e["event_type"], e.get("note", "")[:50])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    writer.write_dataset("gold_event_panel", unique)

    manifest = {
        "generated_at": date.today().isoformat(),
        "from": args.from_date,
        "to": args.to_date,
        "records": len(unique),
        "event_types": sorted({e["event_type"] for e in unique}),
        "severity_breakdown": {
            sev: sum(1 for e in unique if e["severity"] == sev)
            for sev in ["high", "medium", "low"]
        },
    }
    (out_dir / "manifests" / "event_panel_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nTotal unique events: {len(unique)}")
    print(f"By type: {manifest['event_types']}")
    print(f"Output: {out_dir}/gold_event_panel.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
