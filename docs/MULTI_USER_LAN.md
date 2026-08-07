# Sử dụng LAN nhiều tài khoản

Mỗi người dùng có tài khoản riêng. Công việc mới được gắn cố định với người tạo; người dùng thường chỉ thấy, tải, hủy và thử lại công việc của chính mình. Admin thấy tất cả công việc, kể cả job cũ chưa có chủ sở hữu.

## Khởi động lần đầu

1. Nhấp đúp `CHAY_LAN.cmd`.
2. Nhập tên đăng nhập, tên hiển thị và mật khẩu admin khi được hỏi.
3. Tạo năm tài khoản bằng các lệnh trong `USER_ADMINISTRATION.md`.
4. Gửi địa chỉ LAN hiển thị trên màn hình và tài khoản riêng cho từng người.

Hàng đợi vẫn là FIFO toàn hệ thống. Mỗi người mặc định được có tối đa 5 job đang hoạt động; chỉnh bằng `PIPELINE_MAX_ACTIVE_JOBS_PER_USER`.

Không chia sẻ cookie trình duyệt hoặc dùng chung một tài khoản. Nhật ký quản trị nằm tại `logs/audit.log` và không ghi mật khẩu, khóa phiên hay API key.
