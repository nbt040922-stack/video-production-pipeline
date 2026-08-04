# Architecture

## Pipeline

```text
YouTube URL
    |
    v
Source Ingestor
    |
    v
thumbnail.jpg
    |
    v
HookEngineAdapter
    |
    v
Hook Engine CLI (generate + phase4)
    |
    v
hook/final_hook.mp4
    |
    v
Review Engine stub -> Composer stub -> Final Video
```

## Component boundaries

### Source Ingestor

The parent orchestrator validates one YouTube URL and writes `source/source.mp4`, `source/thumbnail.jpg`, and `source/metadata.json` inside an isolated job workspace.

### HookEngineAdapter

The parent owns workspace preparation, CLI process control, progress, cancellation, cleanup, output collection, and ffprobe validation. It calls the Hook Engine's public CLI and never imports or duplicates engine logic.

### Hook Engine

The independently versioned `engines/hook-engine` submodule remains a black box. Its `generate` command creates a raw candidate; `phase4` produces the five-second `final_hook.mp4`.

### Review Engine

The `engines/review-engine` submodule remains untouched. M04 still uses the parent Review stub.

### Composer

Composer remains a stub that preserves the existing end-to-end job flow. Real composition is outside M04.

### Orchestrator

`apps.orchestrator` coordinates stages, job state, isolated paths, persistence, structured failures, cancellation, and asset endpoints.

## Workspace contract

```text
workspace/<job_id>/
├── source/thumbnail.jpg
├── hook/final_hook.mp4
├── hook/metadata.json
├── review/
├── final/
├── metadata/job.json
└── logs/pipeline.log
```

Runtime artifacts stay outside version control. The parent never writes into either engine repository.

## Versioning

Each submodule entry pins an exact engine commit. Updating an engine remains an explicit parent-repository change, preserving independent history and releases.