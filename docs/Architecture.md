# Kiến trúc tổng thể

## Ranh giới người dùng (M08)

SQLite chỉ lưu tài khoản và phiên bản phiên đăng nhập. Job tiếp tục lưu bằng JSON trong workspace; mỗi job mới có `owner_user_id` và `owner_username` cố định. API kiểm tra chủ sở hữu trước mọi thao tác hoặc tải asset. Admin được xem toàn bộ, còn job cũ không có chủ chỉ admin nhìn thấy. Hàng đợi xử lý toàn cục vẫn FIFO.

## Luồng pipeline

```text
YouTube URL
    |
    v
Source Ingestor
    | source.mp4 + thumbnail.jpg
    v
HookEngineAdapter
    |
    v
Hook Engine CLI (generate + phase4)
    | hook/final_hook.mp4
    v
ReviewEngineAdapter
    |
    v
Review Engine CLI
    | review/review.mp4
    v
FinalComposer
    |
    v
final/final_video.mp4
```

## Ranh giới thành phần

### Source Ingestor

Orchestrator kiểm tra một YouTube URL rồi ghi `source/source.mp4`, `source/thumbnail.jpg` và `source/metadata.json` trong workspace riêng của job.

### HookEngineAdapter

Repo cha quản lý workspace, tiến trình CLI, tiến độ, hủy, cleanup, thu output và kiểm tra ffprobe. Adapter gọi CLI công khai của Hook Engine; không import hoặc sao chép logic engine.

### Hook Engine

Submodule `engines/hook-engine` có version độc lập và được xem như hộp đen. `generate` tạo raw candidate; `phase4` tạo `final_hook.mp4` khoảng 5 giây.

### ReviewEngineAdapter và Review Engine

Submodule `engines/review-engine` là hộp đen. CLI headless nhận source video từ repo cha, phát tiến độ JSONL và tạo Review media cùng proxy artifact. Adapter ánh xạ tiến độ, quản lý hủy và kiểm tra output.

### FinalComposer

Composer đọc Hook và Review đã hoàn tất, ghép theo thứ tự bằng FFmpeg, fallback re-encode khi cần, rồi kiểm tra `final_video.mp4` bằng ffprobe.

### Orchestrator

`apps.orchestrator` điều phối stage, trạng thái job, đường dẫn biệt lập, lưu metadata nguyên tử, queue FIFO, lỗi có cấu trúc, hủy và asset endpoint.

## Hợp đồng workspace

```text
workspace/<job_id>/
|-- source/
|   |-- source.mp4
|   |-- thumbnail.jpg
|   `-- metadata.json
|-- hook/
|   |-- final_hook.mp4
|   `-- metadata.json
|-- review/
|   |-- review.mp4
|   |-- metadata.json
|   |-- proxy_metrics.json
|   `-- window_mapping.json
|-- final/
|   |-- final_video.mp4
|   `-- metadata.json
|-- metadata/job.json
`-- logs/pipeline.log
```

Artifact runtime không đưa vào Git. Repo cha không ghi vào thư mục của hai engine.

## Version

Mỗi submodule ghim đúng một engine commit. Cập nhật engine là thay đổi commit pointer rõ ràng ở repo cha; lịch sử và release của engine vẫn độc lập.
