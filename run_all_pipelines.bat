@echo off
setlocal
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem Dùng thư mục chứa launcher để lệnh vẫn đúng khi di chuyển hoặc đổi tên dự án.
cd /d "%~dp0"
if errorlevel 1 goto workspace_error

rem Ưu tiên môi trường riêng của dự án để dùng đúng các thư viện đã cài đặt.
rem Nếu không có môi trường riêng, dùng Python hiện có trong PATH.
set "PIPELINE_PYTHON=python"
if exist "venv\Scripts\python.exe" set "PIPELINE_PYTHON=%CD%\venv\Scripts\python.exe"
if exist ".venv\Scripts\python.exe" set "PIPELINE_PYTHON=%CD%\.venv\Scripts\python.exe"
"%PIPELINE_PYTHON%" --version
if errorlevel 1 goto python_error

rem Bộ điều phối chính thu thập giá SJC, thị trường, tin tức và GPR;
rem sau đó xử lý premium, tạo dự báo 1/3/5 tháng và xuất dữ liệu dashboard.
rem Script Python chịu trách nhiệm kiểm tra kỳ hạn và ngày các đầu ra.
rem Không gọi riêng các builder cũ vì chúng ghi vào các nhánh dữ liệu khác.
rem Truyền nguyên tham số: --to YYYY-MM-DD hoặc --skip-collect khi lake đã mới.
echo ===== ĐANG CHẠY LUỒNG CẬP NHẬT DỮ LIỆU VÀ DỰ BÁO =====
"%PIPELINE_PYTHON%" "scripts\pipeline\refresh_latest_forecast.py" %*
rem Giữ mã lỗi ngay sau lệnh Python; các lệnh in thông báo có thể thay đổi nó.
set "PIPELINE_EXIT_CODE=%ERRORLEVEL%"
if not "%PIPELINE_EXIT_CODE%"=="0" goto pipeline_error
echo.
echo ===== LUỒNG CẬP NHẬT ĐÃ HOÀN TẤT =====
echo Hãy kiểm tra ngày dữ liệu của từng nguồn; nguồn cũ vẫn có thể được giữ lại.
goto finish

:workspace_error
set "PIPELINE_EXIT_CODE=1"
echo [LỖI] Không thể mở thư mục dự án chứa file BAT.
goto finish

:python_error
set "PIPELINE_EXIT_CODE=1"
echo [LỖI] Không chạy được Python. Hãy kiểm tra Python và môi trường của dự án.
goto finish

:pipeline_error
echo [LỖI] Luồng cập nhật thất bại với mã lỗi %PIPELINE_EXIT_CODE%.
echo Xem thông báo phía trên để xác định bước bị lỗi.

:finish
rem Giữ cửa sổ khi nhấp đúp. Đặt PIPELINE_NO_PAUSE=1 khi chạy tự động.
if not "%PIPELINE_NO_PAUSE%"=="1" pause
rem Trả đúng mã lỗi cho tác vụ tự động; chỉ trả 0 khi Python chạy thành công.
endlocal & exit /b %PIPELINE_EXIT_CODE%
