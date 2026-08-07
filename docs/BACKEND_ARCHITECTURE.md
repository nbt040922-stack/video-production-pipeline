# Kiến trúc backend

## Công nghệ

Backend dùng Python 3.11+, FastAPI, Pydantic và Uvicorn. Job chạy trong daemon thread của một backend process. `RLock` bảo vệ state chung; không dùng database hoặc queue ngoài.

## Luồng request

```text
React UI
  -> BackendPipelineClient
  -> FastAPI job API
  -> JobManager FIFO
  -> Source + Hook adapter + Review adapter + FinalComposer
  -> workspace riêng + job.json nguyên tử + pipeline.log
```

## Trạng thái job

```text
queued -> validating -> downloading -> processing
       -> composing -> validating_output -> completed

Trạng thái đang chạy -> cancelled
Worker lỗi -> failed
failed -> Retry tạo job queued mới
```

Retry không sửa job cũ. Job mới có `job_id` mới, tăng `attempt` và ghi `retry_of`.

## Stage

Mỗi job có chín stage theo thứ tự. Mỗi stage lưu trạng thái, tiến độ số nguyên, timestamp, thời gian chạy, thông báo an toàn cho người dùng và lỗi có cấu trúc. Trạng thái stage: `pending`, `running`, `completed`, `failed`, `skipped`, `cancelled`.

## Workspace và lưu trạng thái

Job ID là UUID hex thường dài 32 ký tự. Tạo thư mục từ chối trùng. Metadata được ghi vào `job.json.tmp`, sau đó replace nguyên tử sang `job.json`. Artifact được giữ khi failed hoặc cancelled. `workspace/` bị Git ignore.

## Hủy

Mỗi job đang chạy có `threading.Event`. Hủy sẽ set event, đánh dấu stage chưa xong là cancelled, lưu metadata và trả response. Source và Composer kiểm tra event. Hook dừng process tree đang hoạt động. Review gửi tín hiệu cho CLI cleanup trước, chỉ force-kill sau thời gian chờ.

## Khôi phục khi khởi động

`JobManager` nạp job đã lưu. Job `queued` được đưa lại vào FIFO. Job trả phí đang chạy dở chuyển thành `failed` với mã `INTERRUPTED`, không tự chạy lại. Metadata hỏng được giữ nguyên và trả `CORRUPTED_JOB_METADATA`.

## Adapter pipeline

Source dùng yt-dlp, Pillow, FFmpeg và ffprobe. `HookEngineAdapter` bọc Hook CLI `generate` rồi `phase4`. `ReviewEngineAdapter` bọc `review_cli.py run --progress-jsonl`. `FinalComposer` dùng FFmpeg concat, fallback re-encode chuẩn hóa rồi kiểm tra bằng ffprobe. Hai submodule không bị sửa.

## Frontend và CORS

Production luôn dùng `BackendPipelineClient` với request `/api` cùng origin. Development mặc định dùng mock; đặt `VITE_PIPELINE_MODE=backend` và tùy chọn `VITE_API_BASE_URL=http://127.0.0.1:8000` để dùng backend thật.

Production không bật CORS. Development giới hạn CORS trong `PIPELINE_DEV_CORS_ORIGINS`, mặc định là các origin Vite localhost.
