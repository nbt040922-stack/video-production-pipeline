# Hook Engine Adapter

Milestone M04 replaces only the Hook stub. Source ingestion is real; Review and Composer remain deterministic stubs.

## Black-box contract

The adapter uses the Hook Engine CLI in `main.py`; it does not import or duplicate engine logic.

```text
thumbnail.jpg
  -> main.py generate
  -> raw_candidate.mp4
  -> main.py phase4
  -> final_hook.mp4
```

Inspected engine requirements:

- Python 3.11+, CUDA-enabled PyTorch, FFmpeg, and ffprobe;
- a running ComfyUI server, normally `http://127.0.0.1:8188`;
- local ComfyUI/Wan workflow/checkpoint and DWPose resources;
- one approved `motion_library/**/metadata.json` matching `HOOK_MOTION_ID`;
- no model download or fallback during runtime;
- `OPENAI_API_KEY` is not needed because M04 passes the validated thumbnail directly to `generate` and does not use `phase1 --reconstruct`.

## Adapter flow

1. `prepare()` requires the exact job asset `source/thumbnail.jpg`, verifies JPEG readability with Pillow, checks the CLI/runtime, and creates isolated temporary directories.
2. `run()` invokes `generate` with argument arrays and `shell=False`.
3. The CLI output identifies the engine job and its `raw_candidate.mp4`.
4. `run()` invokes `phase4` for the same raw candidate.
5. The adapter moves the engine result to `hook/final_hook.mp4`.
6. ffprobe verifies readability, positive resolution, and a duration within `HOOK_DURATION_TOLERANCE_SECONDS` of five seconds.
7. The adapter atomically writes `hook/metadata.json`.
8. `cleanup()` removes adapter-owned intermediate directories. Failed or cancelled outputs are removed.

`status()` exposes adapter state, progress, and message. `cancel()` interrupts ComfyUI and terminates the active CLI process tree.

## Configuration

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

The tracked submodule contains engine code. Local ComfyUI models and motion assets are intentionally ignored by the engine repository. Point `HOOK_ENGINE_PATH` at a complete local Hook Engine runtime when those assets are installed elsewhere.

## Workspace output

```text
workspace/<job_id>/hook/
├── final_hook.mp4
└── metadata.json
```

Metadata contains parent job ID, engine job ID, motion ID, relative input/output paths, duration, resolution, FPS, and codecs.

## API and UI

`GET /api/jobs/{job_id}/assets/hook` returns `video/mp4` only after the Hook stage completes. Polling job data includes real Hook progress, message, elapsed time, and `preview_url`. The existing Hook card renders that URL with native video controls.

## Manual smoke test

The parent development script starts Hook ComfyUI automatically and waits for `/system_stats` readiness. On Windows, configure the existing standalone runtime before starting the parent:

```powershell
$env:HOOK_ENGINE_PATH='D:\AI_hook_engine'
$env:HOOK_ENGINE_PYTHON='D:\AI_hook_engine\ComfyUI\.venv\Scripts\python.exe'
$env:HOOK_MOTION_ID='motion1'
.\.venv\Scripts\python.exe scripts\smoke_hook.py "C:\path\to\thumbnail.jpg"
```

This is opt-in. Automated tests use a fake CLI runner and never start ComfyUI, use the GPU, or generate a real video.

## Error codes

- `HOOK_THUMBNAIL_MISSING`, `HOOK_THUMBNAIL_INVALID`
- `HOOK_ENGINE_NOT_READY`, `HOOK_ENGINE_FAILED`, `HOOK_TIMEOUT`
- `HOOK_OUTPUT_MISSING`, `HOOK_OUTPUT_INVALID`
- pipeline cancellation remains `JOB_CANCELLED`
