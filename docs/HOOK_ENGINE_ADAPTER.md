# Hook Engine Adapter

## Hợp đồng hộp đen

Adapter dùng Hook Engine CLI trong `main.py`; không import, sửa hoặc sao chép logic engine.

```text
thumbnail.jpg
  -> main.py generate
  -> raw_candidate.mp4
  -> main.py phase4
  -> final_hook.mp4
```

Engine cần Python 3.11+, PyTorch có CUDA, FFmpeg/ffprobe, ComfyUI thường ở `http://127.0.0.1:8188`, workflow/checkpoint Wan và DWPose cục bộ, cùng motion `metadata.json` khớp `HOOK_MOTION_ID`. Runtime không tự tải model hoặc fallback. Không cần `OPENAI_API_KEY` vì adapter truyền thumbnail thẳng cho `generate`.

## Luồng adapter

1. `prepare()` yêu cầu đúng `source/thumbnail.jpg`, kiểm tra JPEG bằng Pillow, kiểm tra CLI/runtime và tạo thư mục tạm riêng.
2. `run()` gọi `generate` bằng argument array với `shell=False`.
3. Đọc engine job ID và `raw_candidate.mp4` từ output CLI.
4. Gọi `phase4` với raw candidate đó.
5. Chuyển kết quả thành `hook/final_hook.mp4`.
6. ffprobe kiểm tra khả năng đọc, resolution dương và thời lượng gần 5 giây trong `HOOK_DURATION_TOLERANCE_SECONDS`.
7. Ghi nguyên tử `hook/metadata.json`.
8. `cleanup()` chỉ xóa file tạm do adapter tạo; output lỗi hoặc cancelled bị loại.

`status()` trả trạng thái, tiến độ và thông báo. `cancel()` ngắt ComfyUI job và dừng process tree CLI đang chạy.

## Cấu hình

```text
HOOK_ENGINE_PATH=engines/hook-engine
HOOK_ENGINE_PYTHON=python
HOOK_MOTION_ID=motion1
HOOK_ENGINE_SERVER=http://127.0.0.1:8188
HOOK_ENGINE_TIMEOUT_SECONDS=7200
HOOK_ENGINE_SEED=42
HOOK_MIN_COMPATIBILITY=0.35
HOOK_DURATION_TOLERANCE_SECONDS=0.25
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
```

Submodule chỉ chứa code engine. Model ComfyUI và motion asset cục bộ bị engine ignore. Khi asset nằm ở runtime riêng, trỏ `HOOK_ENGINE_PATH` tới checkout đầy đủ đó.

## Output

```text
workspace/<job_id>/hook/
|-- final_hook.mp4
`-- metadata.json
```

Metadata lưu parent job ID, engine job ID, motion ID, đường dẫn input/output tương đối, thời lượng, resolution, FPS và codec.

`GET /api/jobs/{job_id}/assets/hook` trả `video/mp4` sau khi Hook hoàn tất. UI polling nhận tiến độ thật, thông báo, thời gian và `preview_url`.

## Smoke test

```powershell
$env:HOOK_ENGINE_PATH='D:\AI_hook_engine'
$env:HOOK_ENGINE_PYTHON='D:\AI_hook_engine\ComfyUI\.venv\Scripts\python.exe'
$env:HOOK_MOTION_ID='motion1'
.\.venv\Scripts\python.exe scripts\smoke_hook.py "C:\path\to\thumbnail.jpg"
```

Test tự động dùng CLI runner giả; không chạy ComfyUI, GPU hoặc tạo video thật.

Mã lỗi: `HOOK_THUMBNAIL_MISSING`, `HOOK_THUMBNAIL_INVALID`, `HOOK_ENGINE_NOT_READY`, `HOOK_ENGINE_FAILED`, `HOOK_TIMEOUT`, `HOOK_OUTPUT_MISSING`, `HOOK_OUTPUT_INVALID`; hủy pipeline dùng `JOB_CANCELLED`.
