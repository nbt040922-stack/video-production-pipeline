# Vận hành

## Tài khoản M08

Trước lần khởi động M08 đầu tiên, chạy `migrate-m08` rồi `create-admin`. Quản lý tài khoản bằng nhóm lệnh `users`; không sửa trực tiếp SQLite khi backend đang chạy. Khóa hoặc reset mật khẩu có hiệu lực với phiên cũ ở request kế tiếp. Theo dõi sự kiện bảo mật tại `logs/audit.log`.

## Health và readiness

`GET /api/health` chỉ cho biết tiến trình còn sống. `GET /api/readiness` kiểm tra frontend build, quyền ghi workspace, engine, FFmpeg/ffprobe, queue, dung lượng đĩa và xác thực. Kiểm tra này không gọi API trả phí hoặc trả về đường dẫn chứa thông tin đăng nhập.

## Hàng đợi

Mặc định: một job chạy, 20 job chờ, chặn URL trùng trong 60 giây. Người dùng đã đăng nhập cùng xem một queue FIFO và danh sách job chung. Vị trí queue được lưu nguyên tử. Hủy job chờ không gọi engine. Hủy job đang chạy dùng cơ chế dừng tiến trình hiện có.

Sau restart, job queued tiếp tục chạy. Job đang chạy bị gián đoạn chuyển thành `failed` với mã `INTERRUPTED`; chỉ chạy lại khi người dùng bấm Retry.

## Dọn dữ liệu

Cleanup không tự chạy ngầm. Xem trước rồi mới áp dụng:

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli cleanup
.\.venv\Scripts\python.exe -m apps.orchestrator.cli cleanup --apply
```

Chỉ job terminal cũ hơn thời hạn retention mới đủ điều kiện xóa. Bỏ qua job đang chạy, đang chờ, còn mới, symlink và đường dẫn ngoài workspace. Báo cáo ghi job ID, dung lượng thu hồi và số job hoàn tất vượt `PIPELINE_MAX_COMPLETED_JOBS`. An toàn retention được ưu tiên hơn giới hạn số lượng; job còn mới không bị xóa.

## Xử lý lỗi

- `FRONTEND_BUILD_MISSING`: chạy `npm run build:production`.
- Production từ chối xác thực: cấu hình mật khẩu và session secret dài ít nhất 32 ký tự.
- Thiếu dung lượng: lưu trữ output cần giữ, xem cleanup dry-run, sau đó mới dùng `--apply`.
- Hook chưa sẵn sàng: kiểm tra đường dẫn Hook, Python, ComfyUI, model/motion và server.
- Review chưa sẵn sàng: chạy doctor/config cục bộ, kiểm tra Python và credentials.
- Backend thứ hai bị chặn: dùng status script; stale lock chỉ được xóa khi PID đã chết.
- Máy LAN không kết nối: kiểm tra network profile `Private`, IPv4, cổng và firewall `LocalSubnet`.

## Gỡ cài đặt

```powershell
.\scripts\stop-background-task.ps1
.\scripts\uninstall-background-task.ps1
.\scripts\remove-lan-firewall.ps1
```

Lệnh cuối cần quyền Administrator. Các script không xóa job, engine, source code, `.env` hoặc log.
