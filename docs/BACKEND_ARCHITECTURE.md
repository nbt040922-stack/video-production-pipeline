# Backend Architecture

## Stack

The local backend uses Python 3.11+, FastAPI, Pydantic, and Uvicorn. Jobs run in daemon threads inside one backend process. An `RLock` protects shared state; no database or external queue is used.

## Request flow

```text
React UI
  -> BackendPipelineClient
  -> FastAPI job API
  -> JobManager
  -> real source ingestor + deterministic engine stubs
  -> isolated workspace + atomic job.json + pipeline.log
```

## Job state machine

```text
queued -> validating -> downloading -> processing
       -> composing -> validating_output -> completed

Any active state -> cancelled
Any worker error -> failed
failed -> retry creates a new queued job
```

Retry never mutates the failed job. It creates a new job with a new `job_id`, increments `attempt`, and records `retry_of`. The controlled `fixture=fail` fails only the first attempt so retry can exercise a successful recovery.

## Stage model

Every job contains nine ordered stages. Each stage stores status, integer progress, timestamps, elapsed seconds, user-safe message, and structured error data. Stage statuses are `pending`, `running`, `completed`, `failed`, `skipped`, and `cancelled`.

## Workspace

```text
workspace/<job_id>/
├── source/
├── hook/
├── review/
├── final/
├── metadata/job.json
└── logs/pipeline.log
```

Job IDs are 32 lowercase hexadecimal UUID values. Directory creation rejects collisions. Metadata is written to `job.json.tmp` and atomically replaced. Artifacts remain after failure or cancellation. Runtime workspace content is ignored by Git.

## Cancellation

Each active job owns a `threading.Event`. Cancellation sets the event, marks unfinished stages cancelled, persists metadata, and returns immediately. Source and stub adapters check the event during work.

## Startup recovery

`JobManager` loads persisted jobs at startup. Jobs found in non-terminal states become `failed` with error code `INTERRUPTED`. Corrupted metadata remains untouched and returns a structured `CORRUPTED_JOB_METADATA` error.

## Pipeline adapters

The backend defines `SourceIngestor`, `HookEngineAdapter`, `ReviewEngineAdapter`, and `FinalComposer` protocols. Source ingestion uses yt-dlp, Pillow, FFmpeg, and ffprobe. Remaining adapters report backend-owned progress and write small harmless placeholder artifacts.

Future real Hook, Review, and Composer adapters replace those three constructor dependencies. Engine submodules remain untouched and hidden behind adapter boundaries.

## Frontend mode

Mock mode remains default:

```text
VITE_PIPELINE_MODE=mock
```

Backend mode:

```text
VITE_PIPELINE_MODE=backend
VITE_API_BASE_URL=http://127.0.0.1:8000
```

Only `http://127.0.0.1:5173` is allowed by default through CORS. Override `FRONTEND_ORIGIN` when intentionally using another local origin.
