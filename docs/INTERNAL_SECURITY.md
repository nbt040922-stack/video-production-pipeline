# Bảo mật nội bộ

M08 dùng tài khoản riêng. Mật khẩu được băm `scrypt` với salt riêng. Cookie phiên là `HttpOnly`, `SameSite=Strict`, có TTL và chỉ chứa định danh ổn định cùng phiên bản session đã ký. Backend luôn đọc role từ SQLite. Mọi route job và asset kiểm tra chủ sở hữu trước khi tìm đường dẫn tệp; truy cập chéo trả 404 an toàn.

Đây vẫn là dịch vụ LAN HTTP, không được mở trực tiếp ra Internet. Nếu mạng không đáng tin cậy, đặt reverse proxy HTTPS phía trước.

Cookie có `HttpOnly`, `SameSite=Strict`, đường dẫn `/` và thời hạn mặc định 12 giờ có thể cấu hình. Mật khẩu và khóa ký phiên không được lưu ở frontend, trả về qua API, đưa vào readiness hay ghi vào log.

Mọi API tạo, liệt kê, xem trạng thái, tải tài sản, hủy, chạy lại, đọc metadata và mở thư mục job đều cần đăng nhập. Production không bật CORS vì UI và API cùng origin. Development chỉ cho phép các origin Vite localhost trong `PIPELINE_DEV_CORS_ORIGINS`, có credentials và không dùng wildcard `*`.

MVP LAN riêng dùng HTTP nên chưa bật thuộc tính cookie `Secure`. Dữ liệu có thể bị nghe lén trên mạng không tin cậy. Chỉ chạy trong mạng Windows `Private`, dùng firewall `LocalSubnet`; không port forwarding, tunnel hoặc công khai dịch vụ ra Internet.

Người dùng thường chỉ xem và thao tác job của mình; admin xem được toàn bộ và quản lý tài khoản. Sự kiện đăng nhập, quản trị và thao tác job quan trọng được ghi JSON vào audit log nhưng không chứa mật khẩu, cookie, token hoặc API key. Asset endpoint chỉ truy cập đường dẫn cố định sau khi kiểm tra quyền; không có API đọc filesystem hay log tùy ý. `Open Folder` vẫn từ chối máy LAN khác.
