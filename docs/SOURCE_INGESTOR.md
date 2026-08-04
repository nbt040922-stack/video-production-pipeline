# Source Ingestor

## Flow

`RealSourceIngestor` validates one YouTube URL, downloads one video and its best thumbnail with yt-dlp, validates `source.mp4` with ffprobe, normalizes the thumbnail with Pillow, and atomically writes `metadata.json`.

```text
YouTube URL
  -> URL and dependency checks
  -> yt-dlp download + progress hook
  -> FFmpeg merge/remux to source.mp4
  -> ffprobe validation
  -> Pillow JPEG normalization
  -> atomic metadata.json
```

## Format strategy

yt-dlp receives this preference order:

```text
bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]
best[height<=1080][ext=mp4]
best[height<=1080]
```

The maximum height defaults to 1080 and is configurable. Lower-resolution sources remain unchanged; the ingestor never upscales. Separate streams are merged and non-MP4 fallbacks are remuxed to MP4 through FFmpeg. Playlists, subtitles, comments, and multiple downloads are disabled.

## Workspace outputs

```text
workspace/<job_id>/source/
├── source.mp4
├── thumbnail.jpg
└── metadata.json
```

yt-dlp temporary files use the same isolated source directory. Partial files are removed after cancellation or download failure. A validated `source.mp4` is preserved if later thumbnail processing fails.

## Metadata schema

`metadata.json` uses schema version 1 and stores:

- job and YouTube video IDs;
- original URL, title, channel, duration, and upload date;
- workspace-relative video and thumbnail paths;
- width, height, FPS, video/audio codecs, and file size;
- download timestamp;
- yt-dlp and FFmpeg versions.

The file is written to `metadata.json.tmp` and atomically replaced.

## Validation

ffprobe must report a readable video stream, positive duration, positive dimensions, and positive FPS. Audio is recorded when present but is not mandatory. Pillow must decode the thumbnail and report positive dimensions. PNG, WebP, and JPEG inputs are converted to `thumbnail.jpg` without cropping or resizing.

## Cancellation

The job's `threading.Event` is checked before download and by yt-dlp progress hooks. Raising `JobCancelled` aborts yt-dlp and prevents later stages. Partial `.part`, `.ytdl`, temporary, and ambiguous source files are removed. yt-dlp-owned FFmpeg postprocessing can only be interrupted at its hook boundaries in Python API mode.

## Error mapping

Private, unavailable, deleted, age-restricted, authentication-required, network, timeout, missing dependency, merge, thumbnail, ffprobe, and write failures map to user-safe Vietnamese errors. Technical exceptions and tracebacks remain in `pipeline.log`.

## Configuration

| Environment variable | Default | Meaning |
|---|---:|---|
| `PIPELINE_WORKSPACE` | `workspace` | Job workspace root |
| `SOURCE_MAX_DURATION_SECONDS` | `0` | Maximum duration; `0` disables limit |
| `SOURCE_DOWNLOAD_TIMEOUT_SECONDS` | `1800` | Download timeout |
| `SOURCE_MAX_HEIGHT` | `1080` | Preferred maximum source height |
| `YTDLP_MODE` | `python` | Supported yt-dlp execution mode |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg command or absolute path |
| `FFPROBE_PATH` | `ffprobe` | ffprobe command or absolute path |

## Thumbnail API

`GET /api/jobs/{job_id}/assets/thumbnail` returns only the validated JPEG for that job. No generic filesystem endpoint exists.

## Manual smoke test

This command performs a real network download and is intentionally excluded from pytest:

```bash
.venv/bin/python scripts/smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

Windows:

```powershell
.\.venv\Scripts\python.exe scripts\smoke_source.py "https://www.youtube.com/watch?v=VIDEO_ID"
```
