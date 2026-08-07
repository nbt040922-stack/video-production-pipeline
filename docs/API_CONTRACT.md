# Hợp đồng API job

Production dùng cùng origin. Development mặc định: `http://127.0.0.1:8000`.

Trừ health, readiness và login/session, mọi endpoint đều cần cookie đăng nhập hợp lệ. Người dùng thường chỉ truy cập job của mình; admin truy cập được tất cả job.

## Health và readiness

- `GET /api/health`: tiến trình còn sống, chỉ trả trạng thái tối thiểu.
- `GET /api/readiness`: kiểm tra frontend, workspace, Source, Hook, Review, Composer, queue, đĩa và xác thực; không trả secret hoặc gọi API trả phí.

## Xác thực

- `POST /api/auth/login`: nhận `{"username":"...","password":"..."}`, cấp cookie phiên `HttpOnly`.
- `GET /api/auth/session` hoặc `GET /api/auth/me`: trả trạng thái phiên và thông tin người dùng an toàn.
- `POST /api/auth/logout`: xóa cookie phiên.
- `POST /api/auth/change-password`: nhận `current_password`, `new_password`; đổi mật khẩu của chính người đang đăng nhập và cấp lại cookie phiên.

## Tạo và liệt kê job

`POST /api/jobs`

```json
{
  "youtube_url": "https://www.youtube.com/watch?v=demo123"
}
```

Trả HTTP 201 cùng job đã queued. Queue đầy trả `QUEUE_FULL`; URL vừa gửi trùng trả `DUPLICATE_JOB`.

`GET /api/jobs` trả danh sách của người đang đăng nhập. Admin nhận toàn bộ và có thể lọc bằng `owner`, `status`. Mỗi mục gồm chủ sở hữu, `job_id`, tiêu đề nguồn, thời điểm gửi, trạng thái, tiến độ, vị trí queue, stage hiện tại, tình trạng final output và lỗi ngắn.

## Quản trị người dùng

Các route sau chỉ dành cho admin: `GET/POST /api/admin/users`, cùng các thao tác `enable`, `disable`, `reset-password`, `set-role`. API không bao giờ trả password hash.

## Đọc job

`GET /api/jobs/{job_id}` trả trạng thái đã lưu: tiến độ tổng, stage hiện tại, chín stage chi tiết, thời gian, metadata nguồn, trạng thái Hook/Review, lỗi có cấu trúc và final output.

## Tài sản của job

- `GET /api/jobs/{job_id}/assets/thumbnail`: `source/thumbnail.jpg` hợp lệ.
- `GET /api/jobs/{job_id}/assets/hook`: `hook/final_hook.mp4` sau khi Hook hoàn tất.
- `GET /api/jobs/{job_id}/assets/review`: `review/review.mp4`.
- `GET /api/jobs/{job_id}/assets/review-metadata`: metadata Review đã chuẩn hóa.
- `GET /api/jobs/{job_id}/assets/proxy-metrics`: số liệu chi phí proxy.
- `GET /api/jobs/{job_id}/assets/final`: stream `final/final_video.mp4`, hỗ trợ HTTP range theo FastAPI/Starlette.
- `GET /api/jobs/{job_id}/assets/final/download`: tải `final_video.mp4`.

Các route chỉ mở file cố định trong workspace job đã kiểm tra; không nhận đường dẫn filesystem tùy ý.

`POST /api/jobs/{job_id}/open-folder` chỉ mở `final/` trên chính máy host. Request từ máy LAN khác trả HTTP 403 `LOCAL_ONLY`.

## Hủy và chạy lại

`POST /api/jobs/{job_id}/cancel` hủy idempotent nếu job đã cancelled. Job completed hoặc failed trả HTTP 409. Job queued được loại khỏi queue mà không gọi engine.

`POST /api/jobs/{job_id}/retry` chỉ nhận job failed, tạo job mới với `job_id` mới; job và artifact cũ được giữ nguyên.

## Lỗi

API không trả Python traceback:

```json
{
  "error": {
    "code": "INVALID_YOUTUBE_URL",
    "message": "Liên kết YouTube không hợp lệ.",
    "details": null
  }
}
```

Nhóm mã lỗi:

- Source: `INVALID_YOUTUBE_URL`, `PLAYLIST_NOT_SUPPORTED`, `YTDLP_MISSING`, `FFMPEG_MISSING`, `FFPROBE_FAILED`, `PRIVATE_VIDEO`, `VIDEO_UNAVAILABLE`, `AUTH_REQUIRED`, `DOWNLOAD_FAILED`.
- Hook: `HOOK_THUMBNAIL_MISSING`, `HOOK_ENGINE_NOT_READY`, `HOOK_ENGINE_FAILED`, `HOOK_TIMEOUT`, `HOOK_OUTPUT_MISSING`, `HOOK_OUTPUT_INVALID`.
- Review: xem `REVIEW_ENGINE_ADAPTER.md`.
- Composer: xem `FINAL_COMPOSER.md`.
- Pipeline: `JOB_NOT_FOUND`, `INVALID_JOB_STATE`, `CORRUPTED_JOB_METADATA`, `JOB_CANCELLED`, `INTERRUPTED`, `WORKER_ERROR`.

Traceback kỹ thuật chỉ ghi vào `workspace/<job_id>/logs/pipeline.log`.
