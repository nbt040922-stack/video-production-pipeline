# Review Engine Adapter

## Integration method

`ReviewEngineAdapter` wraps the Review Engine's supported headless CLI:

```text
review_cli.py run --progress-jsonl
```

The adapter passes the parent's existing `source/source.mp4`; the engine downloader is therefore not invoked. Engine logic remains inside the independently versioned submodule.

## Lifecycle

- `prepare()` validates paths, source metadata, credentials, voice reference, Python, FFmpeg, and ffprobe before paid work.
- `run()` starts one isolated CLI subprocess, consumes JSONL events, collects artifacts, and validates results.
- `status()` returns adapter status without secrets.
- `cancel()` signals the CLI so its runner can execute local and remote cleanup; forced process-tree termination is a last resort.
- `cleanup()` removes only adapter-owned temporary files. Source, Hook, completed Review artifacts, and logs remain.

## Configuration

| Variable | Purpose |
|---|---|
| `REVIEW_ENGINE_PATH` | Review Engine checkout containing `review_cli.py` |
| `REVIEW_ENGINE_PYTHON` | Python runtime with Review Engine dependencies |
| `REVIEW_ENGINE_TIMEOUT_SECONDS` | Whole Review run timeout; default `14400` |
| `REVIEW_VOICE_REFERENCE_PATH` | Reference voice file; defaults to `<REVIEW_ENGINE_PATH>/voice.wav` when present |
| `REVIEW_VOICE_REFERENCE_TEXT` | Optional exact transcript for the reference voice |
| `GEMINI_API_KEY` | Gemini credential |
| `TWELVE_LABS_API_KEY` | Twelve Labs credential |
| `TWELVE_API_KEY` | Compatibility alias when the canonical variable is absent |
| `USE_PROXY_VIDEO` | Enables Event Window proxy selection; default `true` |
| `FFMPEG_PATH`, `FFPROBE_PATH` | Media tool overrides |

OmniVoice remains managed by the Review Engine's `.venv-omnivoice`. Run its documented installer once. Real credentials must never be committed.

## Input and output

Input: job ID, original YouTube URL, `source/source.mp4`, `source/metadata.json`, and isolated parent workspace.

Stable output:

```text
workspace/<job_id>/review/
├── review.mp4
├── metadata.json
├── proxy_metrics.json
├── window_mapping.json
├── script/review.json       # when produced
├── voice/voice.wav          # when produced
├── timeline/timeline.json   # when produced
└── logs/engine.jsonl
```

`metadata.json` is normalized to parent-relative paths and actual ffprobe values. Engine temporary paths are never exposed as the parent contract.

## Progress mapping

| Engine JSONL stages | Parent/UI stage |
|---|---|
| `preparing`, `writing_review` | Writing review |
| `generating_voice`, `transcribing` | Generating voice |
| `selecting_windows`, `indexing_proxy`, `searching_scenes`, `mapping_timeline` | Selecting footage |
| `rendering_review`, `validating_output` | Rendering review |

Progress comes only from CLI JSONL events. No frontend timer estimates Review progress.

## Validation

The adapter independently checks a readable, non-empty video with video and audio streams, positive duration/resolution/FPS, codecs, finite proxy metrics, fallback consistency, zero mapping errors on successful proxy runs, ordered source/proxy windows, and mapping duration tolerance. A valid full-source fallback with 0% savings is accepted and recorded.

## Cancellation, timeout, and recovery

Cancellation and timeout first signal the CLI, allowing the engine's `finally` cleanup to request deletion of its temporary Twelve index. If the child does not exit within ten seconds, the process tree is terminated. Logs and completed artifacts remain; remote cleanup is not claimed unless the engine reports it.

Restart recovery marks an in-progress persisted job `INTERRUPTED`; it never reruns paid work automatically.

## Error mapping

The parent exposes Vietnamese messages with stable codes: `REVIEW_ENGINE_NOT_CONFIGURED`, `REVIEW_ENGINE_ENTRYPOINT_MISSING`, `REVIEW_ENGINE_CREDENTIALS_MISSING`, `REVIEW_ENGINE_TIMEOUT`, `GEMINI_FAILED`, `OMNIVOICE_FAILED`, `TWELVE_INDEX_FAILED`, `MARENGO_SEARCH_FAILED`, `PROXY_MAPPING_FAILED`, `REVIEW_RENDER_FAILED`, `REVIEW_OUTPUT_INVALID`, and `REVIEW_CANCELLED`. Technical JSONL stays under `review/logs/`; credentials are never logged or returned.

## Manual real job

This calls paid external services. Confirm Gemini and Twelve Labs pricing/quota first.

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

Paste one YouTube URL in the existing UI. After completion, inspect `workspace/<job_id>/review/metadata.json` and `proxy_metrics.json` for source duration, proxy duration, savings, fallback, runtime, video duration, mapping errors, and final status.

Default tests use a fake local CLI and never call paid services. No automatic paid-service retry is added by the parent.
