from __future__ import annotations

import json
import math
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event, RLock
from time import monotonic
from typing import Any, Callable

from .adapters import JobCancelled
from .source_ingestor import ProbeResult, parse_ffprobe

ReviewProgressCallback = Callable[[str, int, str], None]


class ReviewEngineError(Exception):
    def __init__(self, code: str, message: str, technical: str | None = None) -> None:
        super().__init__(technical or message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ReviewEngineConfig:
    engine_path: Path = Path("engines/review-engine")
    python_path: str = sys.executable
    timeout_seconds: int = 14400
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    voice_reference_path: Path | None = None
    voice_reference_text: str = ""
    use_proxy_video: bool = True
    gemini_api_key: str = field(default="", repr=False)
    twelve_labs_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "ReviewEngineConfig":
        engine = Path(os.getenv("REVIEW_ENGINE_PATH", "engines/review-engine"))
        voice = os.getenv("REVIEW_VOICE_REFERENCE_PATH", "").strip()
        default_voice = engine / "voice.wav"
        return cls(
            engine_path=engine,
            python_path=os.getenv("REVIEW_ENGINE_PYTHON", sys.executable),
            timeout_seconds=int(os.getenv("REVIEW_ENGINE_TIMEOUT_SECONDS", "14400")),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            voice_reference_path=Path(voice) if voice else default_voice if default_voice.is_file() else None,
            voice_reference_text=os.getenv("REVIEW_VOICE_REFERENCE_TEXT", ""),
            use_proxy_video=os.getenv("USE_PROXY_VIDEO", "true").lower() in {"1", "true", "yes", "on"},
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            twelve_labs_api_key=os.getenv("TWELVE_LABS_API_KEY", os.getenv("TWELVE_API_KEY", "")),
        )


@dataclass(frozen=True)
class ReviewEngineInput:
    job_id: str
    youtube_url: str
    source_video_path: Path
    source_metadata_path: Path
    workspace: Path


@dataclass(frozen=True)
class ReviewEngineResult:
    job_id: str
    engine_job_id: str
    review_video_path: Path
    metadata_path: Path
    proxy_metrics_path: Path
    window_mapping_path: Path
    script_path: Path | None
    voice_path: Path | None
    timeline_path: Path | None
    duration_seconds: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str
    source_duration_seconds: float
    proxy_duration_seconds: float
    saved_percentage: float
    fallback_used: bool
    fallback_reason: str | None
    runtime_seconds: float


@dataclass
class _Session:
    status: str = "pending"
    progress: int = 0
    message: str = "Đang chờ"
    process: subprocess.Popen[str] | None = None
    cancelled: Event = field(default_factory=Event)


ENGINE_ERROR_MAP = {
    "CREDENTIALS_MISSING": ("REVIEW_ENGINE_CREDENTIALS_MISSING", "Thiếu thông tin xác thực cho Review Engine."),
    "GEMINI_FAILED": ("GEMINI_FAILED", "Không thể viết kịch bản review."),
    "OMNIVOICE_FAILED": ("OMNIVOICE_FAILED", "Không thể tạo giọng đọc review."),
    "TWELVE_INDEX_FAILED": ("TWELVE_INDEX_FAILED", "Không thể lập chỉ mục video review."),
    "MARENGO_SEARCH_FAILED": ("MARENGO_SEARCH_FAILED", "Không thể chọn cảnh cho video review."),
    "PROXY_MAPPING_FAILED": ("PROXY_MAPPING_FAILED", "Không thể ánh xạ cảnh proxy về video nguồn."),
    "REVIEW_RENDER_FAILED": ("REVIEW_RENDER_FAILED", "Không thể dựng video review."),
    "OUTPUT_INVALID": ("REVIEW_OUTPUT_INVALID", "Video review đầu ra không hợp lệ."),
    "CANCELLED": ("REVIEW_CANCELLED", "Đã hủy Review Engine."),
}

STAGE_MAP = {
    "preparing": ("script", 0, 5),
    "writing_review": ("script", 5, 100),
    "generating_voice": ("voice", 0, 65),
    "transcribing": ("voice", 65, 100),
    "selecting_windows": ("footage", 0, 25),
    "indexing_proxy": ("footage", 25, 50),
    "searching_scenes": ("footage", 50, 75),
    "mapping_timeline": ("footage", 75, 100),
    "rendering_review": ("review", 0, 85),
    "validating_output": ("review", 85, 100),
}


class ReviewEngineAdapter:
    def __init__(
        self,
        config: ReviewEngineConfig | None = None,
        probe_runner: Callable[[Path], ProbeResult] | None = None,
    ) -> None:
        self.config = config or ReviewEngineConfig.from_env()
        self._probe_runner = probe_runner
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def readiness(self) -> dict[str, str]:
        root = self.config.engine_path.resolve()
        checks = {
            "entrypoint": "ready" if (root / "review_cli.py").is_file() else "missing",
            "python": self._tool(self.config.python_path) or "missing",
            "ffmpeg": self._tool(self.config.ffmpeg_path) or "missing",
            "ffprobe": self._tool(self.config.ffprobe_path) or "missing",
            "voice_reference": "ready" if self.config.voice_reference_path and self.config.voice_reference_path.is_file() else "missing",
            "omnivoice": "ready" if (root / ".venv-omnivoice" / "Scripts" / "omnivoice-infer.exe").is_file() else "missing",
            "prompt": "ready" if (root / "GEMINI_PROMPT.txt").is_file() else "missing",
            "credentials": "ready" if self.config.gemini_api_key and self.config.twelve_labs_api_key else "missing",
        }
        return {"status": "ready" if all(value != "missing" for value in checks.values()) else "missing_dependency", **checks}

    def prepare(self, request: ReviewEngineInput) -> None:
        root = self.config.engine_path.resolve()
        if not root.is_dir():
            raise ReviewEngineError("REVIEW_ENGINE_NOT_CONFIGURED", "Không tìm thấy thư mục Review Engine.", str(root))
        if not (root / "review_cli.py").is_file():
            raise ReviewEngineError("REVIEW_ENGINE_ENTRYPOINT_MISSING", "Không tìm thấy Review Engine CLI.")
        if not self._tool(self.config.python_path):
            raise ReviewEngineError("REVIEW_ENGINE_NOT_CONFIGURED", "Không tìm thấy Python của Review Engine.")
        if not request.source_video_path.is_file():
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Không tìm thấy source.mp4 cho Review Engine.")
        if not request.source_metadata_path.is_file():
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Không tìm thấy metadata video nguồn.")
        try:
            json.loads(request.source_metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Metadata video nguồn không hợp lệ.", str(exc)) from exc
        if not self.config.gemini_api_key or not self.config.twelve_labs_api_key:
            raise ReviewEngineError("REVIEW_ENGINE_CREDENTIALS_MISSING", "Thiếu Gemini hoặc Twelve Labs API key.")
        if not self.config.voice_reference_path or not self.config.voice_reference_path.is_file():
            raise ReviewEngineError("REVIEW_ENGINE_NOT_CONFIGURED", "Thiếu file giọng đọc mẫu cho Review Engine.")
        if not self._tool(self.config.ffmpeg_path) or not self._tool(self.config.ffprobe_path):
            raise ReviewEngineError("REVIEW_ENGINE_NOT_CONFIGURED", "Không tìm thấy FFmpeg hoặc ffprobe.")
        review = self._review_dir(request)
        review.mkdir(parents=True, exist_ok=True)
        (review / "logs").mkdir(exist_ok=True)
        (review / "_engine").mkdir(exist_ok=True)
        if (review / "review.mp4").exists():
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "review.mp4 đã tồn tại; không ghi đè kết quả cũ.")
        self._doctor(request, review)
        with self._lock:
            self._sessions[request.job_id] = _Session(status="prepared", progress=1, message="Đã chuẩn bị Review Engine")

    def run(
        self,
        request: ReviewEngineInput,
        cancel: Event,
        progress: ReviewProgressCallback,
    ) -> ReviewEngineResult:
        session = self._session(request.job_id)
        self._set_status(request.job_id, "running", 1, "Đang khởi chạy Review Engine")
        review = self._review_dir(request)
        command = [
            self.config.python_path,
            str(self.config.engine_path.resolve() / "review_cli.py"),
            "run",
            "--job-id", request.job_id,
            "--source-video", str(request.source_video_path.resolve()),
            "--youtube-url", request.youtube_url,
            "--output-dir", str(review),
            "--working-dir", str(review / "_engine"),
            "--voice-reference", str(self.config.voice_reference_path.resolve()),
            "--voice-reference-text", self.config.voice_reference_text,
            "--resume-policy", "fail",
            "--progress-jsonl",
        ]
        if self.config.use_proxy_video:
            command.append("--use-proxy-video")
        environment = self._engine_environment()
        last_error: dict[str, Any] | None = None
        result_event: dict[str, Any] | None = None
        started = monotonic()

        def handle(payload: dict[str, Any]) -> None:
            nonlocal last_error, result_event
            if payload.get("event") == "error":
                last_error = payload.get("error") if isinstance(payload.get("error"), dict) else None
            elif payload.get("event") == "result":
                result_event = payload
            elif payload.get("event") == "stage":
                self._map_progress(request.job_id, payload, progress)

        try:
            return_code = self._execute(
                request.job_id, command, self.config.engine_path.resolve(), environment,
                cancel, handle, review / "logs" / "engine.jsonl", started,
            )
            if return_code:
                self._raise_engine_error(last_error, return_code)
            if not result_event:
                raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Review Engine không trả kết quả hoàn tất.")
            result = self._collect(request, result_event, monotonic() - started)
            progress("review", 100, "Review hoàn tất")
            self._set_status(request.job_id, "completed", 100, "Review hoàn tất")
            return result
        except JobCancelled:
            self._set_status(request.job_id, "cancelled", session.progress, "Đã hủy Review Engine")
            raise
        except TimeoutError as exc:
            self._set_status(request.job_id, "failed", session.progress, "Review Engine quá thời gian")
            raise ReviewEngineError("REVIEW_ENGINE_TIMEOUT", "Review Engine chạy quá thời gian cho phép.", str(exc)) from exc
        except ReviewEngineError:
            self._set_status(request.job_id, "failed", session.progress, "Review Engine thất bại")
            raise

    def status(self, job_id: str) -> dict[str, int | str]:
        session = self._session(job_id)
        return {"status": session.status, "progress": session.progress, "message": session.message}

    def cancel(self, job_id: str) -> None:
        with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return
            session.cancelled.set()
            session.status = "cancelled"
            process = session.process
        if process and process.poll() is None:
            self._signal_process(process)

    def cleanup(self, job_id: str, workspace: Path) -> None:
        shutil.rmtree(workspace.resolve() / "review" / "_engine", ignore_errors=True)

    def _execute(
        self,
        job_id: str,
        command: list[str],
        cwd: Path,
        environment: dict[str, str],
        cancel: Event,
        on_event: Callable[[dict[str, Any]], None],
        log_path: Path,
        started: float,
    ) -> int:
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command, cwd=cwd, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, creationflags=creation_flags,
        )
        with self._lock:
            self._sessions[job_id].process = process
        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        stopping: str | None = None
        stop_started = 0.0
        reader_done = False
        with log_path.open("a", encoding="utf-8") as log:
            while True:
                try:
                    line = lines.get(timeout=0.1)
                except queue.Empty:
                    line = ""
                if line is None:
                    reader_done = True
                if line:
                    log.write(line)
                    log.flush()
                    try:
                        payload = json.loads(line)
                        if isinstance(payload, dict):
                            on_event(payload)
                    except ValueError:
                        pass
                if stopping is None and (cancel.is_set() or self._session(job_id).cancelled.is_set()):
                    stopping = "cancel"
                    stop_started = monotonic()
                    self._signal_process(process)
                if stopping is None and monotonic() - started > self.config.timeout_seconds:
                    stopping = "timeout"
                    stop_started = monotonic()
                    self._signal_process(process)
                if process.poll() is not None and reader_done:
                    break
                if stopping and process.poll() is None and monotonic() - stop_started > 10:
                    self._kill_process(process)
            reader.join(timeout=1)
        with self._lock:
            self._sessions[job_id].process = None
        if stopping == "cancel":
            raise JobCancelled
        if stopping == "timeout":
            raise TimeoutError(f"timeout={self.config.timeout_seconds}s")
        return process.returncode or 0

    def _map_progress(self, job_id: str, payload: dict[str, Any], callback: ReviewProgressCallback) -> None:
        mapping = STAGE_MAP.get(str(payload.get("stage")))
        if not mapping:
            return
        stage, start, end = mapping
        try:
            fraction = min(1.0, max(0.0, float(payload.get("progress", 0))))
        except (TypeError, ValueError):
            fraction = 0
        value = round(start + (end - start) * fraction)
        messages = {
            "script": "Đang viết kịch bản",
            "voice": "Đang tạo giọng đọc",
            "footage": "Đang chọn cảnh",
            "review": "Đang dựng video review",
        }
        callback(stage, value, messages[stage])
        overall = {"script": 10, "voice": 35, "footage": 65, "review": 90}[stage] + round(value / 10)
        self._set_status(job_id, "running", min(99, overall), messages[stage])

    def _collect(self, request: ReviewEngineInput, event: dict[str, Any], runtime: float) -> ReviewEngineResult:
        review = self._review_dir(request)
        paths = {name: review / filename for name, filename in {
            "review": "review.mp4", "metadata": "metadata.json", "metrics": "proxy_metrics.json", "mapping": "window_mapping.json"
        }.items()}
        if any(not path.is_file() or path.stat().st_size == 0 for path in paths.values()):
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Review Engine thiếu artifact bắt buộc.")
        probe = (self._probe_runner or self._probe_video)(paths["review"])
        if probe.duration_seconds <= 0 or probe.width <= 0 or probe.height <= 0 or probe.fps <= 0 or not probe.audio_codec:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Video review không có đầy đủ luồng hình và tiếng.")
        try:
            engine_metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
            metrics = json.loads(paths["metrics"].read_text(encoding="utf-8"))
            mapping = json.loads(paths["mapping"].read_text(encoding="utf-8"))
            source_duration, proxy_duration = float(metrics["source_duration"]), float(metrics["proxy_duration"])
            saved = float(metrics["saved_percentage"])
            fallback = bool(metrics.get("fallback_count")) or bool(mapping.get("fallback"))
            reason = metrics.get("fallback_reason") or mapping.get("fallback_reason")
            self._validate_metrics(source_duration, proxy_duration, saved, fallback, reason, metrics, mapping)
        except ReviewEngineError:
            raise
        except (OSError, KeyError, TypeError, ValueError) as exc:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Metadata hoặc proxy metrics không hợp lệ.", str(exc)) from exc
        normalized = {
            "schema_version": 1,
            "job_id": request.job_id,
            "engine_job_id": str(event.get("job_id") or request.job_id),
            "source_video_path": "source/source.mp4",
            "review_video_path": "review/review.mp4",
            "proxy_metrics_path": "review/proxy_metrics.json",
            "window_mapping_path": "review/window_mapping.json",
            "script_path": "review/script/review.json" if (review / "script" / "review.json").is_file() else None,
            "voice_path": "review/voice/voice.wav" if (review / "voice" / "voice.wav").is_file() else None,
            "timeline_path": "review/timeline/timeline.json" if (review / "timeline" / "timeline.json").is_file() else None,
            "duration_seconds": probe.duration_seconds,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
            "source_duration_seconds": source_duration,
            "proxy_duration_seconds": proxy_duration,
            "saved_percentage": saved,
            "fallback_used": fallback,
            "fallback_reason": reason,
            "duration_total_seconds": round(float(engine_metadata.get("duration_total_seconds", runtime)), 3),
        }
        temporary = paths["metadata"].with_suffix(".json.tmp")
        temporary.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, paths["metadata"])
        return ReviewEngineResult(
            request.job_id, normalized["engine_job_id"], paths["review"], paths["metadata"], paths["metrics"], paths["mapping"],
            review / "script" / "review.json" if normalized["script_path"] else None,
            review / "voice" / "voice.wav" if normalized["voice_path"] else None,
            review / "timeline" / "timeline.json" if normalized["timeline_path"] else None,
            probe.duration_seconds, probe.width, probe.height, probe.fps, probe.video_codec, probe.audio_codec,
            source_duration, proxy_duration, saved, fallback, reason, normalized["duration_total_seconds"],
        )

    @staticmethod
    def _validate_metrics(
        source: float, proxy: float, saved: float, fallback: bool, reason: str | None,
        metrics: dict[str, Any], mapping: dict[str, Any],
    ) -> None:
        if not all(math.isfinite(value) for value in (source, proxy, saved)) or source <= 0 or proxy <= 0 or proxy > source + 0.25 or not 0 <= saved <= 100:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Proxy metrics chứa thời lượng không hợp lệ.")
        if fallback:
            if not reason or abs(proxy - source) > 0.25 or abs(saved) > 0.1:
                raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Trạng thái fallback proxy không nhất quán.")
            return
        if int(metrics.get("mapping_errors", 0)) != 0:
            raise ReviewEngineError("PROXY_MAPPING_FAILED", "Ánh xạ proxy có lỗi.")
        windows = mapping.get("windows")
        if not isinstance(windows, list) or not windows:
            raise ReviewEngineError("PROXY_MAPPING_FAILED", "Không có cửa sổ ánh xạ proxy.")
        cursor = 0.0
        source_end = -1.0
        for item in windows:
            try:
                ps, pe = float(item["proxy_start"]), float(item["proxy_end"])
                ss, se = float(item["source_start"]), float(item["source_end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ReviewEngineError("PROXY_MAPPING_FAILED", "Cửa sổ ánh xạ proxy không hợp lệ.", str(exc)) from exc
            if abs(ps - cursor) > 0.01 or pe <= ps or ss < source_end or ss < 0 or se <= ss or se > source + 0.01 or abs((pe - ps) - (se - ss)) > 0.01:
                raise ReviewEngineError("PROXY_MAPPING_FAILED", "Thứ tự hoặc thời lượng ánh xạ proxy không hợp lệ.")
            cursor, source_end = pe, se
        if abs(cursor - proxy) > 0.25:
            raise ReviewEngineError("PROXY_MAPPING_FAILED", "Thời lượng mapping không khớp proxy.")

    def _probe_video(self, path: Path) -> ProbeResult:
        command = [
            self.config.ffprobe_path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
        ]
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if completed.returncode:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Không thể đọc video review.", completed.stderr)
        try:
            return parse_ffprobe(json.loads(completed.stdout))
        except Exception as exc:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Thông tin video review không hợp lệ.", str(exc)) from exc

    def _doctor(self, request: ReviewEngineInput, review: Path) -> None:
        environment = self._engine_environment()
        ffprobe = Path(self.config.ffprobe_path)
        if ffprobe.is_file():
            environment["PATH"] = f"{ffprobe.resolve().parent}{os.pathsep}{environment.get('PATH', '')}"
        command = [
            self.config.python_path,
            str(self.config.engine_path.resolve() / "review_cli.py"),
            "doctor",
            "--source-video", str(request.source_video_path.resolve()),
            "--output-dir", str(review),
            "--json",
        ]
        try:
            completed = subprocess.run(
                command, cwd=self.config.engine_path.resolve(), env=environment,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            )
            payload = json.loads(completed.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.TimeoutExpired, ValueError, IndexError) as exc:
            raise ReviewEngineError("REVIEW_ENGINE_NOT_CONFIGURED", "Không thể kiểm tra Review Engine.", str(exc)) from exc
        if completed.returncode or not payload.get("ready"):
            missing = [name for name, ready in (payload.get("checks") or {}).items() if not ready]
            code = "REVIEW_ENGINE_CREDENTIALS_MISSING" if any("credentials" in name for name in missing) else "REVIEW_ENGINE_NOT_CONFIGURED"
            message = "Thiếu thông tin xác thực cho Review Engine." if code.endswith("CREDENTIALS_MISSING") else "Review Engine chưa sẵn sàng."
            raise ReviewEngineError(code, message, f"failed_checks={','.join(missing) or 'unknown'}")

    def _raise_engine_error(self, error: dict[str, Any] | None, return_code: int) -> None:
        engine_code = str((error or {}).get("code") or "INTERNAL_ERROR")
        code, message = ENGINE_ERROR_MAP.get(engine_code, ("REVIEW_ENGINE_FAILED", "Review Engine thực thi thất bại."))
        if code == "REVIEW_CANCELLED":
            raise JobCancelled
        raise ReviewEngineError(code, message, f"engine_code={engine_code}; exit={return_code}")

    def _session(self, job_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(job_id)
        if not session:
            raise ReviewEngineError("REVIEW_ENGINE_NOT_PREPARED", "Review Engine chưa được chuẩn bị.")
        return session

    def _set_status(self, job_id: str, status: str, progress: int, message: str) -> None:
        with self._lock:
            session = self._sessions[job_id]
            session.status, session.progress, session.message = status, progress, message

    @staticmethod
    def _review_dir(request: ReviewEngineInput) -> Path:
        workspace = request.workspace.resolve()
        review = (workspace / "review").resolve()
        if review.parent != workspace:
            raise ReviewEngineError("REVIEW_OUTPUT_INVALID", "Review workspace không hợp lệ.")
        return review

    @staticmethod
    def _tool(command: str) -> str | None:
        path = Path(command)
        return str(path.resolve()) if path.is_file() else shutil.which(command)

    def _engine_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            GEMINI_API_KEY=self.config.gemini_api_key,
            TWELVE_LABS_API_KEY=self.config.twelve_labs_api_key,
            FFMPEG_PATH=self.config.ffmpeg_path,
            FFPROBE_PATH=self.config.ffprobe_path,
            PYTHONIOENCODING="utf-8",
            PYTHONUTF8="1",
        )
        provider = environment.get("REVIEW_LLM_PROVIDER", "openai").strip().lower()
        openai_ready = bool(environment.get("OPENAI_API_KEY") and environment.get("REVIEW_LLM_MODEL"))
        if provider == "openai" and not openai_ready and self.config.gemini_api_key:
            environment["REVIEW_LLM_PROVIDER"] = "gemini"
        return environment

    @staticmethod
    def _signal_process(process: subprocess.Popen[str]) -> None:
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        except (OSError, ValueError):
            pass

    @staticmethod
    def _kill_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
        else:
            process.kill()
