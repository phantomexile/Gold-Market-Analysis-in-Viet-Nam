@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
rem Dùng thư mục chứa launcher để lệnh vẫn đúng khi di chuyển hoặc đổi tên dự án.
cd /d "%~dp0"

echo ===== STEP 1: Premium Decomposition =====
python scripts/processing/build_premium_decomposition.py --audited-dir data/lake/domestic_target --external-dir data/lake/market_data/v1 --out-dir data/lake/gold_prices
echo STEP 1 DONE: %ERRORLEVEL%
echo.

echo ===== STEP 2: Event Panel =====
python scripts/processing/build_event_panel.py --from 2010-01-01 --to 2027-12-31 --out-dir data/lake/gold_prices
echo STEP 2 DONE: %ERRORLEVEL%
echo.

echo ===== STEP 3: Enhanced Features =====
python scripts/collection/collect_enhanced_features.py --from 2010-01-01 --out-dir data/lake/market_data/v2
echo STEP 3 DONE: %ERRORLEVEL%
echo.

echo ===== ALL PIPELINE STEPS COMPLETE =====
pause
