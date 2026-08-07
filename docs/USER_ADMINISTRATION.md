# Quản lý người dùng

Chạy các lệnh sau tại thư mục gốc dự án. Mật khẩu được nhập ẩn, không đặt trên dòng lệnh.

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli create-admin
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users list
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users create user01 --display-name "Người dùng 01"
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users disable user01
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users enable user01
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users reset-password user01
.\.venv\Scripts\python.exe -m apps.orchestrator.cli users set-role user01 admin
```

Tên đăng nhập dài 3–32 ký tự, gồm chữ thường, số, dấu chấm, gạch dưới hoặc gạch ngang. Mật khẩu dài ít nhất 10 ký tự. Không thể khóa hoặc hạ quyền admin cuối cùng.

Khóa tài khoản, đổi mật khẩu hoặc đổi role sẽ vô hiệu ngay các phiên đăng nhập cũ.

Người dùng tự đổi mật khẩu tại **Cài đặt → Đổi mật khẩu**. Hệ thống yêu cầu mật khẩu hiện tại và mật khẩu mới dài ít nhất 10 ký tự.
