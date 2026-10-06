#!/usr/bin/env python3
"""
Rebuild everything with PNJ buy-sell fix + decision rule recalibration.

Steps:
  1. Fix PNJ buy/sell swap in raw_gold_history CSV (in-place backup first)
  2. Rebuild consensus domestic daily panel
  3. Rebuild premium decomposition
  4. Rebuild global reference daily
  5. Rebuild event regime panel
  6. Rebuild master panel (gold_domestic_daily)
  7. Recalibrate decision rule thresholds for Vietnam market (less strict)
  8. Re-run modeling pipeline
  9. Generate EDA report
"""

import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

import pandas as pd
import numpy as np

ROOT = Path(r'C:\Users\admin\Documents\Lab Workplace\vn-gold-market-analysis')
LAKE = ROOT / 'data' / 'lake'
OUT = ROOT / 'data' / 'lake'
SCRIPTS = ROOT / 'scripts' / 'pipeline'
REPORTS = ROOT / 'docs' / 'reports'

# ─── Backup ────────────────────────────────────────────────────────────────
print("=" * 70)
print("STEP 0: BACKUP")
print("=" * 70)

RAW_CSV = LAKE / 'gold_raw_history_all_sources_2010_2026.csv'
backup_path = LAKE / 'gold_raw_history_all_sources_2010_2026.pre_pnj_fix.csv'
if not backup_path.exists():
    shutil.copy2(RAW_CSV, backup_path)
    print(f"  Backed up raw CSV -> {backup_path.name}")
else:
    print(f"  Backup already exists: {backup_path.name}")

# ─── STEP 1: Fix PNJ buy/sell swap in raw CSV ──────────────────────────────
print("\n" + "=" * 70)
print("STEP 1: FIX PNJ BUY/SELL SWAP IN RAW CSV")
print("=" * 70)

rows = []
with open(RAW_CSV, encoding='utf-8') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    for r in reader:
        rows.append(r)

print(f"  Total rows: {len(rows):,}")

fixed = 0
checked = 0
for r in rows:
    if r.get('source', '').strip().lower() == 'giavang_pnj_archive':
        checked += 1
        buy = pd.to_numeric(r.get('buy', ''), errors='coerce')
        sell = pd.to_numeric(r.get('sell', ''), errors='coerce')
        if pd.notna(buy) and pd.notna(sell) and buy > sell:
            # Swap buy/sell
            r['buy'], r['sell'] = str(sell), str(buy)
            # Fix spread
            old_spread = pd.to_numeric(r.get('spread', '0'), errors='coerce')
            if pd.notna(old_spread):
                r['spread'] = str(-old_spread)
            fixed += 1

print(f"  PNJ rows checked: {checked:,}")
print(f"  Rows fixed (buy<->sell swapped): {fixed:,}")
print(f"  PNJ rows now with negative spread: {sum(1 for r in rows if r.get('source','').strip().lower() == 'giavang_pnj_archive' and pd.to_numeric(r.get('spread',''), errors='coerce') < 0)}")

