import json
import sys
from pathlib import Path
from threading import Event
from typing import Any

import pytest
from PIL import Image

from apps.orchestrator.adapters import JobCancelled
from apps.orchestrator.models import is_youtube_url
from apps.orchestrator.source_ingestor import (
    ProbeResult,
    RealSourceIngestor,
    SourceIngestorConfig,
    SourceIngestorError,
    parse_ffprobe,
)


PROBE = ProbeResult(
    duration_seconds=61.5,
    width=1280,
    height=720,
    fps=30,
    video_codec="h264",
    audio_codec="aac",
)


class FakeYDL:
    def __init__(self, options: dict[str, Any], error: Exception | None = None) -> None:
        self.options = options
        self.error = error

    def __enter__(self) -> "FakeYDL":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def extract_info(self, url: str, download: bool) -> dict[str, Any]:
        output = Path(self.options["outtmpl"].replace("%(ext)s", "mp4"))
        output.write_bytes(b"mock video")
        Image.new("RGB", (640, 360), "#553399").save(output.with_suffix(".webp"), format="WEBP")
        self.options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
        if self.error:
            raise self.error
        return {
            "id": "abc123",
            "title": "Real source fixture",
            "channel": "Fixture Channel",
            "duration": 61.5,
            "upload_date": "20260804",
            "webpage_url": url,
        }


def config(**overrides: Any) -> SourceIngestorConfig:
    values = {
        "ffmpeg_path": sys.executable,
        "ffprobe_path": sys.executable,
        "download_timeout_seconds": 30,
    }
    values.update(overrides)
    return SourceIngestorConfig(**values)


def workspace(tmp_path: Path) -> Path:
    (tmp_path / "source").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "url",
    ["https://www.youtube.com/watch?v=abc123", "https://youtu.be/abc123"],
)
def test_accepts_youtube_urls(url: str) -> None:
    assert is_youtube_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/watch?v=abc123",
        "https://youtube.com/playlist?list=PL123",
        "https://youtu.be/abc123?list=PL123",
    ],
)
def test_rejects_non_youtube_and_playlist_urls(url: str) -> None:
    assert not is_youtube_url(url)


def test_deterministic_paths_thumbnail_and_metadata(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    ingestor = RealSourceIngestor(
        config(),
        ydl_factory=lambda options: FakeYDL(options),
        probe_runner=lambda _path: PROBE,
    )

    result = ingestor.download("https://youtu.be/abc123", "a" * 32, root, Event(), lambda *_: None)
    result = ingestor.prepare_thumbnail(result, "a" * 32, root, Event(), lambda *_: None)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))

    assert result.source_video_path == root / "source" / "source.mp4"
    assert result.thumbnail_path == root / "source" / "thumbnail.jpg"
    assert result.metadata_path == root / "source" / "metadata.json"
    assert metadata["source_video_path"] == "source/source.mp4"
    assert metadata["thumbnail_path"] == "source/thumbnail.jpg"
    assert metadata["youtube_video_id"] == "abc123"
    with Image.open(result.thumbnail_path) as thumbnail:
        assert thumbnail.format == "JPEG"
        assert thumbnail.size == (640, 360)


def test_parses_ffprobe_validation_data() -> None:
    result = parse_ffprobe({
        "format": {"duration": "12.5"},
        "streams": [
            {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "avg_frame_rate": "30000/1001"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    })
    assert result.width == 1920
    assert result.height == 1080
    assert result.fps == pytest.approx(29.97, rel=0.001)
    assert result.audio_codec == "aac"


def test_rejects_invalid_ffprobe_data() -> None:
    with pytest.raises(SourceIngestorError, match="không hợp lệ"):
        parse_ffprobe({"format": {"duration": "0"}, "streams": []})


def test_cancellation_cleans_partial_files(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    cancel = Event()

    class CancellingYDL(FakeYDL):
        def extract_info(self, url: str, download: bool) -> dict[str, Any]:
            partial = root / "source" / "source.mp4.part"
            partial.write_bytes(b"partial")
            cancel.set()
            self.options["progress_hooks"][0]({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2})
            return {}

    ingestor = RealSourceIngestor(config(), ydl_factory=lambda options: CancellingYDL(options), probe_runner=lambda _: PROBE)
    with pytest.raises(JobCancelled):
        ingestor.download("https://youtu.be/abc123", "a" * 32, root, cancel, lambda *_: None)
    assert not list((root / "source").glob("*.part"))


def test_missing_ffmpeg_is_user_safe(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    ingestor = RealSourceIngestor(config(ffmpeg_path="missing-ffmpeg-for-test"), ydl_factory=lambda options: FakeYDL(options))
    with pytest.raises(SourceIngestorError) as captured:
        ingestor.download("https://youtu.be/abc123", "a" * 32, root, Event(), lambda *_: None)
    assert captured.value.code == "FFMPEG_MISSING"


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("Private video", "PRIVATE_VIDEO"),
        ("Video unavailable", "VIDEO_UNAVAILABLE"),
        ("Sign in to confirm your age", "AUTH_REQUIRED"),
        ("Network timed out", "NETWORK_ERROR"),
        ("generic yt-dlp failure", "DOWNLOAD_FAILED"),
    ],
)
def test_maps_yt_dlp_failures_and_cleans_outputs(tmp_path: Path, message: str, code: str) -> None:
    root = workspace(tmp_path)
    ingestor = RealSourceIngestor(
        config(),
        ydl_factory=lambda options: FakeYDL(options, RuntimeError(message)),
        probe_runner=lambda _: PROBE,
    )
    with pytest.raises(SourceIngestorError) as captured:
        ingestor.download("https://youtu.be/abc123", "a" * 32, root, Event(), lambda *_: None)
    assert captured.value.code == code
    assert not list((root / "source").glob("source.*"))
