# Chạy nền trên Windows

M07 dùng Windows Task Scheduler, không dùng `sc.exe` giả Windows Service.

## Chế độ chẩn đoán có cửa sổ

```powershell
.\scripts\run-production.ps1
```

Script đọc `.env`, kiểm tra virtual environment và frontend build, khởi động Hook ComfyUI nếu cần, sau đó chạy FastAPI. Review và FFmpeg chỉ được tạo khi có job và do backend worker quản lý.

## Chế độ chạy nền tự động

Cài task idempotent khi đăng nhập:

```powershell
.\scripts\install-background-task.ps1 -Mode Logon
```

Có thể dùng `-Mode Startup`; chế độ này có thể cần quyền Administrator.

```powershell
.\scripts\start-background-task.ps1
.\scripts\status-background-task.ps1
.\scripts\stop-background-task.ps1
.\scripts\uninstall-background-task.ps1
```

Tên task: `Video Production Pipeline`. Watchdog ẩn khởi động lại runtime nếu tiến trình thoát bất thường. Task từ chối instance trùng. Watchdog và server dùng PID/lock độc quyền trong thư mục log. Stop script kiểm tra đúng command line trước khi dừng, không quét hoặc giết Python không liên quan.

Log xoay vòng:

- `logs/server.log`
- `logs/access.log`
- `logs/worker.log`

Log chẩn đoán: `server-console.log`, `watchdog.log`, `comfyui.stdout.log`, `comfyui.stderr.log`.

Job queued được nạp lại sau restart. Job đang chạy bị gián đoạn chuyển thành failed và cần Retry thủ công. Nếu Task Scheduler không còn đủ nhu cầu, có thể đánh giá WinSW như Windows Service thật trong milestone sau.
