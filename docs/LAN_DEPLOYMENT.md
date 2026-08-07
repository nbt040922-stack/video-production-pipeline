# Triển khai trong mạng LAN

## Kiến trúc

Một máy Windows 11 giữ workspace, GPU, tiến trình engine, FFmpeg và API key. FastAPI phục vụ Vite production và `/api` trên cùng một cổng.

```text
Trình duyệt LAN -> http://HOST:8000
                  |-- /       Vite SPA
                  `-- /api    FastAPI + JobManager FIFO có lưu trạng thái
```

Không mở cổng này bằng port forwarding, public DNS, tunnel hoặc Internet công cộng.

## Cấu hình và chạy

Sao chép `.env.example` thành `.env`. Điền `PIPELINE_SESSION_SECRET` ngẫu nhiên. M08 không còn dùng `PIPELINE_ACCESS_PASSWORD`; mỗi người có tài khoản riêng trong SQLite. Tạo secret bằng:

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli generate-secret
```

Sau đó chạy `migrate-m08`, `create-admin` và tạo tài khoản theo [Quản lý người dùng](USER_ADMINISTRATION.md). Nếu dùng `CHAY_LAN.cmd`, các bước migrate và tạo admin được thực hiện tự động.

Production LAN từ chối khởi động nếu thiếu hai giá trị trên. Chỉ dùng `PIPELINE_ALLOW_INSECURE=true` trong môi trường development biệt lập.

```powershell
npm run build:production
.\scripts\run-production.ps1
```

Ép build lại frontend:

```powershell
.\scripts\run-production.ps1 -BuildFrontend
```

UI và API dùng chung origin; production gọi `/api` bằng URL tương đối. Source map mặc định tắt. Khi cần chẩn đoán:

```powershell
npm run build:production -- --sourcemap
```

Hiển thị địa chỉ truy cập:

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli lan-info
```

## Firewall và địa chỉ ổn định

Chạy thủ công trong PowerShell có quyền Administrator:

```powershell
.\scripts\allow-lan-firewall.ps1
```

Rule chính xác: `Video Production Pipeline LAN (TCP)`. Rule chỉ cho phép cổng TCP đã cấu hình từ `LocalSubnet` trên profile `Private`. Gỡ rule bằng:

```powershell
.\scripts\remove-lan-firewall.ps1
```

Script không tự đổi IP Windows. Nên đặt DHCP reservation trên router; nếu không thể, cấu hình IPv4 private tĩnh thủ công.

## Mẫu nghiệm thu thủ công

Chỉ thực hiện khi đã được phép đổi firewall và chạy một job thật ít tốn phí.

- Ngày/người kiểm tra:
- IPv4/cổng máy chủ:
- UI qua localhost đạt:
- UI từ máy LAN thứ hai đạt:
- Bắt buộc đăng nhập:
- Máy chưa đăng nhập bị chặn:
- Job ID đã được duyệt:
- Quan sát được queued/running/progress:
- Tải và phát được `final_video.mp4`:
- Khởi động lại trình duyệt vẫn thấy job:
- Khởi động lại backend vẫn thấy job hoàn tất:
- Firewall giới hạn `LocalSubnet`:
- Lỗi/việc cần làm tiếp:
