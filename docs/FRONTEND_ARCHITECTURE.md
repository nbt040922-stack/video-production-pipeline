# Frontend Architecture

## Stack

The prototype uses React, TypeScript, Vite, Vitest, Testing Library, and plain CSS. It runs as a browser application and can later be wrapped by Electron or Tauri without changing the UI architecture.

## Screen structure

The desktop shell has a compact sidebar, top status bar, and one primary workspace. `Video mới` contains the complete workflow. `Công việc`, `Đầu ra`, and `Cài đặt` are lightweight placeholders.

The primary screen contains:

1. YouTube URL form and validation.
2. Mock source preview.
3. Nine-stage pipeline progress.
4. Parallel Hook Engine and Review Engine status cards.
5. Completed output preview and actions.

## Component hierarchy

```text
App
└── AppShell
    ├── Create video form
    ├── SourcePreview
    ├── PipelineProgress
    ├── EngineCards
    └── FinalOutput
```

`App` owns navigation, URL input, source metadata, and active-job presentation. `useVideoJob` owns job polling and actions. Presentational components receive typed props and contain no mock timers.

## State model

Active state remains in React:

- selected page;
- URL and validation state;
- source metadata;
- active `VideoJob`;
- transient notices.

Job states are `validating`, `processing`, `completed`, `failed`, and `cancelled`. Stage and engine states are `pending`, `running`, `completed`, `failed`, and `skipped`.

Local storage is intentionally omitted. Add it only when job persistence across reloads becomes a product requirement.

## PipelineClient contract

```ts
interface PipelineClient {
  inspectSource(youtubeUrl: string): Promise<SourceMetadata>
  createJob(input: CreateVideoInput): Promise<CreateJobResult>
  getJob(jobId: string): Promise<VideoJob>
  cancelJob(jobId: string): Promise<void>
}
```

UI code receives this interface. It does not import engine modules, call Python, run FFmpeg, or contact YouTube.

## Mock mode

`MockPipelineClient` stores jobs in memory. A deterministic timer advances one stage per tick and returns cloned snapshots through `getJob`. It supports completion and cancellation.

Development failure fixture:

```text
https://youtu.be/mock-video?fixture=fail
```

This URL fails at the review-writing stage. Retry creates a fresh mock job; reset clears active UI state.

## Future backend integration

Replace the `MockPipelineClient` instance passed to `App` with an HTTP, Electron IPC, or Tauri command adapter implementing `PipelineClient`.

Exact integration points:

- `inspectSource`: downloader metadata endpoint;
- `createJob`: orchestrator job creation endpoint;
- `getJob`: job status polling endpoint;
- `cancelJob`: orchestrator cancellation endpoint;
- `Open Output Folder`: desktop shell API after Electron/Tauri packaging.

Engine-specific details remain behind the orchestrator. Components and job types should not import either submodule.
