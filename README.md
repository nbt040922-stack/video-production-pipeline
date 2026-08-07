# Video Production Pipeline

## Tài khoản LAN (M08)

Hệ thống dùng tài khoản riêng và tự tách công việc theo người tạo. Admin quản lý tài khoản bằng CLI và có thể xem toàn bộ job; người dùng thường chỉ thấy job của mình. Xem [Sử dụng LAN nhiều tài khoản](docs/MULTI_USER_LAN.md), [Quản lý người dùng](docs/USER_ADMINISTRATION.md) và [Nâng cấp M08](docs/M08_MIGRATION.md).

Repo cha điều phối quy trình sản xuất video theo module. Hai engine production-ready vẫn là Git submodule độc lập; repo này không merge, sao chép hoặc sửa lịch sử của chúng.

## Mục đích

Pipeline biến một YouTube URL thành video hoàn chỉnh:

```text
YouTube URL -> Bộ tải nguồn -> Hook Engine -> Review Engine -> Composer -> Video cuối
```

- **Hook Engine** tạo `final_hook.mp4`.
- **Review Engine** tạo `review.mp4`.
- **FinalComposer** ghép hai video thành `final_video.mp4`.
- **Orchestrator** quản lý queue, workspace, tiến độ, lỗi, hủy và API.

Xem [docs/Architecture.md](docs/Architecture.md).

## Cấu trúc repo

```text
video-production-pipeline/
|-- apps/orchestrator/        # FastAPI, JobManager, adapter, runtime LAN
|-- composer/                 # Package Composer
|-- config/                   # Cấu hình repo cha
|-- docs/                     # Tài liệu tiếng Việt
|-- engines/
|   |-- hook-engine/          # Git submodule
|   `-- review-engine/        # Git submodule
|-- scripts/                  # Dev, smoke test, production Windows
|-- src/                      # React frontend
|-- tests/                    # Backend tests
|-- workspace/                # Dữ liệu runtime, Git ignore
|-- .env.example
|-- setup.ps1
`-- setup.sh
```

## Workspace

`workspace/` chứa media đã tải, file trung gian, metadata, log theo job và video tạo ra. Nội dung bị Git ignore. Source code và cấu hình bền vững phải nằm ngoài thư mục này.

```text
workspace/<job_id>/
|-- source/
|-- hook/
|-- review/
|-- final/
|-- metadata/job.json
`-- logs/pipeline.log
```

## Git submodule

- `engines/hook-engine`: <https://github.com/nbt040922-stack/AI_hook_engine.git>
- `engines/review-engine`: <https://github.com/nbt040922-stack/video-short-workflow.git>

Clone đủ submodule:

```bash
git clone --recursive <video-production-pipeline-url>
```

Nếu đã clone thiếu `--recursive`:

```bash
git submodule update --init --recursive
```

### Cập nhật Hook Engine

```bash
cd engines/hook-engine
git switch main
git pull --ff-only
cd ../..
git add engines/hook-engine
git commit -m "chore: update hook engine"
```

### Cập nhật Review Engine

```bash
cd engines/review-engine
git switch main
git pull --ff-only
cd ../..
git add engines/review-engine
git commit -m "chore: update review engine"
```

Code engine phải được commit/push trong repo engine trước. Repo cha chỉ lưu commit pointer mới.

## Cài môi trường

macOS/Linux:

```bash
./setup.sh
npm install
```

Windows PowerShell:

```powershell
.\setup.ps1
npm install
```

Setup tạo `.venv`, khởi tạo submodule và cài dependency manifest hiện có. Hook Engine runtime đầy đủ vẫn cần ComfyUI, model và motion asset riêng.

## Chạy development

Frontend mock:

```bash
npm run dev
```

Backend cục bộ trên Windows:

```powershell
.\.venv\Scripts\python.exe -m uvicorn apps.orchestrator.api:app --host 127.0.0.1 --port 8000
```

Frontend development dùng backend thật:

```powershell
$env:VITE_PIPELINE_MODE='backend'
$env:VITE_API_BASE_URL='http://127.0.0.1:8000'
npm run dev -- --host 127.0.0.1
```

Chạy frontend, backend repo cha và Hook ComfyUI:

```powershell
.\scripts\dev.ps1
```

macOS/Linux:

```bash
./scripts/dev.sh
```

## Kiểm tra

```powershell
.\.venv\Scripts\python.exe -m pytest
npm test -- --run
npm run build:production
```

Test mặc định dùng adapter giả, không tải YouTube thật, không chạy GPU và không gọi API trả phí.

## Bộ tải nguồn thật

Source stage dùng yt-dlp, Pillow, FFmpeg và ffprobe. FFmpeg/ffprobe phải có trên `PATH` hoặc đặt `FFMPEG_PATH`, `FFPROBE_PATH`.

Backend nhận một URL YouTube/`youtu.be`, tải tối đa 1080p không upscale, rồi tạo:

```text
source/source.mp4
source/thumbnail.jpg
source/metadata.json
```

Smoke test tải thật:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Xem [docs/SOURCE_INGESTOR.md](docs/SOURCE_INGESTOR.md).

## Hook Engine thật

Hook adapter truyền `source/thumbnail.jpg` vào CLI có sẵn, chạy `generate` rồi `phase4`, kiểm tra video khoảng 5 giây bằng ffprobe và xuất `hook/final_hook.mp4`. Không sửa nội bộ Hook Engine.

Cấu hình thường dùng:

```text
HOOK_ENGINE_PATH=D:\AI_hook_engine
HOOK_ENGINE_PYTHON=D:\AI_hook_engine\ComfyUI\.venv\Scripts\python.exe
HOOK_MOTION_ID=motion1
HOOK_ENGINE_SERVER=http://127.0.0.1:8188
```

`scripts/dev.ps1` và `scripts/run-production.ps1` tự khởi động ComfyUI nếu chưa sẵn sàng.

Smoke test:

```powershell
$env:HOOK_ENGINE_PATH='D:\AI_hook_engine'
$env:HOOK_ENGINE_PYTHON='D:\AI_hook_engine\ComfyUI\.venv\Scripts\python.exe'
$env:HOOK_MOTION_ID='motion1'
.\.venv\Scripts\python.exe scripts\smoke_hook.py "C:\path\to\thumbnail.jpg"
```

Xem [docs/HOOK_ENGINE_ADAPTER.md](docs/HOOK_ENGINE_ADAPTER.md).

## Review Engine thật

Review adapter truyền `source/source.mp4` vào `review_cli.py run --progress-jsonl`, ánh xạ tiến độ engine sang bốn stage UI, kiểm tra `review.mp4`, proxy mapping và metadata.

Biến chính:

```text
REVIEW_ENGINE_PATH=
REVIEW_ENGINE_PYTHON=
REVIEW_VOICE_REFERENCE_PATH=
GEMINI_API_KEY=
TWELVE_LABS_API_KEY=
USE_PROXY_VIDEO=true
```

OmniVoice phải được cài trong Review Engine theo tài liệu engine. Job thật có thể phát sinh phí Gemini/Twelve Labs. Xem [docs/REVIEW_ENGINE_ADAPTER.md](docs/REVIEW_ENGINE_ADAPTER.md).

## Final Composer thật

Composer kiểm tra `hook/final_hook.mp4` và `review/review.mp4`, ghép Hook trước rồi Review. Nếu codec/resolution/FPS tương thích, dùng stream copy. Nếu không, fallback H.264/AAC 1920×1080, 30 FPS. Job chỉ completed sau khi ffprobe chấp nhận `final/final_video.mp4`.

Smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_composer.py "workspace\<job_id>"
```

