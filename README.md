# Video Production Pipeline

Parent repository for a modular video-production workflow. It coordinates two production-ready engines without merging or duplicating their code or Git history.

## Purpose

The pipeline turns a YouTube URL into a composed final video:

```text
YouTube URL -> Downloader -> Hook Engine -> Review Engine -> Composer -> Final Video
```

- **Hook Engine** produces `final_hook.mp4`.
- **Review Engine** produces `review.mp4`.
- **Composer** will combine those outputs into the final video.
- **Orchestrator** coordinates the real Source, Hook, and Review stages while Composer remains a stub.

See [docs/Architecture.md](docs/Architecture.md) for component boundaries and data flow.

## Repository layout

```text
video-production-pipeline/
|-- apps/
|   `-- orchestrator/
|-- composer/
|-- config/
|-- docs/
|   `-- Architecture.md
|-- engines/
|   |-- hook-engine/       # Git submodule
|   `-- review-engine/     # Git submodule
|-- tests/
|-- workspace/             # Ignored runtime files
|-- .gitignore
|-- .gitmodules
|-- README.md
|-- setup.ps1
`-- setup.sh
```

## Workspace

`workspace/` is the handoff area for downloaded media, intermediate files, logs, and generated videos. Its contents are intentionally ignored by Git. Keep source code and durable configuration outside it.

## Submodules

The engine repositories remain independent and retain their own histories:

- `engines/hook-engine`: <https://github.com/nbt040922-stack/AI_hook_engine.git>
- `engines/review-engine`: <https://github.com/nbt040922-stack/video-short-workflow.git>

Clone everything in one command:

```bash
git clone --recursive <video-production-pipeline-url>
```

If the parent was cloned without `--recursive`, initialize the engines afterward:

```bash
git submodule update --init --recursive
```

## Development workflow

1. Clone with submodules.
2. Run `./setup.sh` on macOS/Linux or `./setup.ps1` in PowerShell.
3. Develop each engine in its own repository and branch.
4. Commit parent-project changes separately from engine changes.
5. Keep generated media and temporary files under `workspace/`.

The setup scripts create `.venv`, initialize submodules, and install dependency manifests that the engines provide. The Hook Engine currently has no root dependency manifest, so the scripts make no assumptions about additional packages for it.

## Updating the Hook Engine

```bash
cd engines/hook-engine
git switch main
git pull --ff-only
cd ../..
git add engines/hook-engine
git commit -m "chore: update hook engine"
```

## Updating the Review Engine

```bash
cd engines/review-engine
git switch main
git pull --ff-only
cd ../..
git add engines/review-engine
git commit -m "chore: update review engine"
```

Updating a submodule changes only the commit pointer stored by this parent repository. Engine code changes must be committed and pushed in the engine's own repository first.

## Orchestrator

Run the local orchestrator API with:

```bash
python -m apps.orchestrator
```
## Frontend prototype

The desktop-first React frontend defaults to mock mode. Backend mode polls the local orchestrator and previews real Source, Hook, and Review assets.

```bash
npm install
npm run dev
```

Validation commands:

```bash
npm test
npm run build
```

See [docs/FRONTEND_ARCHITECTURE.md](docs/FRONTEND_ARCHITECTURE.md) for the component model and future backend integration points.

No screenshot is stored yet. If one is added later, use `docs/screenshots/frontend.png`.
## Local backend

Install Python and frontend dependencies:

```bash
./setup.sh
npm install
```

On Windows PowerShell:

```powershell
.\setup.ps1
npm install
```

Run backend only:

```bash
.venv/bin/python -m uvicorn apps.orchestrator.api:app --host 127.0.0.1 --port 8000
```

Use `.venv\Scripts\python.exe` instead on Windows.

Run frontend against backend:

```bash
VITE_PIPELINE_MODE=backend VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1
```

Run frontend, parent backend, and Hook ComfyUI runtime:

```bash
./scripts/dev.sh
```

