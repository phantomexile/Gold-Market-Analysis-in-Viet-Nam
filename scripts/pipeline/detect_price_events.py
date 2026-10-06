#!/usr/bin/env python3
"""Detect real gold price event days from data instead of hand-writing events.

Strategy:
1. Detect spike days from sell_consensus daily returns (>2sigma)
2. Detect premium shock days (premium vs its own rolling mean)
3. Detect spread blowout days
4. Tag each with approximate cause from available data:
   - If USD/VND moved >1% same day -> FX-driven
   - If LBMA moved >1% same day -> global-driven
   - If both -> mixed
   - Otherwise -> domestic
"""
import csv, sys, json
from datetime import date, timedelta
from statistics import mean, stdev
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

def load_csv(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))

rows = load_csv("data/lake/pipeline_output_premium_enriched.csv")
print(f"Loaded {len(rows)} rows from gold_daily_enriched")

# Index by date
by_date = {r["date"]: r for r in rows}
dates = sorted(by_date.keys())

# Daily returns
returns = []
for i in range(1, len(dates)):
    d_prev, d_curr = dates[i-1], dates[i]
    try:
        prev_p = float(by_date[d_prev]["sell_consensus"])
        curr_p = float(by_date[d_curr]["sell_consensus"])
        ret = (curr_p - prev_p) / prev_p * 100
        returns.append((d_curr, ret))
    except (ValueError, ZeroDivisionError):
        pass

rets = [r for _, r in returns]
mu, sigma = mean(rets), stdev(rets)
print(f"Return stats: mean={mu:+.3f}%, stdev={sigma:.3f}%")
print(f"Spike threshold: +{mu+2*sigma:.3f}% / {mu-2*sigma:.3f}%")

# Premium stats
premiums = []
for d in dates:
    try:
        p = float(by_date[d]["premium_pct"])
        if p != 0:
            premiums.append(p)
    except: pass
pmu, psig = mean(premiums), stdev(premiums)
print(f"Premium stats: mean={pmu:.2f}%, stdev={psig:.2f}%")

# Detect events
spike_events = []
premium_events = []
spread_events = []

# Spike days
for d, ret in returns:
    if ret > mu + 2*sigma:
        spike_events.append((d, ret, "spike_up"))
    elif ret < mu - 2*sigma:
        spike_events.append((d, ret, "spike_down"))

# Premium shock days (>3 sigma from premium mean)
for d in dates:
    try:
        p = float(by_date[d]["premium_pct"])
        if abs(p - pmu) > 3 * psig:
            premium_events.append((d, p, pmu))
    except: pass

# Spread blowout (>5x median spread_pct)
spreads = []
for d in dates:
    try:
        s = float(by_date[d]["spread_pct"])
        if s > 0:
            spreads.append(s)
    except: pass