Xem [docs/FINAL_COMPOSER.md](docs/FINAL_COMPOSER.md).

## Production LAN trên Windows

FastAPI phục vụ UI và API cùng origin:

```text
http://HOST:8000/        UI
http://HOST:8000/api/    API
```

### Cách dễ nhất: bấm một file

Bấm đúp `CHAY_LAN.cmd` ở thư mục gốc. Lần đầu file tự tạo session secret, migrate dữ liệu, hỏi thông tin admin, build frontend, mở firewall `LocalSubnet`, cài Task Scheduler và chạy dịch vụ. Sau đó Windows tự chạy dịch vụ mỗi khi đăng nhập; không cần setup lại.

### 1. Tạo cấu hình

```powershell
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m apps.orchestrator.cli generate-secret
```

Điền ít nhất:

```text
PIPELINE_ENV=production
PIPELINE_HOST=0.0.0.0
PIPELINE_PORT=8000
PIPELINE_SESSION_SECRET=<secret ngẫu nhiên dài ít nhất 32 ký tự>
PIPELINE_DATABASE_PATH=data/pipeline.db
PIPELINE_MAX_ACTIVE_JOBS_PER_USER=5
```

Không commit `.env`.

### 2. Build và chạy chẩn đoán

```powershell
npm run build:production
.\scripts\run-production.ps1
```

Hiển thị URL:

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli lan-info
```

### 3. Mở firewall thủ công

Chạy PowerShell bằng Administrator:

```powershell
.\scripts\allow-lan-firewall.ps1
```

Rule `Video Production Pipeline LAN (TCP)` chỉ nhận kết nối từ `LocalSubnet` trên profile `Private`. Không mở Internet hoặc router port forwarding.

### 4. Cài chạy nền

```powershell
.\scripts\install-background-task.ps1 -Mode Logon
.\scripts\start-background-task.ps1
.\scripts\status-background-task.ps1
```

Dừng và gỡ:

```powershell
.\scripts\stop-background-task.ps1
.\scripts\uninstall-background-task.ps1
.\scripts\remove-lan-firewall.ps1
```

## Xác thực và queue

- Người dùng nhập mật khẩu nội bộ; backend cấp cookie `HttpOnly`, `SameSite=Strict`.
- Production từ chối chạy LAN nếu thiếu mật khẩu/session secret.
- Mọi người đã đăng nhập cùng xem danh sách job.
- Mặc định một job chạy, 20 job chờ, chống URL trùng trong 60 giây.
- Job queued sống qua restart; job chạy dở thành `INTERRUPTED` và cần Retry.
- Máy LAN tải final video; `Open Folder` chỉ dùng trên host.

## Retention và log

Cleanup luôn chạy thủ công, mặc định là dry-run:

```powershell
.\.venv\Scripts\python.exe -m apps.orchestrator.cli cleanup
.\.venv\Scripts\python.exe -m apps.orchestrator.cli cleanup --apply
```

Không xóa job đang chạy/queued hoặc job còn mới. Log production xoay vòng tại:

```text
logs/server.log
logs/access.log
logs/worker.log
```

## Tài liệu chi tiết

- [Kiến trúc tổng thể](docs/Architecture.md)
- [Kiến trúc backend](docs/BACKEND_ARCHITECTURE.md)
- [Kiến trúc frontend](docs/FRONTEND_ARCHITECTURE.md)
- [Hợp đồng API](docs/API_CONTRACT.md)
- [Triển khai LAN](docs/LAN_DEPLOYMENT.md)
- [Chạy nền Windows](docs/WINDOWS_BACKGROUND_RUNTIME.md)
- [Bảo mật nội bộ](docs/INTERNAL_SECURITY.md)
- [Vận hành](docs/OPERATIONS.md)

Không công khai MVP này qua Internet, port forwarding hoặc tunnel.
