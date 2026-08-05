import json
import shutil
import subprocess
from pathlib import Path
from threading import Event

import pytest
from PIL import Image

from apps.orchestrator.adapters import JobCancelled
from apps.orchestrator.final_composer import FinalComposer, FinalComposerConfig, FinalComposerError
from apps.orchestrator.source_ingestor import ProbeResult


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG or not FFPROBE, reason="FFmpeg is required")


def make_clip(path: Path, color: str, size: str = "320x240", duration: float = 0.4) -> None:
    subprocess.run([
        FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={size}:r=30:d={duration}",
        "-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={duration}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True)


def workspace(tmp_path: Path, review_size: str = "320x240") -> Path:
    for folder in ("hook", "review", "final"):
        (tmp_path / folder).mkdir()
    make_clip(tmp_path / "hook" / "final_hook.mp4", "red")
    make_clip(tmp_path / "review" / "review.mp4", "blue", review_size)
    return tmp_path


def composer() -> FinalComposer:
    return FinalComposer(FinalComposerConfig(FFMPEG or "ffmpeg", FFPROBE or "ffprobe", 30))


def test_stream_copy_keeps_hook_before_review_and_writes_contract(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    adapter = composer()
    adapter.compose(root, Event(), lambda *_: None)
    adapter.validate(root, Event(), lambda *_: None)

    report = json.loads((root / "final" / "compose_report.json").read_text(encoding="utf-8"))
    metadata = json.loads((root / "final" / "metadata.json").read_text(encoding="utf-8"))
    assert report["strategy"] == "stream_copy"
    assert metadata["duration_seconds"] == pytest.approx(0.8, abs=0.15)
    assert metadata["final_video_path"] == "final/final_video.mp4"

    frames = root / "frames"
    frames.mkdir()
    for name, timestamp in (("hook", "0.1"), ("review", "0.6")):
        subprocess.run([FFMPEG, "-y", "-v", "error", "-ss", timestamp, "-i", str(root / "final" / "final_video.mp4"), "-frames:v", "1", str(frames / f"{name}.png")], check=True)
    hook_pixel = Image.open(frames / "hook.png").getpixel((10, 10))
    review_pixel = Image.open(frames / "review.png").getpixel((10, 10))
    assert hook_pixel[0] > hook_pixel[2]
    assert review_pixel[2] > review_pixel[0]


def test_codec_mismatch_falls_back_to_1080p_reencode(tmp_path: Path) -> None:
    root = workspace(tmp_path, "640x360")
    adapter = composer()
    adapter.compose(root, Event(), lambda *_: None)
    adapter.validate(root, Event(), lambda *_: None)

    report = json.loads((root / "final" / "compose_report.json").read_text(encoding="utf-8"))
    metadata = json.loads((root / "final" / "metadata.json").read_text(encoding="utf-8"))
    assert report["strategy"] == "reencode"
    assert report["fallback_reason"] == "CODEC_MISMATCH"
    assert (metadata["width"], metadata["height"], round(metadata["fps"])) == (1920, 1080, 30)


@pytest.mark.parametrize(("missing", "code"), (("hook", "MISSING_HOOK"), ("review", "MISSING_REVIEW")))
def test_missing_upstream_video_is_structured(tmp_path: Path, missing: str, code: str) -> None:
    root = workspace(tmp_path)
    target = root / missing / ("final_hook.mp4" if missing == "hook" else "review.mp4")
    target.unlink()
    with pytest.raises(FinalComposerError, match="video") as caught:
        composer().compose(root, Event(), lambda *_: None)
    assert caught.value.code == code


def test_missing_ffmpeg_is_structured(tmp_path: Path) -> None:
    root = workspace(tmp_path)
    adapter = FinalComposer(FinalComposerConfig("definitely-missing-ffmpeg", FFPROBE or "ffprobe", 30))
    with pytest.raises(FinalComposerError) as caught:
        adapter.compose(root, Event(), lambda *_: None)
    assert caught.value.code == "FFMPEG_MISSING"


def test_cancel_terminates_running_ffmpeg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class Process:
        returncode = None
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, _timeout):
            self.returncode = -1

        def kill(self):
            self.returncode = -9

    process = Process()
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: process)
    cancel = Event()
    cancel.set()
    with pytest.raises(JobCancelled):
        composer()._run_ffmpeg(["ffmpeg"], tmp_path / "composer.log", tmp_path / "progress.log", 1, cancel, lambda *_: None)
    assert process.terminated


def test_invalid_output_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = workspace(tmp_path)
    adapter = composer()
    valid = ProbeResult(duration_seconds=0.4, width=320, height=240, fps=30, video_codec="h264", audio_codec="aac")
    monkeypatch.setattr(adapter, "_probe", lambda path: valid if path.name in {"final_hook.mp4", "review.mp4"} else (_ for _ in ()).throw(FinalComposerError("INVALID_OUTPUT", "Video không hợp lệ.")))
    monkeypatch.setattr(adapter, "_run_ffmpeg", lambda command, *_: Path(command[-1]).write_bytes(b"bad"))
    with pytest.raises(FinalComposerError) as caught:
        adapter.compose(root, Event(), lambda *_: None)
    assert caught.value.code == "INVALID_OUTPUT"


def test_concat_failure_falls_back_to_reencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = workspace(tmp_path)
    adapter = composer()
    real_run = adapter._run_ffmpeg
    calls = 0

    def fail_once(command, *args):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FinalComposerError("CONCAT_FAILURE", "FFmpeg không thể ghép video.")
        return real_run(command, *args)

    monkeypatch.setattr(adapter, "_run_ffmpeg", fail_once)
    adapter.compose(root, Event(), lambda *_: None)
    report = json.loads((root / "final" / "compose_report.json").read_text(encoding="utf-8"))
    assert report["strategy"] == "reencode"
    assert report["fallback_reason"] == "CONCAT_FAILURE"
    assert [attempt["status"] for attempt in report["attempts"]] == ["failed", "completed"]


def test_disk_full_is_not_hidden_by_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = workspace(tmp_path)
    adapter = composer()
    monkeypatch.setattr(adapter, "_run_ffmpeg", lambda *_: (_ for _ in ()).throw(FinalComposerError("DISK_FULL", "Không đủ dung lượng.")))
    with pytest.raises(FinalComposerError) as caught:
        adapter.compose(root, Event(), lambda *_: None)
    assert caught.value.code == "DISK_FULL"
