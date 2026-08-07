# Nâng cấp lên M08

## Trước khi chạy

Tắt backend đang chạy và sao lưu thư mục `data/` cùng `workspace/` nếu cần bản sao ngoài máy.

## Thực hiện

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli migrate-m08
.\.venv\Scripts\python.exe -m apps.orchestrator.cli create-admin
```

Lệnh migrate có thể chạy lại. Nó tạo SQLite tại `data/pipeline.db` và sao lưu metadata job cũ vào `data/m08-backup/jobs/`. Job cũ không được sửa và chỉ admin nhìn thấy.

Sau đó build frontend và khởi động bằng `CHAY_LAN.cmd`. Kiểm tra `/api/readiness`: `database_ready` và `user_setup_ready` phải là `true`.

## Quay lui

Tắt backend, lưu bản dữ liệu M08 nếu cần điều tra, rồi khôi phục mã nguồn phiên bản M07. Job JSON cũ vẫn giữ nguyên; bản sao nằm trong `data/m08-backup/`.
