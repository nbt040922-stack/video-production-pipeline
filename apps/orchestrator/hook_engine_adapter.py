from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from threading import Event, RLock
from typing import Callable

from PIL import Image, UnidentifiedImageError

from .adapters import JobCancelled, ProgressCallback
from .source_ingestor import ProbeResult, SourceIngestorError, parse_ffprobe


SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PHASE_3_RESULT = re.compile(r"\[PASS\] Phase 3 job ([A-Za-z0-9_-]+): (.+)")


class HookEngineError(Exception):
    def __init__(self, code: str, message: str, technical: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.technical = technical


@dataclass(frozen=True)
class HookEngineConfig:
    engine_path: Path = Path("engines/hook-engine")
    python_path: str = sys.executable
    motion_id: str = "motion1"
    server: str = "http://127.0.0.1:8188"
    timeout_seconds: int = 7200
    seed: int = 42
    min_compatibility: float = 0.35
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    target_duration_seconds: float = 5.0
    duration_tolerance_seconds: float = 0.25

    @classmethod
    def from_env(cls) -> "HookEngineConfig":
        return cls(
            engine_path=Path(os.getenv("HOOK_ENGINE_PATH", "engines/hook-engine")),
            python_path=os.getenv("HOOK_ENGINE_PYTHON", sys.executable),
            motion_id=os.getenv("HOOK_MOTION_ID", "motion1"),
            server=os.getenv("HOOK_ENGINE_SERVER", "http://127.0.0.1:8188"),
            timeout_seconds=int(os.getenv("HOOK_ENGINE_TIMEOUT_SECONDS", "7200")),
            seed=int(os.getenv("HOOK_ENGINE_SEED", "42")),
            min_compatibility=float(os.getenv("HOOK_MIN_COMPATIBILITY", "0.35")),
            ffmpeg_path=os.getenv("FFMPEG_PATH", "ffmpeg"),
            ffprobe_path=os.getenv("FFPROBE_PATH", "ffprobe"),
            duration_tolerance_seconds=float(os.getenv("HOOK_DURATION_TOLERANCE_SECONDS", "0.25")),
        )


@dataclass
class _Session:
    status: str = "pending"
    progress: int = 0
    message: str = "Đang chờ"
    process: subprocess.Popen[str] | None = None
    cancelled: Event | None = None


CommandRunner = Callable[
    [list[str], Path, int, Callable[[], bool], Callable[[float], None]],
    subprocess.CompletedProcess[str],
]
ProbeRunner = Callable[[Path], ProbeResult]


class HookEngineAdapter:
    def __init__(
        self,
        config: HookEngineConfig | None = None,
        *,
        command_runner: CommandRunner | None = None,
        probe_runner: ProbeRunner | None = None,
    ) -> None:
        self.config = config or HookEngineConfig.from_env()
        self._command_runner = command_runner
        self._probe_runner = probe_runner
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def prepare(self, thumbnail: Path, job_id: str, workspace: Path) -> None:
        if not SAFE_ID.fullmatch(job_id):
            raise HookEngineError("HOOK_INVALID_JOB_ID", "Mã công việc Hook không hợp lệ.")
        workspace = workspace.resolve()
        expected_thumbnail = workspace / "source" / "thumbnail.jpg"
        if thumbnail.resolve() != expected_thumbnail or not thumbnail.is_file():
            raise HookEngineError("HOOK_THUMBNAIL_MISSING", "Không tìm thấy thumbnail cho Hook Engine.")
        try:
            with Image.open(thumbnail) as image:
                image.verify()
                if image.format != "JPEG" or image.width <= 0 or image.height <= 0:
                    raise HookEngineError("HOOK_THUMBNAIL_INVALID", "Thumbnail cho Hook Engine không hợp lệ.")
        except (OSError, UnidentifiedImageError) as exc:
            raise HookEngineError("HOOK_THUMBNAIL_INVALID", "Thumbnail cho Hook Engine không hợp lệ.", str(exc)) from exc

        self._require_runtime()
        hook_dir = workspace / "hook"
        hook_dir.mkdir(parents=True, exist_ok=True)
        for path in (hook_dir / "_engine", hook_dir / "_finalized"):
            shutil.rmtree(path, ignore_errors=True)
            path.mkdir()
        for path in (hook_dir / "final_hook.mp4", hook_dir / "metadata.json"):
            path.unlink(missing_ok=True)
        with self._lock:
            self._sessions[job_id] = _Session(status="prepared", progress=5, message="Đã chuẩn bị Hook Engine", cancelled=Event())

    def run(
        self,
        thumbnail: Path,
        job_id: str,
        workspace: Path,
        cancel: Event,
        progress: ProgressCallback,
    ) -> Path:
        session = self._session(job_id)
        workspace = workspace.resolve()
        hook_dir = workspace / "hook"
        engine_root = self.config.engine_path.resolve()
        python = self._resolve_executable(self.config.python_path)
        raw_root = hook_dir / "_engine"
        finalized_root = hook_dir / "_finalized"

        try:
            self._set_status(job_id, "running", 10, "Đang khởi chạy Hook Engine")
            progress(10, "Đang khởi chạy Hook Engine")
            generate = [
                python,
                str(engine_root / "main.py"),
                "generate",
                "--motion-id",
                self.config.motion_id,
                "--image",
                str(thumbnail.resolve()),
                "--output",
                str(raw_root / "raw_candidate.mp4"),
                "--server",
                self.config.server,
                "--seed",
                str(self.config.seed),
                "--timeout",
                str(self.config.timeout_seconds),
                "--min-compatibility",
                str(self.config.min_compatibility),
            ]
            generated = self._run_command(
                job_id,
                generate,
                engine_root,
                cancel,
                lambda elapsed: progress(25, f"Hook Engine đang tạo video: {round(elapsed)} giây"),
            )
            match = PHASE_3_RESULT.search(generated.stdout)
            if not match:
                raise HookEngineError("HOOK_ENGINE_FAILED", "Hook Engine không trả về kết quả Phase 3 hợp lệ.", generated.stdout)
            engine_job_id = match.group(1)
            raw_video = Path(match.group(2).strip()).resolve()
            if raw_root.resolve() not in raw_video.parents or not raw_video.is_file():
                raise HookEngineError("HOOK_OUTPUT_INVALID", "Hook Engine không tạo được raw candidate hợp lệ.")

            self._set_status(job_id, "running", 80, "Đang hoàn thiện video Hook")
            progress(80, "Đang hoàn thiện video Hook")
            finalized = self._run_command(
                job_id,
                [
                    python,
                    str(engine_root / "main.py"),
                    "phase4",
                    "--raw-video",
                    str(raw_video),
                    "--output-dir",
                    str(finalized_root),
                ],
                engine_root,
                cancel,
                lambda elapsed: progress(90, f"Đang chuẩn hóa Hook: {round(elapsed)} giây"),
            )
            if finalized.returncode:
                raise HookEngineError("HOOK_ENGINE_FAILED", "Hook Engine thất bại khi hoàn thiện video.", finalized.stderr)
            engine_output = finalized_root / engine_job_id / "final_hook.mp4"
            if not engine_output.is_file():
                raise HookEngineError("HOOK_OUTPUT_MISSING", "Hook Engine không tạo final_hook.mp4.")

            output = hook_dir / "final_hook.mp4"
            os.replace(engine_output, output)
            progress(97, "Đang xác thực final_hook.mp4")
            probe = (self._probe_runner or self._probe_video)(output)
            self._validate_output(output, probe)
            self._write_metadata(workspace, job_id, engine_job_id, probe)
            self._set_status(job_id, "completed", 100, "Hook hoàn tất")
            progress(100, "Hook hoàn tất")
            return output
        except JobCancelled:
            self._set_status(job_id, "cancelled", session.progress, "Đã hủy Hook Engine")
            raise
        except HookEngineError:
            self._set_status(job_id, "failed", session.progress, "Hook Engine thất bại")
            raise
        except TimeoutError as exc:
            self._set_status(job_id, "failed", session.progress, "Hook Engine quá thời gian")
            raise HookEngineError("HOOK_TIMEOUT", "Hook Engine chạy quá thời gian cho phép.", str(exc)) from exc
        except Exception as exc:
            self._set_status(job_id, "failed", session.progress, "Hook Engine thất bại")
            raise HookEngineError("HOOK_ENGINE_FAILED", "Hook Engine chạy thất bại.", str(exc)) from exc

    def status(self, job_id: str) -> dict[str, int | str]:
        session = self._session(job_id)
        return {"status": session.status, "progress": session.progress, "message": session.message}

    def cancel(self, job_id: str) -> None:
        with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                return
            if session.cancelled:
                session.cancelled.set()
            session.status = "cancelled"
            session.message = "Đã hủy Hook Engine"
            process = session.process
        self._interrupt_engine()
        self._stop_process(process)

    def cleanup(self, job_id: str, workspace: Path) -> None:
        hook_dir = workspace.resolve() / "hook"
        if self.status(job_id)["status"] != "completed":
            (hook_dir / "final_hook.mp4").unlink(missing_ok=True)
            (hook_dir / "metadata.json").unlink(missing_ok=True)
        shutil.rmtree(hook_dir / "_engine", ignore_errors=True)
        shutil.rmtree(hook_dir / "_finalized", ignore_errors=True)

    def readiness(self) -> dict[str, str]:
        try:
            self._require_runtime()
            urllib.request.urlopen(self.config.server.rstrip("/") + "/system_stats", timeout=1).close()
        except HookEngineError as exc:
            return {"status": "missing_dependency", "detail": exc.message}
        except Exception as exc:
            return {"status": "missing_dependency", "detail": f"Không kết nối được ComfyUI: {exc}"}
        return {
            "status": "ready",
            "engine_path": str(self.config.engine_path.resolve()),
            "motion_id": self.config.motion_id,
            "server": self.config.server,
        }

    def _run_command(
        self,
        job_id: str,
        command: list[str],
        cwd: Path,
        external_cancel: Event,
        on_tick: Callable[[float], None],
    ) -> subprocess.CompletedProcess[str]:
        cancelled = lambda: external_cancel.is_set() or self._is_cancelled(job_id)
        if cancelled():
            raise JobCancelled
        runner = self._command_runner or (
            lambda cmd, directory, timeout, is_cancelled, tick: self._execute(
                job_id, cmd, directory, timeout, is_cancelled, tick
            )
        )
        result = runner(command, cwd, self.config.timeout_seconds, cancelled, on_tick)
        if cancelled():
            raise JobCancelled
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            if "timed out" in detail.lower():
                raise HookEngineError("HOOK_TIMEOUT", "Hook Engine chạy quá thời gian cho phép.", detail)
            raise HookEngineError("HOOK_ENGINE_FAILED", "Hook Engine chạy thất bại.", detail)
        return result

    def _execute(
        self,
        job_id: str,
        command: list[str],
        cwd: Path,
        timeout: int,
        cancelled: Callable[[], bool],
        on_tick: Callable[[float], None],
    ) -> subprocess.CompletedProcess[str]:
        started = time.monotonic()
        next_tick = started
        environment = os.environ.copy()
        ffmpeg_dir = str(Path(self._resolve_executable(self.config.ffmpeg_path)).parent)
        environment["PATH"] = ffmpeg_dir + os.pathsep + environment.get("PATH", "")
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                env=environment,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                start_new_session=os.name != "nt",
            )
            with self._lock:
                self._sessions[job_id].process = process
            try:
                while process.poll() is None:
                    now = time.monotonic()
                    elapsed = now - started
                    if cancelled():
                        self._interrupt_engine()
                        self._stop_process(process)
                        raise JobCancelled
                    if elapsed > timeout:
                        self._interrupt_engine()
                        self._stop_process(process)
                        raise TimeoutError(f"Hook Engine timed out after {timeout}s")
                    if now >= next_tick:
                        on_tick(elapsed)
                        next_tick = now + 5
                    time.sleep(1)
                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout = stdout_file.read().decode("utf-8", errors="replace")
                stderr = stderr_file.read().decode("utf-8", errors="replace")
                return subprocess.CompletedProcess(command, process.returncode or 0, stdout, stderr)
            finally:
                with self._lock:
                    if self._sessions.get(job_id):
                        self._sessions[job_id].process = None

    def _probe_video(self, path: Path) -> ProbeResult:
        ffprobe = self._resolve_executable(self.config.ffprobe_path)
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height,avg_frame_rate:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            shell=False,
        )
        if completed.returncode:
            raise HookEngineError("HOOK_OUTPUT_INVALID", "Không thể đọc final_hook.mp4.", completed.stderr)
        try:
            return parse_ffprobe(json.loads(completed.stdout))
        except (json.JSONDecodeError, SourceIngestorError) as exc:
            raise HookEngineError("HOOK_OUTPUT_INVALID", "final_hook.mp4 không hợp lệ.", str(exc)) from exc

    def _validate_output(self, output: Path, probe: ProbeResult) -> None:
        if not output.is_file() or output.stat().st_size <= 0:
            raise HookEngineError("HOOK_OUTPUT_MISSING", "Hook Engine không tạo final_hook.mp4.")
        if abs(probe.duration_seconds - self.config.target_duration_seconds) > self.config.duration_tolerance_seconds:
            raise HookEngineError(
                "HOOK_OUTPUT_INVALID",
                f"Hook phải dài khoảng {self.config.target_duration_seconds:g} giây.",
                f"duration={probe.duration_seconds}",
            )
        if probe.width <= 0 or probe.height <= 0:
            raise HookEngineError("HOOK_OUTPUT_INVALID", "Độ phân giải Hook không hợp lệ.")

    def _write_metadata(
        self, workspace: Path, job_id: str, engine_job_id: str, probe: ProbeResult
    ) -> None:
        target = workspace / "hook" / "metadata.json"
        temporary = target.with_suffix(".json.tmp")
        payload = {
            "schema_version": 1,
            "job_id": job_id,
            "engine_job_id": engine_job_id,
            "motion_id": self.config.motion_id,
            "thumbnail_path": "source/thumbnail.jpg",
            "final_video_path": "hook/final_hook.mp4",
            "duration_seconds": probe.duration_seconds,
            "width": probe.width,
            "height": probe.height,
            "fps": probe.fps,
            "video_codec": probe.video_codec,
            "audio_codec": probe.audio_codec,
        }
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)

    def _require_runtime(self) -> None:
        root = self.config.engine_path.resolve()
        if not (root / "main.py").is_file():
            raise HookEngineError("HOOK_ENGINE_NOT_READY", "Không tìm thấy Hook Engine entry point.")
        if not (root / "ComfyUI" / "main.py").is_file():
            raise HookEngineError("HOOK_ENGINE_NOT_READY", "Không tìm thấy ComfyUI runtime của Hook Engine.")
        self._resolve_executable(self.config.python_path)
        self._resolve_executable(self.config.ffmpeg_path)
        self._resolve_executable(self.config.ffprobe_path)
        if not SAFE_ID.fullmatch(self.config.motion_id):
            raise HookEngineError("HOOK_ENGINE_NOT_READY", "HOOK_MOTION_ID không hợp lệ.")
        motions = root / "motion_library"
        found = False
        for metadata in motions.rglob("metadata.json") if motions.is_dir() else ():
            try:
                if json.loads(metadata.read_text(encoding="utf-8")).get("motion_id") == self.config.motion_id:
                    found = True
                    break
            except (OSError, json.JSONDecodeError):
                continue
        if not found:
            raise HookEngineError("HOOK_ENGINE_NOT_READY", f"Không tìm thấy motion `{self.config.motion_id}`.")

    @staticmethod
    def _resolve_executable(value: str) -> str:
        candidate = Path(value)
        resolved = str(candidate.resolve()) if candidate.is_file() else shutil.which(value)
        if not resolved:
            raise HookEngineError("HOOK_ENGINE_NOT_READY", f"Không tìm thấy executable `{value}`.")
        return resolved

    def _session(self, job_id: str) -> _Session:
        with self._lock:
            session = self._sessions.get(job_id)
            if not session:
                raise HookEngineError("HOOK_NOT_PREPARED", "Hook Engine chưa được chuẩn bị.")
            return session

    def _set_status(self, job_id: str, status: str, progress: int, message: str) -> None:
        with self._lock:
            session = self._sessions[job_id]
            session.status = status
            session.progress = progress
            session.message = message

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(job_id)
            return bool(session and session.cancelled and session.cancelled.is_set())

    def _interrupt_engine(self) -> None:
        try:
            request = urllib.request.Request(
                self.config.server.rstrip("/") + "/interrupt",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(request, timeout=3).close()
        except Exception:
            pass

    @staticmethod
    def _stop_process(process: subprocess.Popen[str] | None) -> None:
        if not process or process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                shell=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
