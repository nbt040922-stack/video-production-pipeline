from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from threading import Event
from time import monotonic, sleep
from typing import Any, Callable, ContextManager

from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel

from .adapters import JobCancelled, ProgressCallback
from .models import is_youtube_url


class SourceIngestorError(Exception):
    def __init__(self, code: str, message: str, technical: str | None = None) -> None:
        super().__init__(technical or message)
        self.code = code
        self.message = message


class ProbeResult(BaseModel):
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None = None


class SourceResult(BaseModel):
    source_video_path: Path
    thumbnail_path: Path
    metadata_path: Path
    youtube_video_id: str
    title: str
    channel: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    file_size_bytes: int
    upload_date: str | None = None
    original_url: str
    video_codec: str
    audio_codec: str | None = None
    downloaded_at: str
    yt_dlp_version: str
    ffmpeg_version: str | None = None


@dataclass(frozen=True)
class SourceIngestorConfig:
    max_duration_seconds: int | None = None
    download_timeout_seconds: int = 1800
    max_height: int = 1080
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    yt_dlp_mode: str = "python"

    @classmethod
    def from_env(cls) -> "SourceIngestorConfig":
        maximum = int(os.getenv("SOURCE_MAX_DURATION_SECONDS", "0"))
        return cls(
            max_duration_seconds=maximum or None,
            download_timeout_seconds=int(os.getenv("SOURCE_DOWNLOAD_TIMEOUT_SECONDS", "1800")),
            max_height=int(os.getenv("SOURCE_MAX_HEIGHT", "1080")),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            yt_dlp_mode=os.getenv("YTDLP_MODE", "python"),
        )


def parse_ffprobe(payload: dict[str, Any]) -> ProbeResult:
    streams = payload.get("streams") or []
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    try:
        duration = float((payload.get("format") or {}).get("duration") or 0)
        width = int((video or {}).get("width") or 0)
        height = int((video or {}).get("height") or 0)
        fps = float(Fraction((video or {}).get("avg_frame_rate") or (video or {}).get("r_frame_rate") or "0/1"))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise SourceIngestorError("FFPROBE_INVALID", "Không thể đọc thông tin video nguồn.", str(exc)) from exc
    if not video or duration <= 0 or width <= 0 or height <= 0 or fps <= 0:
        raise SourceIngestorError("FFPROBE_INVALID", "Video nguồn không hợp lệ hoặc không đọc được.")
    return ProbeResult(
        duration_seconds=duration,
        width=width,
        height=height,
        fps=fps,
        video_codec=str(video.get("codec_name") or "unknown"),
        audio_codec=str(audio.get("codec_name")) if audio and audio.get("codec_name") else None,
    )