med_spread = sorted(spreads)[len(spreads)//2]
for d in dates:
    try:
        s = float(by_date[d]["spread_pct"])
        if s > med_spread * 5:
            spread_events.append((d, s, med_spread))
    except: pass

print(f"\n=== DETECTED EVENTS (from data only) ===")
print(f"\nPrice spike days (>2sigma): {len(spike_events)}")
print(f"Premium shock days (>3sigma): {len(premium_events)}")
print(f"Spread blowout days (>5x median): {len(spread_events)}")

# Try to tag cause
def tag_cause(d, ret, premium_val, usd_val, lbma_val):
    causes = []
    # Check available data
    try:
        prev_d = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        if prev_d not in by_date: prev_d = d
        prev_usd = float(by_date[prev_d].get("usd_vnd") or 0)
        curr_usd = float(usd_val or 0)
        if prev_usd > 0 and abs(curr_usd - prev_usd) / prev_usd * 100 > 0.5:
            causes.append("USD/VND move")
    except: pass
    try:
        prev_d = (date.fromisoformat(d) - timedelta(days=1)).isoformat()
        if prev_d not in by_date: prev_d = d
        prev_lbma = float(by_date[prev_d].get("global_gold_usd_oz") or 0)
        curr_lbma = float(lbma_val or 0)
        if prev_lbma > 0 and abs(curr_lbma - prev_lbma) / prev_lbma * 100 > 0.5:
            causes.append("LBMA move")
    except: pass
    if not causes:
        causes.append("domestic/supply")
    return causes

# Build event records from price spikes
event_records = []
for d, ret, direction in spike_events:
    r = by_date.get(d, {})
    event_records.append({
        "event_date": d,
        "event_type": f"price_{direction}",
        "scope": "domestic_vietnam",
        "severity": "high" if abs(ret) > 4 else "medium",
        "expected_channel": "safe_haven_buy" if direction == "spike_up" else "panic_sell",
        "note": f"SJC sell return {ret:+.2f}%, premium={r.get('premium_pct','?')}%",
        "source_url": "",
        "effective_from": d,
        "effective_to": d,
        "day_return_pct": f"{ret:.2f}",
        "premium_pct": r.get("premium_pct", ""),
        "spread_pct": r.get("spread_pct", ""),
        "lbma_usd_oz": r.get("global_gold_usd_oz", ""),
        "usd_vnd": r.get("usd_vnd", ""),
        "source_count": r.get("source_count", ""),
    })

for d, prem, avg in premium_events:
    r = by_date.get(d, {})
    event_records.append({
        "event_date": d,
        "event_type": "premium_shock",
        "scope": "domestic_vietnam",
        "severity": "high" if abs(prem - avg) > 4*psig else "medium",
        "expected_channel": "premium_spike",
        "note": f"Premium {prem:+.1f}% vs avg {avg:.1f}% (delta={prem-avg:+.1f}%)",
        "source_url": "",
        "effective_from": d,
        "effective_to": d,
        "day_return_pct": "",
        "premium_pct": f"{prem:.2f}",
        "spread_pct": r.get("spread_pct", ""),
        "lbma_usd_oz": r.get("global_gold_usd_oz", ""),
        "usd_vnd": r.get("usd_vnd", ""),
        "source_count": r.get("source_count", ""),
    })

for d, s, med in spread_events:
    r = by_date.get(d, {})
    event_records.append({
        "event_date": d,
        "event_type": "spread_blowout",
        "scope": "domestic_vietnam",
        "severity": "medium",
        "expected_channel": "liquidity_squeeze",
        "note": f"Spread {s:.2f}% vs median {med:.2f}% ({s/med:.1f}x)",
        "source_url": "",
        "effective_from": d,
        "effective_to": d,
        "day_return_pct": "",
        "premium_pct": r.get("premium_pct", ""),
        "spread_pct": f"{s:.2f}",
        "lbma_usd_oz": r.get("global_gold_usd_oz", ""),
        "usd_vnd": r.get("usd_vnd", ""),
        "source_count": r.get("source_count", ""),
    })

# Deduplicate by date+type
seen = set()
unique = []
for e in event_records:
    key = (e["event_date"], e["event_type"])
    if key not in seen:
        seen.add(key)
        unique.append(e)

# Sort by date
unique.sort(key=lambda x: x["event_date"])

# Write
out = "data/lake/price_events.csv"
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(unique[0].keys()))
    w.writeheader()
    w.writerows(unique)

print(f"\nWrote {len(unique)} detected events to {out}")
print("\nEvent type breakdown:")
from collections import Counter
ct = Counter(e["event_type"] for e in unique)
for k, v in ct.most_common():
    print(f"  {k}: {v}")

print("\nYear distribution:")
yr = Counter(e["event_date"][:4] for e in unique)
for y in sorted(yr):
    print(f"  {y}: {yr[y]} events")

print(f"\nTop 10 spike_up days:")
up = [e for e in unique if e["event_type"] == "price_spike_up"]
for e in sorted(up, key=lambda x: float(x["day_return_pct"]), reverse=True)[:10]:
    print(f"  {e['event_date']}: +{e['day_return_pct']}% premium={e['premium_pct']}% lbma={e['lbma_usd_oz']} usd={e['usd_vnd']}")
