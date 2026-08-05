# Final Composer

`FinalComposer` is the last local backend stage. It reads only the completed upstream artifacts and never modifies them:

```text
hook/final_hook.mp4
          +
review/review.mp4
          ↓
FFmpeg FinalComposer
          ↓
final/final_video.mp4
```

## Strategy

Both inputs are validated with ffprobe before composition. When video codec, audio codec, resolution, and frame rate match, FFmpeg concat demuxer joins Hook first and Review second with stream copy. This preserves quality and avoids a second encode.

When those properties differ, or stream-copy concat produces an invalid file, Composer retries once with H.264/AAC, 1920×1080, 30 FPS, stereo 48 kHz output. Video is scaled and padded without changing aspect ratio. Final duration must be within 3% or one second of the sum of both inputs.

## Workspace contract

```text
workspace/<job_id>/final/
├── final_video.mp4
├── metadata.json
├── compose_report.json
├── composer.log
└── ffmpeg-progress.log
```

`metadata.json` contains the validated duration, resolution, frame rate, codecs, size, relative path, and selected strategy. `compose_report.json` records input probes, concat attempts, fallback reason, and output probe. Logs remain available after failure or cancellation. Temporary rendering and concat-list files are removed after success.

## Progress and cancellation

FFmpeg writes machine-readable render time to `ffmpeg-progress.log`; the existing Compose card receives progress calculated from the combined input duration. Cancellation terminates the active FFmpeg process and leaves Hook, Review, and diagnostic logs untouched. The job becomes complete only after the Validate stage accepts the final file.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg command or absolute executable path |
| `FFPROBE_PATH` | `ffprobe` | ffprobe command or absolute executable path |
| `FINAL_COMPOSER_TIMEOUT_SECONDS` | `3600` | Maximum duration of one FFmpeg attempt |

## Errors

Composer exposes structured codes including `MISSING_HOOK`, `MISSING_REVIEW`, `FFMPEG_MISSING`, `FFPROBE_MISSING`, `CONCAT_FAILURE`, `CODEC_MISMATCH`, `INVALID_OUTPUT`, `DISK_FULL`, and `COMPOSER_TIMEOUT`. `JOB_CANCELLED` remains the pipeline-level cancellation code.

## Manual smoke test

Use a completed workspace that already contains real Hook and Review videos:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_composer.py "workspace\<job_id>"
```

Then open `workspace/<job_id>/final/final_video.mp4` or use the final preview in the frontend.
