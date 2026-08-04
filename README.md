# Video Production Pipeline

Parent repository for a modular video-production workflow. It coordinates two production-ready engines without merging or duplicating their code or Git history.

## Purpose

The planned pipeline turns a YouTube URL into a composed final video:

```text
YouTube URL -> Downloader -> Hook Engine -> Review Engine -> Composer -> Final Video
```

- **Hook Engine** produces `final_hook.mp4`.
- **Review Engine** produces `review.mp4`.
- **Composer** will combine those outputs into the final video.
- **Orchestrator** will coordinate the stages in a future implementation.

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

## Future orchestrator

No orchestrator is implemented yet. Its future entry point will be run as:

```bash
python -m apps.orchestrator
```
## Frontend prototype

The desktop-first React prototype runs entirely in mock mode. It does not call either engine or any external media service.

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

Run both services:

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

The source stage uses yt-dlp, Pillow, FFmpeg, and ffprobe. Hook, Review, and Composer stages still use deterministic local adapters; neither engine submodule is executed. See [docs/BACKEND_ARCHITECTURE.md](docs/BACKEND_ARCHITECTURE.md) and [docs/API_CONTRACT.md](docs/API_CONTRACT.md).
## Real source ingestion

Install dependencies through `setup.ps1` or `setup.sh`. FFmpeg and ffprobe must be available on `PATH`, or configured through `FFMPEG_PATH` and `FFPROBE_PATH`.

The backend accepts one standard YouTube or `youtu.be` URL, downloads at most 1080p without upscaling, and writes `source.mp4`, `thumbnail.jpg`, and `metadata.json` into the isolated job workspace.

Manual real-download smoke test:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

See [docs/SOURCE_INGESTOR.md](docs/SOURCE_INGESTOR.md). Default tests mock yt-dlp and never download real media.
