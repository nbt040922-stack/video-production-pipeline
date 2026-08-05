from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any

from .adapters import JobCancelled, ProgressCallback
from .source_ingestor import ProbeResult, SourceIngestorError, parse_ffprobe


class FinalComposerError(Exception):
    def __init__(self, code: str, message: str, technical: str | None = None) -> None:
        super().__init__(technical or message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class FinalComposerConfig:
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    timeout_seconds: int = 3600

    @classmethod
    def from_env(cls) -> "FinalComposerConfig":
        return cls(
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            timeout_seconds=int(os.getenv("FINAL_COMPOSER_TIMEOUT_SECONDS", "3600")),
        )


class FinalComposer:
    def __init__(self, config: FinalComposerConfig | None = None) -> None:
        self.config = config or FinalComposerConfig.from_env()

    def readiness(self) -> dict[str, str]:
        ffmpeg = self._tool(self.config.ffmpeg_path)
        ffprobe = self._tool(self.config.ffprobe_path)
        return {
            "status": "ready" if ffmpeg and ffprobe else "missing_dependency",
            "ffmpeg": ffmpeg or "missing",
            "ffprobe": ffprobe or "missing",
        }

    def compose(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> Path:
        ffmpeg = self._require_tool(self.config.ffmpeg_path, "FFMPEG_MISSING", "Không tìm thấy FFmpeg.")
        self._require_tool(self.config.ffprobe_path, "FFPROBE_MISSING", "Không tìm thấy ffprobe.")
        hook = workspace / "hook" / "final_hook.mp4"
        review = workspace / "review" / "review.mp4"
        if not hook.is_file():
            raise FinalComposerError("MISSING_HOOK", "Không tìm thấy video Hook để ghép.")
        if not review.is_file():
            raise FinalComposerError("MISSING_REVIEW", "Không tìm thấy video Review để ghép.")

        final_dir = workspace / "final"
        final_dir.mkdir(parents=True, exist_ok=True)
        output = final_dir / "final_video.mp4"
        temporary = final_dir / ".final_video.rendering.mp4"
        concat_file = final_dir / ".concat.txt"
        progress_file = final_dir / "ffmpeg-progress.log"
        log_file = final_dir / "composer.log"
        temporary.unlink(missing_ok=True)
        progress_file.unlink(missing_ok=True)

        progress(5, "Đang kiểm tra video Hook và Review")
        hook_info = self._probe(hook)
        review_info = self._probe(review)
        expected_duration = hook_info.duration_seconds + review_info.duration_seconds
        attempts: list[dict[str, Any]] = []
        strategy = "stream_copy"
        fallback_reason: str | None = None

        if self._compatible(hook_info, review_info):
            concat_file.write_text(
                "\n".join(f"file '{self._concat_path(path)}'" for path in (hook, review)) + "\n",
                encoding="utf-8",
            )
            command = [
                ffmpeg, "-y", "-v", "warning", "-f", "concat", "-safe", "0", "-i", str(concat_file),
                "-c", "copy", "-movflags", "+faststart", "-progress", str(progress_file), str(temporary),
            ]
            try:
                self._run_ffmpeg(command, log_file, progress_file, expected_duration, cancel, progress)
                self._validate_video(temporary, expected_duration)
                attempts.append({"strategy": strategy, "status": "completed"})
            except JobCancelled:
                temporary.unlink(missing_ok=True)
                concat_file.unlink(missing_ok=True)
                raise
            except FinalComposerError as exc:
                if exc.code in {"DISK_FULL", "COMPOSER_TIMEOUT", "FFMPEG_MISSING"}:
                    temporary.unlink(missing_ok=True)
                    concat_file.unlink(missing_ok=True)
                    raise
                attempts.append({"strategy": strategy, "status": "failed", "code": exc.code})
                fallback_reason = exc.code
                temporary.unlink(missing_ok=True)
        else:
            fallback_reason = "CODEC_MISMATCH"

        if fallback_reason:
            strategy = "reencode"
            progress(10, "Thông số video khác nhau, đang chuẩn hóa đầu ra")
            command = [
                ffmpeg, "-y", "-v", "warning", "-i", str(hook), "-i", str(review),
                "-filter_complex",
                "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v0];"
                "[1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1,format=yuv420p[v1];"
                "[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a0];"
                "[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a1];"
                "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]",
                "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-progress", str(progress_file),
                str(temporary),
            ]
            try:
                self._run_ffmpeg(command, log_file, progress_file, expected_duration, cancel, progress)
                self._validate_video(temporary, expected_duration)
                attempts.append({"strategy": strategy, "status": "completed"})
            except JobCancelled:
                temporary.unlink(missing_ok=True)
                concat_file.unlink(missing_ok=True)
                raise
            except FinalComposerError as exc:
                attempts.append({"strategy": strategy, "status": "failed", "code": exc.code})
                temporary.unlink(missing_ok=True)
                concat_file.unlink(missing_ok=True)
                self._write_report(workspace, strategy, fallback_reason, attempts, hook_info, review_info, None)
                if fallback_reason == "CODEC_MISMATCH" and exc.code == "CONCAT_FAILURE":
                    raise FinalComposerError("CODEC_MISMATCH", "Không thể chuẩn hóa codec của video đầu vào.", str(exc)) from exc
                raise

        try:
            os.replace(temporary, output)
        except OSError as exc:
            if exc.errno in {errno.ENOSPC, 112}:
                raise FinalComposerError("DISK_FULL", "Không đủ dung lượng để lưu video cuối.", str(exc)) from exc
            raise
        concat_file.unlink(missing_ok=True)
        progress(95, "Đã ghép xong, đang kiểm tra đầu ra")
        output_info = self._validate_video(output, expected_duration)
        self._write_report(workspace, strategy, fallback_reason, attempts, hook_info, review_info, output_info)
        return output

    def validate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        if cancel.is_set():
            raise JobCancelled
        output = workspace / "final" / "final_video.mp4"
        hook = workspace / "hook" / "final_hook.mp4"
        review = workspace / "review" / "review.mp4"
        if not output.is_file():
            raise FinalComposerError("INVALID_OUTPUT", "Không tìm thấy video cuối.")
        expected = self._probe(hook).duration_seconds + self._probe(review).duration_seconds
        info = self._validate_video(output, expected)
        report_path = workspace / "final" / "compose_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else {}
        metadata = {
            "schema_version": 1,
            "job_id": workspace.name,
            "final_video_path": "final/final_video.mp4",
            "duration_seconds": info.duration_seconds,
            "width": info.width,
            "height": info.height,
            "fps": info.fps,
            "video_codec": info.video_codec,
            "audio_codec": info.audio_codec,
            "file_size_bytes": output.stat().st_size,
            "strategy": report.get("strategy", "unknown"),
        }
        self._write_json(workspace / "final" / "metadata.json", metadata)
        progress(100, "Video cuối hợp lệ")

    def _run_ffmpeg(
        self,
        command: list[str],
        log_path: Path,
        progress_path: Path,
        expected_duration: float,
        cancel: Event,
        progress: ProgressCallback,
    ) -> None:
        started = monotonic()
        try:
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[{self._now()}] {' '.join(command)}\n")
                process = subprocess.Popen(command, stdout=log, stderr=log, text=True, encoding="utf-8", errors="replace")
                while process.poll() is None:
                    if cancel.is_set():
                        process.terminate()
                        try:
                            process.wait(5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                        raise JobCancelled
                    if monotonic() - started > self.config.timeout_seconds:
                        process.kill()
                        raise FinalComposerError("COMPOSER_TIMEOUT", "Ghép video vượt quá thời gian cho phép.")
                    rendered = self._progress_seconds(progress_path)
                    percent = min(90, 15 + round(75 * rendered / max(expected_duration, 0.1)))
                    progress(percent, f"Đang ghép video cuối: {percent}%")
                    sleep(0.2)
                if process.returncode != 0:
                    technical = log_path.read_text(encoding="utf-8", errors="replace")[-4000:]
                    code = "DISK_FULL" if self._is_disk_full(technical) else "CONCAT_FAILURE"
                    message = "Không đủ dung lượng để ghép video." if code == "DISK_FULL" else "FFmpeg không thể ghép video."
                    raise FinalComposerError(code, message, technical)
        except OSError as exc:
            if exc.errno in {errno.ENOSPC, 112}:
                raise FinalComposerError("DISK_FULL", "Không đủ dung lượng để ghép video.", str(exc)) from exc
            raise FinalComposerError("CONCAT_FAILURE", "Không thể khởi chạy FFmpeg.", str(exc)) from exc

    def _probe(self, path: Path) -> ProbeResult:
        ffprobe = self._require_tool(self.config.ffprobe_path, "FFPROBE_MISSING", "Không tìm thấy ffprobe.")
        completed = subprocess.run(
            [ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if completed.returncode != 0:
            raise FinalComposerError("INVALID_OUTPUT", "Video không đọc được.", completed.stderr)
        try:
            return parse_ffprobe(json.loads(completed.stdout))
        except (json.JSONDecodeError, SourceIngestorError) as exc:
            raise FinalComposerError("INVALID_OUTPUT", "Video không hợp lệ.", str(exc)) from exc

    def _validate_video(self, path: Path, expected_duration: float) -> ProbeResult:
        if not path.is_file() or path.stat().st_size <= 0:
            raise FinalComposerError("INVALID_OUTPUT", "Video cuối không tồn tại hoặc rỗng.")
        info = self._probe(path)
        if not info.audio_codec or abs(info.duration_seconds - expected_duration) > max(1.0, expected_duration * 0.03):
            raise FinalComposerError("INVALID_OUTPUT", "Video cuối thiếu âm thanh hoặc sai thời lượng.")
        return info

    def _write_report(
        self,
        workspace: Path,
        strategy: str,
        fallback_reason: str | None,
        attempts: list[dict[str, Any]],
        hook: ProbeResult,
        review: ProbeResult,
        output: ProbeResult | None,
    ) -> None:
        payload = {
            "schema_version": 1,
            "job_id": workspace.name,
            "status": "completed" if output else "failed",
            "strategy": strategy,
            "fallback_reason": fallback_reason,
            "attempts": attempts,
            "inputs": {"hook": hook.model_dump(), "review": review.model_dump()},
            "output": output.model_dump() if output else None,
            "finished_at": self._now(),
        }
        self._write_json(workspace / "final" / "compose_report.json", payload)

    @staticmethod
    def _compatible(first: ProbeResult, second: ProbeResult) -> bool:
        return (
            first.video_codec == second.video_codec
            and first.audio_codec == second.audio_codec
            and first.audio_codec is not None
            and (first.width, first.height) == (second.width, second.height)
            and abs(first.fps - second.fps) < 0.01
        )

    @staticmethod
    def _concat_path(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "'\\''")

    @staticmethod
    def _progress_seconds(path: Path) -> float:
        try:
            values = dict(line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
            return int(values.get("out_time_us", "0")) / 1_000_000
        except (OSError, ValueError):
            return 0

    @staticmethod
    def _is_disk_full(text: str) -> bool:
        lowered = text.lower()
        return "no space left" in lowered or "not enough space" in lowered or "disk full" in lowered

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _tool(command: str) -> str | None:
        candidate = Path(command)
        return str(candidate.resolve()) if candidate.is_file() else shutil.which(command)

    def _require_tool(self, command: str, code: str, message: str) -> str:
        resolved = self._tool(command)
        if not resolved:
            raise FinalComposerError(code, message)
        return resolved
