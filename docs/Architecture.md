# Architecture

## Pipeline

```text
YouTube URL
    |
    v
Downloader
    |
    v
Hook Engine
    |
    v
Review Engine
    |
    v
Composer
    |
    v
Final Video
```

## Component boundaries

### Downloader

Accepts a YouTube URL and places downloaded source media in `workspace/`. It is a future parent-project component; no downloader is implemented here yet.

### Hook Engine

The `engines/hook-engine` submodule is independently versioned and produces `final_hook.mp4`. The parent treats it as a production-ready module and does not own its internals.

### Review Engine

The `engines/review-engine` submodule is independently versioned and produces `review.mp4`. The parent treats it as a production-ready module and does not own its internals.

### Composer

The `composer` package will consume `final_hook.mp4` and `review.mp4` and produce the final video. This repository currently provides only the package boundary.

### Orchestrator

The future `apps.orchestrator` package will coordinate stage execution, workspace paths, failure handling, and configuration. It will call the engines through their supported command-line or file interfaces rather than importing their internal implementation.

## Workspace contract

All runtime inputs, intermediate artifacts, logs, and outputs belong under `workspace/` and are excluded from version control. Source repositories remain immutable from the parent pipeline's perspective.

## Versioning

Each submodule entry pins an exact engine commit. Updating an engine is an explicit parent-repository change, providing reproducible builds while preserving the complete history and release process of each engine.