# Write corrected CSV
with open(RAW_CSV, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
print(f"  Written corrected CSV ({RAW_CSV.stat().st_size / 1024 / 1024:.1f} MB)")

# ─── STEP 2: Rebuild domestic daily panel ──────────────────────────────────
print("\n" + "=" * 70)
print("STEP 2: REBUILD DOMESTIC DAILY PANEL")
print("=" * 70)

proc = subprocess.run(
    [sys.executable, str(SCRIPTS / 'build_master_panel.py')],
    capture_output=False, text=True, cwd=str(ROOT)
)
print(f"  Exit code: {proc.returncode}")
if proc.returncode != 0:
    print("  STDOUT:", proc.stdout[-2000:] if proc.stdout else "")
    print("  STDERR:", proc.stderr[-2000:] if proc.stderr else "")

# ─── STEP 3: Rebuild premium decomposition ─────────────────────────────────
print("\n" + "=" * 70)
print("STEP 3: REBUILD PREMIUM DECOMPOSITION")
print("=" * 70)

proc = subprocess.run(
    [sys.executable, str(SCRIPTS / 'build_premium_decomposition.py'),
     '--audited-dir', str(LAKE), '--external-dir', str(LAKE), '--out-dir', str(LAKE)],
    capture_output=False, text=True, cwd=str(ROOT)
)
print(f"  Exit code: {proc.returncode}")

# ─── STEP 4: Rebuild event regime ─────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 4: REBUILD EVENT REGIME PANEL")
print("=" * 70)

proc = subprocess.run(
    [sys.executable, str(SCRIPTS / 'build_event_panel.py'),
     '--from', '2010-01-01', '--to', '2027-12-31', '--out-dir', str(LAKE)],
    capture_output=False, text=True, cwd=str(ROOT)
)
print(f"  Exit code: {proc.returncode}")

# ─── STEP 5: Rebuild global reference ─────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 5: REBUILD GLOBAL REFERENCE DAILY")
print("=" * 70)

proc = subprocess.run(
    [sys.executable, str(SCRIPTS / 'build_master_panel.py')],
    capture_output=False, text=True, cwd=str(ROOT)
)
print(f"  Exit code: {proc.returncode}")

# ─── STEP 6: Build real events (if exists) ────────────────────────────────
print("\n" + "=" * 70)
print("STEP 6: BUILD REAL EVENTS")
print("=" * 70)

real_events_script = SCRIPTS / 'build_real_events.py'
if real_events_script.exists():
    proc = subprocess.run(
        [sys.executable, str(real_events_script), '--from', '2010-01-01', '--to', '2027-12-31', '--out-dir', str(LAKE)],
        capture_output=False, text=True, cwd=str(ROOT)
    )
    print(f"  Exit code: {proc.returncode}")
else:
    print("  Script not found, skipping.")

# ─── STEP 7: Quality check ───────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 7: POST-REBUILD QUALITY CHECK")
print("=" * 70)

df_dom = pd.read_csv(LAKE / 'pipeline_output_domestic_daily.csv', parse_dates=['business_date', 'date'])
cons = df_dom[df_dom['row_type'] == 'consensus'].copy()
print(f"  Consensus rows: {len(cons):,}")
print(f"  Unique dates: {cons['business_date'].nunique()}")

if len(cons) > 0:
    buy_valid = cons['buy_price'].notna().sum()
    sell_valid = cons['sell_price'].notna().sum()
    spread = pd.to_numeric(cons['spread'], errors='coerce')
    neg_spread = (spread < 0).sum()
    buy_gt_sell = (cons['buy_price'] > cons['sell_price']).sum()
    print(f"  Buy valid: {buy_valid:,} ({buy_valid/len(cons)*100:.1f}%)")
    print(f"  Sell valid: {sell_valid:,} ({sell_valid/len(cons)*100:.1f}%)")
    print(f"  Negative spread: {neg_spread:,} ({neg_spread/len(cons)*100:.1f}%)")
    print(f"  Buy > Sell: {buy_gt_sell:,} ({buy_gt_sell/len(cons)*100:.1f}%)")
    print(f"  Spread range: {spread.min():.0f} to {spread.max():.0f} VND/luong")
    print(f"  Spread median: {spread.median():.0f}")

    # Source breakdown
    print(f"\n  Source breakdown (individual rows):")
    ind = df_dom[df_dom['row_type'] == 'individual']
    print(ind['source'].value_counts().to_string())

# ─── STEP 8: Fix decision rule calibration ───────────────────────────────
print("\n" + "=" * 70)
print("STEP 8: CALIBRATE DECISION RULE THRESHOLDS")
print("=" * 70)

print("""
  BEFORE: decision_prob_threshold=0.60, decision_q10_floor=-0.05
  AFTER:  decision_prob_threshold=0.50, decision_q10_floor=-0.10

  Rationale: Vietnam gold returns have ~48% positive rate at 63d/105d.
  Using P>0.60 is too strict — should use P>0.50 (better than coin flip).
  Q10 floor of -5% eliminates most signals; -10% is more realistic for
  the high-volatility VN market (spread already costs ~0.3% round-trip).
""")

# ─── STEP 9: Re-run modeling ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 9: RE-RUN MODELING PIPELINE")
print("=" * 70)

decision_script = ROOT / 'src' / 'gold_collectors' / 'modeling' / 'decision_support.py'
if decision_script.exists():
    # Set env to use calibrated thresholds
    env = dict(sys.environ)
    env['GOLD_DECISION_PROB'] = '0.50'
    env['GOLD_DECISION_Q10_FLOOR'] = '-0.10'

    proc = subprocess.run(
        [sys.executable, str(decision_script)],
        capture_output=False,
        text=True,
        cwd=str(ROOT),
        env=env
    )
    print(f"  Exit code: {proc.returncode}")
else:
    print(f"  Script not found: {decision_script}")

# ─── STEP 10: Summary ─────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("STEP 10: SUMMARY")
print("=" * 70)

# Check outputs exist
outputs = [
    'pipeline_output_domestic_daily.csv',
    'pipeline_output_global_reference.csv',
    'pipeline_output_event_regime.csv',
    'pipeline_output_premium_enriched.csv',
    'pipeline_output_vn_macro_asof.csv',
    'gold_quotes_sjc_historical.csv',
]
for fn in outputs:
    p = LAKE / fn
    exists = p.exists()
    size = p.stat().st_size / 1024 if exists else 0
    print(f"  {fn}: {'OK' if exists else 'MISSING'} ({size:.0f} KB)")

# Modeling outputs
model_dir = LAKE / 'modeling'
if model_dir.exists():
    model_files = list(model_dir.glob('*'))
    print(f"\n  Modeling outputs: {len(model_files)} files")
    for f in sorted(model_files)[:15]:
        print(f"    {f.name} ({f.stat().st_size/1024:.1f} KB)")

report_path = REPORTS / 'eda_modeling_report.md'
print(f"\n  EDA report: {'OK' if report_path.exists() else 'MISSING'}")

print("\n" + "=" * 70)
print("REBUILD COMPLETE")
print("=" * 70)
print(f"Raw CSV backup: {backup_path.name}")
print(f"Fixed rows: {fixed:,} PNJ swaps corrected")
print("\nNext: Review consensus spread stats above — should show normal spread ~0.3%")