```powershell
.\scripts\dev.ps1
```

Run all tests and the frontend build:

```bash
.venv/bin/python -m pytest
npm test
npm run build
```

The source stage uses yt-dlp, Pillow, FFmpeg, and ffprobe. Hook and Review wrap their engines' supported CLIs. Final Composer joins their validated videos locally with FFmpeg. See [docs/BACKEND_ARCHITECTURE.md](docs/BACKEND_ARCHITECTURE.md) and [docs/API_CONTRACT.md](docs/API_CONTRACT.md).
## Real source ingestion

Install dependencies through `setup.ps1` or `setup.sh`. FFmpeg and ffprobe must be available on `PATH`, or configured through `FFMPEG_PATH` and `FFPROBE_PATH`.

The backend accepts one standard YouTube or `youtu.be` URL, downloads at most 1080p without upscaling, and writes `source.mp4`, `thumbnail.jpg`, and `metadata.json` into the isolated job workspace.

Manual real-download smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

See [docs/SOURCE_INGESTOR.md](docs/SOURCE_INGESTOR.md). Default tests mock yt-dlp and never download real media.
## Real Hook Engine integration

The Hook adapter passes `workspace/<job_id>/source/thumbnail.jpg` to the existing Hook Engine CLI, runs `generate` and `phase4`, validates the five-second video with ffprobe, and exposes `hook/final_hook.mp4` for preview. Hook Engine internals and submodule history remain untouched.

A complete local engine runtime needs ComfyUI, Wan resources, an approved motion, FFmpeg, ffprobe, and the engine Python environment. Configure `HOOK_ENGINE_PATH`, `HOOK_ENGINE_PYTHON`, and `HOOK_MOTION_ID` when runtime is not in the default sibling location.

`scripts/dev.ps1` and `scripts/dev.sh` now start ComfyUI automatically when it is not already healthy. They prefer a complete sibling `AI_hook_engine` checkout, otherwise use `HOOK_ENGINE_PATH`. Review Engine remains an on-demand CLI subprocess and needs no background server.

Manual adapter smoke test:

```powershell
$env:HOOK_ENGINE_PATH='D:\AI_hook_engine'
$env:HOOK_ENGINE_PYTHON='D:\AI_hook_engine\ComfyUI\.venv\Scripts\python.exe'
$env:HOOK_MOTION_ID='motion1'
.\.venv\Scripts\python.exe scripts\smoke_hook.py "C:\path\to\thumbnail.jpg"
```

See [docs/HOOK_ENGINE_ADAPTER.md](docs/HOOK_ENGINE_ADAPTER.md). Automated tests do not run ComfyUI or GPU generation.

## Real Review Engine integration

The Review adapter passes the existing `source/source.mp4` to `review_cli.py run --progress-jsonl`, maps structured engine events into the four approved Review stages, validates `review.mp4` and proxy mapping data, then exposes the real preview and savings/fallback metadata.

Configure `REVIEW_ENGINE_PATH`, `REVIEW_ENGINE_PYTHON`, `REVIEW_VOICE_REFERENCE_PATH`, `GEMINI_API_KEY`, and `TWELVE_LABS_API_KEY`. `USE_PROXY_VIDEO` defaults to `true`. OmniVoice must be installed in the Review Engine as documented there.

See [docs/REVIEW_ENGINE_ADAPTER.md](docs/REVIEW_ENGINE_ADAPTER.md). Default tests never call paid services.

## Real Final Composer

The Final Composer validates `hook/final_hook.mp4` and `review/review.mp4`, joins them in that order with FFmpeg stream copy when compatible, and falls back to H.264/AAC 1920×1080 at 30 FPS only when needed. The job completes only after ffprobe validates `final/final_video.mp4`.

Manual smoke test with an existing completed Hook/Review workspace:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_composer.py "workspace\<job_id>"
```

See [docs/FINAL_COMPOSER.md](docs/FINAL_COMPOSER.md).
