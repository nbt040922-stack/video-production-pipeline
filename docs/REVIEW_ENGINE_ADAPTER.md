# Review Engine Adapter

## Cách tích hợp

`ReviewEngineAdapter` bọc CLI headless chính thức:

```text
review_cli.py run --progress-jsonl
```

Adapter truyền `source/source.mp4` đã có nên downloader của engine không chạy. Logic engine vẫn nằm trong submodule có version độc lập.

## Vòng đời

- `prepare()`: kiểm tra đường dẫn, source metadata, credentials, voice reference, Python, FFmpeg và ffprobe trước khi gọi dịch vụ trả phí.
- `run()`: chạy một CLI process riêng, đọc event JSONL, thu artifact và kiểm tra kết quả.
- `status()`: trả trạng thái không chứa secret.
- `cancel()`: báo CLI tự cleanup cục bộ/từ xa; chỉ force-kill process tree khi hết thời gian chờ.
- `cleanup()`: chỉ xóa file tạm của adapter; giữ Source, Hook, Review hoàn tất và log.

## Cấu hình

| Biến | Ý nghĩa |
|---|---|
| `REVIEW_ENGINE_PATH` | Checkout Review Engine chứa `review_cli.py` |
| `REVIEW_ENGINE_PYTHON` | Python có dependency Review Engine |
| `REVIEW_ENGINE_TIMEOUT_SECONDS` | Timeout toàn Review; mặc định `14400` |
| `REVIEW_VOICE_REFERENCE_PATH` | File giọng mẫu; mặc định `<REVIEW_ENGINE_PATH>/voice.wav` nếu có |
| `REVIEW_VOICE_REFERENCE_TEXT` | Transcript chính xác tùy chọn của giọng mẫu |
| `GEMINI_API_KEY` | Credential Gemini |
| `TWELVE_LABS_API_KEY` | Credential Twelve Labs |
| `TWELVE_API_KEY` | Alias tương thích khi biến chuẩn không có |
| `USE_PROXY_VIDEO` | Bật Event Window proxy; mặc định `true` |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Ghi đè media tool |

OmniVoice do `.venv-omnivoice` của Review Engine quản lý. Chạy installer của engine một lần. Không commit credentials thật.

## Input/output

Input gồm job ID, YouTube URL gốc, `source/source.mp4`, `source/metadata.json` và workspace riêng.

```text
workspace/<job_id>/review/
|-- review.mp4
|-- metadata.json
|-- proxy_metrics.json
|-- window_mapping.json
|-- script/review.json
|-- voice/voice.wav
|-- timeline/timeline.json
`-- logs/engine.jsonl
```

Ba file trong thư mục con chỉ có khi engine tạo. `metadata.json` dùng đường dẫn tương đối với repo cha và giá trị ffprobe thật; không lộ đường dẫn tạm nội bộ engine.

## Ánh xạ tiến độ

| Stage JSONL của engine | Stage UI |
|---|---|
| `preparing`, `writing_review` | Viết bài đánh giá |
| `generating_voice`, `transcribing` | Tạo giọng đọc |
| `selecting_windows`, `indexing_proxy`, `searching_scenes`, `mapping_timeline` | Chọn cảnh |
| `rendering_review`, `validating_output` | Dựng video review |

Tiến độ chỉ đến từ event JSONL thật, không dùng timer giả ở frontend.

## Kiểm tra, hủy và khôi phục

Adapter kiểm tra video đọc được, không rỗng, có video/audio stream, thời lượng/resolution/FPS dương, codec, proxy metric hữu hạn, fallback nhất quán, mapping không lỗi khi proxy thành công, window đúng thứ tự và sai số thời lượng hợp lệ. Full-source fallback hợp lệ với 0% tiết kiệm vẫn được chấp nhận và ghi nhận.

Hủy/timeout báo CLI trước để `finally` xóa Twelve index tạm. Nếu CLI không thoát trong 10 giây mới dừng process tree. Restart chuyển job chạy dở thành `INTERRUPTED`, không tự gọi lại dịch vụ trả phí.

Mã lỗi ổn định: `REVIEW_ENGINE_NOT_CONFIGURED`, `REVIEW_ENGINE_ENTRYPOINT_MISSING`, `REVIEW_ENGINE_CREDENTIALS_MISSING`, `REVIEW_ENGINE_TIMEOUT`, `GEMINI_FAILED`, `OMNIVOICE_FAILED`, `TWELVE_INDEX_FAILED`, `MARENGO_SEARCH_FAILED`, `PROXY_MAPPING_FAILED`, `REVIEW_RENDER_FAILED`, `REVIEW_OUTPUT_INVALID`, `REVIEW_CANCELLED`.

## Job thật thủ công

Lệnh này gọi dịch vụ trả phí. Kiểm tra giá/quota Gemini và Twelve Labs trước.

```powershell
$env:REVIEW_ENGINE_PATH='F:\CA_NHAN\video-short-workflow'
$env:REVIEW_ENGINE_PYTHON='F:\CA_NHAN\video-short-workflow\.venv\Scripts\python.exe'
$env:REVIEW_VOICE_REFERENCE_PATH='C:\path\to\reference.wav'
$env:GEMINI_API_KEY='...'
$env:TWELVE_LABS_API_KEY='...'
$env:USE_PROXY_VIDEO='true'
$env:VITE_PIPELINE_MODE='backend'
.\scripts\dev.ps1
```

Test mặc định dùng CLI giả cục bộ, không gọi dịch vụ trả phí và không tự retry dịch vụ trả phí.