class RealSourceIngestor:
    def __init__(
        self,
        config: SourceIngestorConfig | None = None,
        ydl_factory: Callable[[dict[str, Any]], ContextManager[Any]] | None = None,
        probe_runner: Callable[[Path], ProbeResult] | None = None,
    ) -> None:
        self.config = config or SourceIngestorConfig.from_env()
        self._ydl_factory = ydl_factory
        self._probe_runner = probe_runner

    def readiness(self) -> dict[str, str]:
        return {
            "status": "ready" if self._yt_dlp_available() and self._tool(self.config.ffmpeg_path) and self._tool(self.config.ffprobe_path) else "missing_dependency",
            "yt_dlp": "ready" if self._yt_dlp_available() else "missing",
            "ffmpeg": self._tool(self.config.ffmpeg_path) or "missing",
            "ffprobe": self._tool(self.config.ffprobe_path) or "missing",
        }

    def download(
        self,
        youtube_url: str,
        job_id: str,
        workspace: Path,
        cancel: Event,
        progress: ProgressCallback,
    ) -> SourceResult:
        if cancel.is_set():
            raise JobCancelled
        if not is_youtube_url(youtube_url):
            raise SourceIngestorError("INVALID_YOUTUBE_URL", "Liên kết YouTube không hợp lệ.")
        if self.config.yt_dlp_mode != "python":
            raise SourceIngestorError("YTDLP_MODE_UNSUPPORTED", "Chế độ yt-dlp chưa được hỗ trợ.")
        ffmpeg = self._require_tool(self.config.ffmpeg_path, "FFMPEG_MISSING", "Không tìm thấy FFmpeg.")
        self._require_tool(self.config.ffprobe_path, "FFPROBE_MISSING", "Không tìm thấy ffprobe.")
        if not self._yt_dlp_available() and self._ydl_factory is None:
            raise SourceIngestorError("YTDLP_MISSING", "Không tìm thấy yt-dlp. Hãy chạy setup trước.")

        source_dir = (workspace.resolve() / "source").resolve()
        if source_dir.parent != workspace.resolve():
            raise SourceIngestorError("INVALID_WORKSPACE", "Workspace nguồn không hợp lệ.")
        source_dir.mkdir(parents=True, exist_ok=True)
        deadline = monotonic() + self.config.download_timeout_seconds

        def progress_hook(data: dict[str, Any]) -> None:
            if cancel.is_set():
                raise JobCancelled
            if monotonic() > deadline:
                raise SourceIngestorError("DOWNLOAD_TIMEOUT", "Tải video nguồn quá thời gian cho phép.")
            if data.get("status") != "downloading":
                return
            downloaded = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            percent = min(99, round(downloaded * 100 / total)) if total else 1
            progress(percent, f"Đang tải video nguồn: {percent}%")

        def postprocessor_hook(data: dict[str, Any]) -> None:
            if cancel.is_set():
                raise JobCancelled
            if monotonic() > deadline:
                raise SourceIngestorError("DOWNLOAD_TIMEOUT", "Tải video nguồn quá thời gian cho phép.")
            if data.get("status") == "started":
                progress(99, "Đang ghép và chuẩn hóa source.mp4")

        def match_filter(info: dict[str, Any], *, incomplete: bool) -> str | None:
            duration = info.get("duration")
            if not incomplete and self.config.max_duration_seconds and duration and duration > self.config.max_duration_seconds:
                return f"Source duration exceeds {self.config.max_duration_seconds} seconds"
            return None

        options = {
            "format": (
                f"bestvideo[height<={self.config.max_height}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height<={self.config.max_height}][ext=mp4]/best[height<={self.config.max_height}]"
            ),
            "outtmpl": str(source_dir / "source.%(ext)s"),
            "merge_output_format": "mp4",
            "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
            "ffmpeg_location": ffmpeg,
            "writethumbnail": True,
            "writeinfojson": False,
            "writesubtitles": False,
            "writeautomaticsub": False,
            "getcomments": False,
            "noplaylist": True,
            "playlistend": 1,
            "max_downloads": 1,
            "socket_timeout": min(60, self.config.download_timeout_seconds),
            "retries": 2,
            "fragment_retries": 2,
            "progress_hooks": [progress_hook],
            "postprocessor_hooks": [postprocessor_hook],
            "match_filter": match_filter,
            "quiet": True,
            "no_warnings": True,
        }

        try:
            with self._downloader(options) as downloader:
                info = downloader.extract_info(youtube_url, download=True)
            if info.get("_type") == "playlist":
                raise SourceIngestorError("PLAYLIST_NOT_SUPPORTED", "Playlist chưa được hỗ trợ.")
            video_path = source_dir / "source.mp4"
            if not video_path.is_file() or video_path.stat().st_size <= 0:
                raise SourceIngestorError("DOWNLOAD_OUTPUT_MISSING", "yt-dlp không tạo được source.mp4.")
            probe = (self._probe_runner or self._probe_video)(video_path)
            if self.config.max_duration_seconds and probe.duration_seconds > self.config.max_duration_seconds:
                raise SourceIngestorError("SOURCE_TOO_LONG", "Video dài hơn giới hạn cho phép.")
            raw_thumbnail = self._find_thumbnail(source_dir) or source_dir / "thumbnail.jpg"
            self._remove_ambiguous_video_files(source_dir, video_path)
            progress(100, "Đã tải và xác thực video nguồn")
            return SourceResult(
                source_video_path=video_path,
                thumbnail_path=raw_thumbnail,
                metadata_path=source_dir / "metadata.json",
                youtube_video_id=str(info.get("id") or ""),
                title=str(info.get("title") or "Video YouTube"),
                channel=str(info.get("channel") or info.get("uploader") or "Không rõ kênh"),
                duration_seconds=probe.duration_seconds,
                width=probe.width,
                height=probe.height,
                fps=probe.fps,
                file_size_bytes=video_path.stat().st_size,
                upload_date=info.get("upload_date"),
                original_url=str(info.get("webpage_url") or youtube_url),
                video_codec=probe.video_codec,
                audio_codec=probe.audio_codec,
                downloaded_at=datetime.now(timezone.utc).isoformat(),
                yt_dlp_version=self._package_version("yt-dlp"),
                ffmpeg_version=self._tool_version(ffmpeg),
            )
        except JobCancelled:
            self._cleanup_incomplete(source_dir)
            raise
        except SourceIngestorError:
            self._cleanup_incomplete(source_dir)
            raise
        except OSError as exc:
            self._cleanup_incomplete(source_dir)
            raise SourceIngestorError("SOURCE_WRITE_ERROR", "Không thể ghi video vào workspace.", str(exc)) from exc
        except Exception as exc:  # yt-dlp exposes several environment-specific exception classes
            self._cleanup_incomplete(source_dir)
            raise self._map_download_error(exc) from exc

    def prepare_thumbnail(
        self,
        result: SourceResult,
        job_id: str,
        workspace: Path,
        cancel: Event,
        progress: ProgressCallback,
    ) -> SourceResult:
        if cancel.is_set():
            raise JobCancelled
        source_dir = workspace.resolve() / "source"
        candidate = result.thumbnail_path if result.thumbnail_path.is_file() else self._find_thumbnail(source_dir)
        if not candidate:
            raise SourceIngestorError("THUMBNAIL_MISSING", "Video không có ảnh thumbnail sử dụng được.")
        target = source_dir / "thumbnail.jpg"
        temporary = source_dir / "thumbnail.jpg.tmp"
        try:
            with Image.open(candidate) as image:
                image.load()
                if image.width <= 0 or image.height <= 0:
                    raise SourceIngestorError("THUMBNAIL_INVALID", "Ảnh thumbnail không hợp lệ.")
                image.convert("RGB").save(temporary, format="JPEG", quality=92, optimize=True)
            os.replace(temporary, target)
            with Image.open(target) as validated:
                validated.verify()
            if target.stat().st_size <= 0:
                raise SourceIngestorError("THUMBNAIL_INVALID", "Ảnh thumbnail không hợp lệ.")
            for path in source_dir.glob("source.*"):
                if path != result.source_video_path and path.is_file():
                    path.unlink(missing_ok=True)
            result.thumbnail_path = target
            self._write_metadata(result, job_id, workspace)
            progress(100, "Đã chuẩn hóa và xác thực thumbnail")
            return result
        except JobCancelled:
            temporary.unlink(missing_ok=True)
            raise
        except SourceIngestorError:
            temporary.unlink(missing_ok=True)
            raise
        except (OSError, UnidentifiedImageError) as exc:
            temporary.unlink(missing_ok=True)
            raise SourceIngestorError("THUMBNAIL_INVALID", "Không thể đọc hoặc chuẩn hóa thumbnail.", str(exc)) from exc

    def _probe_video(self, video_path: Path) -> ProbeResult:
        ffprobe = self._require_tool(self.config.ffprobe_path, "FFPROBE_MISSING", "Không tìm thấy ffprobe.")
        command = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate",
            "-of", "json",
            str(video_path),
        ]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30, shell=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SourceIngestorError("FFPROBE_FAILED", "Không thể kiểm tra video nguồn.", str(exc)) from exc
        if completed.returncode:
            raise SourceIngestorError("FFPROBE_FAILED", "Không thể kiểm tra video nguồn.", completed.stderr.strip())
        try:
            return parse_ffprobe(json.loads(completed.stdout))
        except json.JSONDecodeError as exc:
            raise SourceIngestorError("FFPROBE_INVALID", "ffprobe trả về dữ liệu không hợp lệ.", str(exc)) from exc

    def _write_metadata(self, result: SourceResult, job_id: str, workspace: Path) -> None:
        source_dir = workspace.resolve() / "source"
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
        temporary = source_dir / "metadata.json.tmp"
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, result.metadata_path)

    def _downloader(self, options: dict[str, Any]) -> ContextManager[Any]:
        if self._ydl_factory:
            return self._ydl_factory(options)
        from yt_dlp import YoutubeDL

        return YoutubeDL(options)

    @staticmethod
    def _find_thumbnail(source_dir: Path) -> Path | None:
        candidates = [
            path for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        ]
        return max(candidates, key=lambda path: path.stat().st_size, default=None)

    @staticmethod
    def _cleanup_incomplete(source_dir: Path) -> None:
        for pattern in ("*.part", "*.ytdl", "*.tmp", "source.*"):
            for path in source_dir.glob(pattern):
                if path.is_file() and path.name != "metadata.json":
                    path.unlink(missing_ok=True)

    @staticmethod
    def _remove_ambiguous_video_files(source_dir: Path, keep: Path) -> None:
        for path in source_dir.glob("source.*"):
            if path != keep and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".m4a", ".opus"}:
                path.unlink(missing_ok=True)

    @staticmethod
    def _tool(command: str) -> str | None:
        path = Path(command)
        return str(path.resolve()) if path.is_file() else shutil.which(command)

    def _require_tool(self, command: str, code: str, message: str) -> str:
        resolved = self._tool(command)
        if not resolved:
            raise SourceIngestorError(code, message)
        return resolved

    @staticmethod
    def _yt_dlp_available() -> bool:
        try:
            version("yt-dlp")
            return True
        except PackageNotFoundError:
            return False

    @staticmethod
    def _package_version(package: str) -> str:
        try:
            return version(package)
        except PackageNotFoundError:
            return "unknown"

    @staticmethod
    def _tool_version(executable: str) -> str | None:
        try:
            line = subprocess.run(
                [executable, "-version"], capture_output=True, text=True, timeout=10, shell=False
            ).stdout.splitlines()[0]
            return line.strip() or None
        except (OSError, subprocess.TimeoutExpired, IndexError):
            return None

    @staticmethod
    def _map_download_error(exc: Exception) -> SourceIngestorError:
        message = str(exc)
        lowered = message.lower()
        if "private" in lowered:
            return SourceIngestorError("PRIVATE_VIDEO", "Video riêng tư, không thể tải.", message)
        if "age" in lowered or "sign in" in lowered or "login" in lowered:
            return SourceIngestorError("AUTH_REQUIRED", "Video yêu cầu đăng nhập hoặc xác minh độ tuổi.", message)
        if "unavailable" in lowered or "deleted" in lowered or "removed" in lowered:
            return SourceIngestorError("VIDEO_UNAVAILABLE", "Video không tồn tại hoặc không khả dụng.", message)
        if "ffmpeg" in lowered:
            return SourceIngestorError("DOWNLOAD_MERGE_FAILED", "Không thể ghép âm thanh và video nguồn.", message)
        if "timed out" in lowered or "network" in lowered or "http error" in lowered:
            return SourceIngestorError("NETWORK_ERROR", "Lỗi mạng khi tải video nguồn.", message)
        if "duration exceeds" in lowered:
            return SourceIngestorError("SOURCE_TOO_LONG", "Video dài hơn giới hạn cho phép.", message)
        return SourceIngestorError("DOWNLOAD_FAILED", "Không thể tải video nguồn.", message)
