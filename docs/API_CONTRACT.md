# Local Job API Contract

Base URL: `http://127.0.0.1:8000`

## Health

`GET /api/health`

Returns backend mode, workspace location, and readiness for real Source, Hook, Review, and Final Composer dependencies. Credential values are never returned.

## Create job

`POST /api/jobs`

```json
{
  "youtube_url": "https://www.youtube.com/watch?v=demo123"
}
```

Returns HTTP 201 with the complete queued job, including `job_id`, status, timestamps, stages, and engine states.

## Read job

`GET /api/jobs/{job_id}`

Returns current persisted job state:

- overall status and progress percentage;
- current stage;
- nine detailed stages;
- timestamps and elapsed time;
- source metadata;
- Hook and Review adapter states;
- structured error;
- final output metadata.

## Source thumbnail

`GET /api/jobs/{job_id}/assets/thumbnail`

Returns the validated `image/jpeg` thumbnail for one job. Missing or unknown assets return structured errors. The endpoint cannot read arbitrary paths.
## Hook preview

`GET /api/jobs/{job_id}/assets/hook`

Returns validated `video/mp4` only after the Hook stage completes. The endpoint resolves only the known `hook/final_hook.mp4` job asset and cannot read arbitrary paths.

## Review assets

- `GET /api/jobs/{job_id}/assets/review` returns validated `review.mp4`.
- `GET /api/jobs/{job_id}/assets/review-metadata` returns normalized Review metadata.
- `GET /api/jobs/{job_id}/assets/proxy-metrics` returns proxy cost metrics.

These routes resolve fixed files inside one validated job workspace. They do not accept arbitrary filesystem paths.

## Final video

- `GET /api/jobs/{job_id}/assets/final` streams the validated `final_video.mp4` only after the job completes.
- `POST /api/jobs/{job_id}/open-folder` opens that job's local `final/` directory on the backend desktop.

Both routes resolve a fixed path inside the validated job workspace and reject incomplete or unknown jobs.

## Cancel job

`POST /api/jobs/{job_id}/cancel`

```json
{
  "job_id": "...",
  "status": "cancelled"
}
```

Cancellation is idempotent for an already-cancelled job. Completed and failed jobs return HTTP 409.

## Retry job

`POST /api/jobs/{job_id}/retry`

Only failed jobs can be retried. Returns HTTP 201 with a new queued job. The original job and artifacts are preserved.

## Errors

Errors never include Python tracebacks:

```json
{
  "error": {
    "code": "INVALID_YOUTUBE_URL",
    "message": "Liên kết YouTube không hợp lệ.",
    "details": null
  }
}
```

Codes include source errors such as `INVALID_YOUTUBE_URL`, `PLAYLIST_NOT_SUPPORTED`, `YTDLP_MISSING`, `FFMPEG_MISSING`, `FFPROBE_FAILED`, `PRIVATE_VIDEO`, `VIDEO_UNAVAILABLE`, `AUTH_REQUIRED`, and `DOWNLOAD_FAILED`; Hook errors such as `HOOK_THUMBNAIL_MISSING`, `HOOK_ENGINE_NOT_READY`, `HOOK_ENGINE_FAILED`, `HOOK_TIMEOUT`, `HOOK_OUTPUT_MISSING`, and `HOOK_OUTPUT_INVALID`; Review errors documented in `REVIEW_ENGINE_ADAPTER.md`; Composer errors documented in `FINAL_COMPOSER.md`; plus `JOB_NOT_FOUND`, `INVALID_JOB_STATE`, `CORRUPTED_JOB_METADATA`, `JOB_CANCELLED`, `INTERRUPTED`, and `WORKER_ERROR`. Full worker tracebacks are written only to the job's `logs/pipeline.log`.

## Controlled failure

Development fixture:

```text
https://youtu.be/demo123?fixture=fail
```

First attempt fails in the Review adapter. Retrying creates a second attempt that completes.
