@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "C:\Users\Admin\Desktop\vn-gold-market-analysis"

echo ===== STEP 1: Premium Decomposition =====
python scripts/pipeline/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices
echo STEP 1 DONE: %ERRORLEVEL%
echo.

echo ===== STEP 2: Event Panel =====
python scripts/pipeline/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices
echo STEP 2 DONE: %ERRORLEVEL%
echo.

echo ===== STEP 3: Enhanced Features =====
python scripts/pipeline/collect_enhanced_features.py --from 2010-01-01 --out-dir data/lake/market_data/v2
echo STEP 3 DONE: %ERRORLEVEL%
echo.

echo ===== ALL PIPELINE STEPS COMPLETE =====
pause
