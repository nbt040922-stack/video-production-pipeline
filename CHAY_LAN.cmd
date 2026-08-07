@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

if /i "%~1"=="--check" goto :check

set "LAN_PORT=8000"
if not exist ".env" goto :port_ready
for /f "tokens=2 delims==" %%P in ('findstr /B /C:"PIPELINE_PORT=" ".env"') do set "LAN_PORT=%%P"
:port_ready

schtasks /Query /TN "Video Production Pipeline" >nul 2>&1
if errorlevel 1 goto :install
if not exist ".env" goto :install
if not exist ".venv\Scripts\python.exe" goto :install
goto :account_setup

:install
net session >nul 2>&1
if errorlevel 1 goto :elevate

echo [1/6] Kiểm tra môi trường...
if exist ".venv\Scripts\python.exe" goto :node
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "setup.ps1"
if errorlevel 1 goto :fail

:node
if exist "node_modules" goto :config
call npm install
if errorlevel 1 goto :fail

:config
echo [2/6] Cấu hình bảo mật phiên đăng nhập...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
    "$path = Join-Path (Get-Location) '.env';" ^
    "if (-not (Test-Path $path)) { Copy-Item '.env.example' $path };" ^
    "$lines = [IO.File]::ReadAllLines($path);" ^
    "$secretLine = $lines | Where-Object { $_.StartsWith('PIPELINE_SESSION_SECRET=') } | Select-Object -First 1;" ^
    "$secret = ([string]($secretLine -replace '^PIPELINE_SESSION_SECRET=', '')).Trim();" ^
    "if (-not $secret) { $secret = ((& '.\.venv\Scripts\python.exe' -m apps.orchestrator.cli generate-secret) | Out-String).Trim() };" ^
    "for ($i = 0; $i -lt $lines.Length; $i++) {" ^
    "  if ($lines[$i].StartsWith('PIPELINE_SESSION_SECRET=')) { $lines[$i] = 'PIPELINE_SESSION_SECRET=' + $secret }" ^
    "};" ^
    "[IO.File]::WriteAllLines($path, $lines, [Text.UTF8Encoding]::new($false))"
if errorlevel 1 goto :fail

echo [3/6] Build frontend...
if exist "dist\index.html" goto :firewall
call npm run build:production
if errorlevel 1 goto :fail

:firewall
echo [4/6] Mở firewall LAN riêng...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\allow-lan-firewall.ps1" -Port %LAN_PORT%
if errorlevel 1 goto :fail

echo [5/6] Cài tự chạy khi đăng nhập Windows...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\install-background-task.ps1" -Mode Logon
if errorlevel 1 goto :fail

:account_setup
echo Thiết lập dữ liệu người dùng...
call .venv\Scripts\python.exe -m apps.orchestrator.cli migrate-m08
if errorlevel 1 goto :fail
call .venv\Scripts\python.exe -m apps.orchestrator.cli create-admin
if errorlevel 1 goto :fail

:start
echo [6/6] Khởi động dịch vụ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "scripts\start-background-task.ps1"
if errorlevel 1 goto :fail
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$limit = (Get-Date).AddMinutes(3); do { try { $health = Invoke-RestMethod -Uri 'http://127.0.0.1:%LAN_PORT%/api/health' -TimeoutSec 2; if ($health.status -eq 'ok') { exit 0 } } catch {}; Start-Sleep -Seconds 2 } while ((Get-Date) -lt $limit); exit 1"
if errorlevel 1 goto :health_fail
echo.
.\.venv\Scripts\python.exe -m apps.orchestrator.cli lan-info
echo.
echo HOÀN TẤT. Windows tự chạy dịch vụ khi đăng nhập.
echo Mỗi người dùng đăng nhập bằng tài khoản riêng; job không bị lẫn nhau.
pause
exit /b 0

:health_fail
echo Backend chưa mở cổng %LAN_PORT%. Log cuối:
powershell.exe -NoProfile -Command "Get-Content 'logs\runtime.stderr.log','logs\watchdog.log' -Tail 15 -ErrorAction SilentlyContinue"
goto :fail

:elevate
echo Đang xin quyền Administrator cho lần cài đầu...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
exit /b

:check
if not exist "setup.ps1" exit /b 1
if not exist "scripts\allow-lan-firewall.ps1" exit /b 1
if not exist "scripts\install-background-task.ps1" exit /b 1
if not exist "scripts\start-background-task.ps1" exit /b 1
findstr /C:"/api/health" "%~f0" >nul || exit /b 1
echo CHAY_LAN.cmd: OK
exit /b 0

:fail
echo.
echo CÀI ĐẶT THẤT BẠI. Xem thông báo lỗi phía trên.
pause
exit /b 1
