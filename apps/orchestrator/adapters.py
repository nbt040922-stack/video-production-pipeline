from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Callable, Protocol

from PIL import Image

if TYPE_CHECKING:
    from .source_ingestor import SourceResult

ProgressCallback = Callable[[int, str], None]


class JobCancelled(Exception):
    pass


class SourceIngestor(Protocol):
    def download(
        self, youtube_url: str, job_id: str, workspace: Path, cancel: Event, progress: ProgressCallback
    ) -> "SourceResult": ...

    def prepare_thumbnail(
        self, result: "SourceResult", job_id: str, workspace: Path, cancel: Event, progress: ProgressCallback
    ) -> "SourceResult": ...


class HookEngineAdapter(Protocol):
    def generate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


class ReviewEngineAdapter(Protocol):
    def write_review(self, workspace: Path, cancel: Event, progress: ProgressCallback, fail: bool) -> None: ...
    def generate_voice(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...
    def select_footage(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...
    def render(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


class FinalComposer(Protocol):
    def compose(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> Path: ...
    def validate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


def _work(label: str, delay: float, cancel: Event, progress: ProgressCallback) -> None:
    for percent in (25, 65, 100):
        if cancel.wait(delay / 3):
            raise JobCancelled
        progress(percent, f"{label}: {percent}%")


class StubSourceIngestor:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def download(
        self, youtube_url: str, job_id: str, workspace: Path, cancel: Event, progress: ProgressCallback
    ) -> "SourceResult":
        from .source_ingestor import SourceResult

        _work("Đang tải nguồn", self.delay, cancel, progress)
        source = workspace / "source" / "source.mp4"
        thumbnail = workspace / "source" / "source.webp"
        source.write_bytes(b"placeholder source\n")
        Image.new("RGB", (320, 180), "#292b35").save(thumbnail, format="WEBP")
        return SourceResult(
            source_video_path=source,
            thumbnail_path=thumbnail,
            metadata_path=workspace / "source" / "metadata.json",
            youtube_video_id="stub-video",
            title="Bodycam Footage Review — Local Backend",
            channel="Local pipeline fixture",
            duration_seconds=768,
            width=1920,
            height=1080,
            fps=30,
            file_size_bytes=source.stat().st_size,
            original_url=youtube_url,
            video_codec="h264",
            audio_codec="aac",
            downloaded_at=datetime.now(timezone.utc).isoformat(),
            yt_dlp_version="stub",
            ffmpeg_version="stub",
        )

    def prepare_thumbnail(
        self, result: "SourceResult", job_id: str, workspace: Path, cancel: Event, progress: ProgressCallback
    ) -> "SourceResult":
        _work("Đang chuẩn bị ảnh bìa", self.delay, cancel, progress)
        target = workspace / "source" / "thumbnail.jpg"
        with Image.open(result.thumbnail_path) as image:
            image.convert("RGB").save(target, format="JPEG", quality=90)
        result.thumbnail_path.unlink(missing_ok=True)
        result.thumbnail_path = target
        payload = {
            "schema_version": 1,
            "job_id": job_id,
            "youtube_video_id": result.youtube_video_id,
            "original_url": result.original_url,
            "title": result.title,
            "channel": result.channel,
            "duration_seconds": result.duration_seconds,
            "upload_date": result.upload_date,
            "source_video_path": "source/source.mp4",
            "thumbnail_path": "source/thumbnail.jpg",
            "width": result.width,
            "height": result.height,
            "fps": result.fps,
            "video_codec": result.video_codec,
            "audio_codec": result.audio_codec,
            "file_size_bytes": result.file_size_bytes,
            "downloaded_at": result.downloaded_at,
            "yt_dlp_version": result.yt_dlp_version,
            "ffmpeg_version": result.ffmpeg_version,
        }
        temporary = result.metadata_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, result.metadata_path)
        return result


class StubHookEngineAdapter:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def generate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang tạo đoạn mở đầu", self.delay, cancel, progress)
        (workspace / "hook" / "final_hook.mp4").write_bytes(b"placeholder hook\n")


class StubReviewEngineAdapter:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def write_review(self, workspace: Path, cancel: Event, progress: ProgressCallback, fail: bool) -> None:
        _work("Đang viết bài đánh giá", self.delay, cancel, progress)
        if fail:
            raise RuntimeError("Controlled review adapter failure")

    def generate_voice(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang tạo giọng đọc", self.delay, cancel, progress)

    def select_footage(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang chọn cảnh quay", self.delay, cancel, progress)

    def render(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang dựng video đánh giá", self.delay, cancel, progress)
        (workspace / "review" / "review.mp4").write_bytes(b"placeholder review\n")


class StubFinalComposer:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def compose(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> Path:
        _work("Đang ghép video cuối", self.delay, cancel, progress)
        output = workspace / "final" / "final_video.mp4"
        output.write_bytes(b"placeholder final video\n")
        return output

    def validate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang kiểm tra đầu ra", self.delay, cancel, progress)
        if not (workspace / "final" / "final_video.mp4").is_file():
            raise RuntimeError("Final output is missing")
