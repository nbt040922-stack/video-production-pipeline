from __future__ import annotations

import json
import logging
import os
import re
import traceback
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, RLock, Thread
from time import sleep
from typing import Any
from uuid import uuid4

from .adapters import (
    FinalComposer,
    HookEngine,
    JobCancelled,
    ReviewEngine,
    SourceIngestor,
)
from .final_composer import FinalComposer as RealFinalComposer, FinalComposerError
from .hook_engine_adapter import HookEngineAdapter, HookEngineError
from .review_engine_adapter import (
    ReviewEngineAdapter,
    ReviewEngineError,
    ReviewEngineInput,
    ReviewEngineResult,
)
from .models import (
    EngineStatus,
    ErrorData,
    JobStage,
    JobStatus,
    OutputMetadata,
    SourceMetadata,
    StageStatus,
    VideoJob,
    utc_now,
)
from .source_ingestor import RealSourceIngestor, SourceIngestorError, SourceResult
SAFE_JOB_ID = re.compile(r"^[a-f0-9]{32}$")
TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}

STAGES = (
    ("download", "Tải video nguồn"),
    ("thumbnail", "Chuẩn bị ảnh bìa"),
    ("hook", "Tạo đoạn mở đầu"),
    ("script", "Viết bài đánh giá"),
    ("voice", "Tạo giọng đọc"),
    ("footage", "Chọn cảnh quay"),
    ("review", "Dựng video đánh giá"),
    ("compose", "Ghép video cuối"),
    ("validate", "Kiểm tra đầu ra"),
)


class PipelineError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


class JobManager:
    def __init__(
        self,
        workspace: Path | str = "workspace",
        step_delay: float = 0.3,
        source_ingestor: SourceIngestor | None = None,
        hook_engine: HookEngine | None = None,
        review_engine: ReviewEngine | None = None,
        composer: FinalComposer | None = None,
        max_concurrent_jobs: int | None = None,
        max_queued_jobs: int | None = None,
        duplicate_window_seconds: int | None = None,
        max_active_jobs_per_user: int | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._jobs: dict[str, VideoJob] = {}
        self._corrupted: set[str] = set()
        self._cancel_events: dict[str, Event] = {}
        self._workers: dict[str, Thread] = {}
        self.step_delay = step_delay
        self.max_concurrent_jobs = max(1, max_concurrent_jobs or int(os.getenv("PIPELINE_MAX_CONCURRENT_JOBS", "1")))
        self.max_queued_jobs = max(1, max_queued_jobs or int(os.getenv("PIPELINE_MAX_QUEUED_JOBS", "20")))
        self.duplicate_window_seconds = max(0, duplicate_window_seconds if duplicate_window_seconds is not None else int(os.getenv("PIPELINE_DUPLICATE_WINDOW_SECONDS", "60")))
        self.max_active_jobs_per_user = max(1, max_active_jobs_per_user or int(os.getenv("PIPELINE_MAX_ACTIVE_JOBS_PER_USER", "5")))
        self.source_ingestor = source_ingestor or RealSourceIngestor()
        self.hook_engine = hook_engine or HookEngineAdapter()
        self.review_engine = review_engine or ReviewEngineAdapter()
        self.composer = composer or RealFinalComposer()
        self._recover_jobs()
        with self._lock:
            self._dispatch_locked()

    def create_job(self, youtube_url: str, retry_of: str | None = None, attempt: int = 1,
                   owner_user_id: str | None = None, owner_username: str = "legacy") -> VideoJob:
        with self._lock:
            active = sum(job.owner_user_id == owner_user_id and job.status not in TERMINAL_STATUSES for job in self._jobs.values())
            if owner_user_id and active >= self.max_active_jobs_per_user:
                raise PipelineError("USER_JOB_LIMIT_REACHED", "Bạn đã đạt giới hạn công việc đang hoạt động.", 429)
            queued = sum(job.status == JobStatus.QUEUED and job.job_id not in self._workers for job in self._jobs.values())
            if queued >= self.max_queued_jobs:
                raise PipelineError("QUEUE_FULL", "Hàng đợi đã đầy. Vui lòng thử lại sau.", 429)
            if not retry_of and self.duplicate_window_seconds:
                cutoff = datetime.now(timezone.utc).timestamp() - self.duplicate_window_seconds
                duplicate = next((job for job in self._jobs.values() if job.owner_user_id == owner_user_id and job.youtube_url == youtube_url and datetime.fromisoformat(job.created_at).timestamp() >= cutoff), None)
                if duplicate:
                    raise PipelineError("DUPLICATE_JOB", "URL này vừa được gửi. Vui lòng theo dõi công việc hiện có.", 409, {"job_id": duplicate.job_id})
            while True:
                job_id = uuid4().hex
                job_dir = self.workspace / job_id
                try:
                    job_dir.mkdir()
                    break
                except FileExistsError:
                    continue

            for folder in ("source", "hook", "review", "final", "metadata", "logs"):
                (job_dir / folder).mkdir()

            job = VideoJob(
                job_id=job_id,
                youtube_url=youtube_url,
                owner_user_id=owner_user_id,
                owner_username=owner_username,
                status=JobStatus.QUEUED,
                stages=[JobStage(id=stage_id, name=name) for stage_id, name in STAGES],
                created_at=utc_now(),
                hook_engine=EngineStatus(output_filename="final_hook.mp4"),
                review_engine=EngineStatus(output_filename="review.mp4", proxy_savings="Đang tính"),
                attempt=attempt,
                retry_of=retry_of,
            )
            self._jobs[job_id] = job
            self._cancel_events[job_id] = Event()
            self._persist(job)
            self._log(job_id, "Job queued")
            self._dispatch_locked()
            return self._jobs[job_id].model_copy(deep=True)

    def list_jobs(self, owner_user_id: str | None = None, owner_username: str | None = None,
                  status: str | None = None, restrict_owner: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            if restrict_owner:
                jobs = [job for job in jobs if job.owner_user_id == owner_user_id]
            if owner_username:
                jobs = [job for job in jobs if job.owner_username == owner_username]
            if status:
                jobs = [job for job in jobs if job.status.value == status]
            return [{
                "job_id": job.job_id,
                "source_title": job.source.title if job.source else None,
                "submitted_at": job.created_at,
                "status": job.status,
                "progress": job.progress_percentage,
                "queue_position": job.queue_position,
                "current_stage": job.current_stage,
                "final_output_available": bool(job.output),
                "error": job.error.message if job.error else None,
                "owner_user_id": job.owner_user_id,
                "owner_username": job.owner_username,
            } for job in jobs]

    def get_job(self, job_id: str) -> VideoJob:
        self._validate_job_id(job_id)
        with self._lock:
            if job_id in self._corrupted:
                raise PipelineError("CORRUPTED_JOB_METADATA", "Dữ liệu công việc bị hỏng.", 500)
            job = self._jobs.get(job_id)
            if not job:
                raise PipelineError("JOB_NOT_FOUND", "Không tìm thấy công việc.", 404)
            return job.model_copy(deep=True)

    def cancel_job(self, job_id: str) -> VideoJob:
        with self._lock:
            job = self.get_job(job_id)
            if job.status == JobStatus.CANCELLED:
                return job
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED}:
                raise PipelineError("INVALID_JOB_STATE", "Không thể hủy công việc đã kết thúc.", 409)
            cancel_hook = job.current_stage == "hook"
            cancel_review = job.current_stage in {"script", "voice", "footage", "review"}
            self._cancel_events[job_id].set()
            self._mark_cancelled(self._jobs[job_id])
            self._refresh_queue_positions_locked()
            self._dispatch_locked()
            result = self._jobs[job_id].model_copy(deep=True)
        if cancel_hook:
            self.hook_engine.cancel(job_id)
        if cancel_review:
            self.review_engine.cancel(job_id)
        return result

    def retry_job(self, job_id: str) -> VideoJob:
        original = self.get_job(job_id)
        if original.status != JobStatus.FAILED:
            raise PipelineError("INVALID_JOB_STATE", "Chỉ có thể thử lại công việc thất bại.", 409)
        return self.create_job(original.youtube_url, retry_of=original.job_id, attempt=original.attempt + 1,
                               owner_user_id=original.owner_user_id, owner_username=original.owner_username)

    def wait(self, job_id: str, timeout: float = 10) -> VideoJob:
        worker = self._workers.get(job_id)
        if worker:
            worker.join(timeout)
        return self.get_job(job_id)

    def _run_job(self, job_id: str) -> None:
        try:
            with self._lock:
                job = self._jobs[job_id]
                job.status = JobStatus.VALIDATING
                job.started_at = utc_now()
                self._persist(job)
                self._log(job_id, "Validating input")

            cancel = self._cancel_events[job_id]
            if cancel.is_set():
                raise JobCancelled
            source_result: SourceResult | None = None

            review_complete = False
            for index, (stage_id, _name) in enumerate(STAGES):
                if review_complete and stage_id in {"voice", "footage", "review"}:
                    continue
                self._start_stage(job_id, index)
                workspace = self._job_dir(job_id)
                progress = lambda value, message, active_stage=stage_id: self._report_progress(
                    job_id, active_stage, value, message
                )
                if stage_id == "download":
                    job = self.get_job(job_id)
                    source_result = self.source_ingestor.download(
                        job.youtube_url, job_id, workspace, cancel, progress
                    )
                elif stage_id == "thumbnail":
                    if source_result is None:
                        raise SourceIngestorError("SOURCE_RESULT_MISSING", "Thiếu dữ liệu video nguồn.")
                    source_result = self.source_ingestor.prepare_thumbnail(
                        source_result, job_id, workspace, cancel, progress
                    )
                    self._apply_source_result(job_id, source_result)
                else:
                    self._run_non_source_stage(job_id, stage_id, cancel, progress)
                if stage_id == "script":
                    review_complete = True
                    self._finish_review(job_id)
                else:
                    self._finish_stage(job_id, index)

            with self._lock:
                job = self._jobs[job_id]
                output_path = self._job_dir(job_id) / "final" / "final_video.mp4"
                metadata = json.loads((output_path.parent / "metadata.json").read_text(encoding="utf-8"))
                job.status = JobStatus.COMPLETED
                job.current_stage = None
                job.progress_percentage = 100
                job.finished_at = utc_now()
                job.elapsed_seconds = self._elapsed(job.started_at)
                job.output = OutputMetadata(
                    filename=output_path.name,
                    resolution=f"{metadata['width']}×{metadata['height']}",
                    duration=self._format_duration(float(metadata["duration_seconds"])),
                    file_size=self._format_size(int(metadata["file_size_bytes"])),
                    relative_path=f"{job_id}/final/{output_path.name}",
                    preview_url=f"/api/jobs/{job_id}/assets/final",
                )
                self._persist(job)
                self._log(job_id, "Job completed")
        except JobCancelled:
            with self._lock:
                self._mark_cancelled(self._jobs[job_id])
        except Exception as exc:  # noqa: BLE001 - worker boundary logs full traceback
            with self._lock:
                job = self._jobs[job_id]
                current = next((stage for stage in job.stages if stage.status == StageStatus.RUNNING), None)
                error = (
                    ErrorData(code=exc.code, message=exc.message)
                    if isinstance(exc, (SourceIngestorError, HookEngineError, ReviewEngineError, FinalComposerError))
                    else ErrorData(code="WORKER_ERROR", message="Xử lý công việc thất bại.")
                )
                if current:
                    current.status = StageStatus.FAILED
                    current.error = error
                    current.finished_at = utc_now()
                    current.elapsed_seconds = self._elapsed(current.started_at)
                job.status = JobStatus.FAILED
                job.finished_at = utc_now()
                job.elapsed_seconds = self._elapsed(job.started_at)
                job.error = error
                if job.review_engine.status == StageStatus.RUNNING:
                    job.review_engine.status = StageStatus.FAILED
                    job.review_engine.message = error.message
                if job.hook_engine.status == StageStatus.RUNNING:
                    job.hook_engine.status = StageStatus.FAILED
                    job.hook_engine.message = error.message
                self._persist(job)
                self._log(job_id, f"Worker failed: {exc}\n{traceback.format_exc()}")
        finally:
            with self._lock:
                self._workers.pop(job_id, None)
                self._dispatch_locked()

    def _run_non_source_stage(
        self, job_id: str, stage_id: str, cancel: Event, progress: Any
    ) -> None:
        workspace = self._job_dir(job_id)
        job = self.get_job(job_id)
        fail = "fixture=fail" in job.youtube_url and job.attempt == 1
        actions = {
            "hook": lambda: self._run_hook(job_id, workspace, cancel, progress),
            "script": lambda: self._run_review(job_id, workspace, cancel, fail),
            "compose": lambda: self.composer.compose(workspace, cancel, progress),
            "validate": lambda: self.composer.validate(workspace, cancel, progress),
        }
        actions[stage_id]()

    def _run_hook(self, job_id: str, workspace: Path, cancel: Event, progress: Any) -> None:
        thumbnail = workspace / "source" / "thumbnail.jpg"
        self.hook_engine.prepare(thumbnail, job_id, workspace)
        try:
            self.hook_engine.run(thumbnail, job_id, workspace, cancel, progress)
        finally:
            self.hook_engine.cleanup(job_id, workspace)

    def _run_review(self, job_id: str, workspace: Path, cancel: Event, fail: bool) -> None:
        if fail:
            raise RuntimeError("Controlled review adapter failure")
        job = self.get_job(job_id)
        request = ReviewEngineInput(
            job_id=job_id,
            youtube_url=job.youtube_url,
            source_video_path=workspace / "source" / "source.mp4",
            source_metadata_path=workspace / "source" / "metadata.json",
            workspace=workspace,
        )
        self.review_engine.prepare(request)
        try:
            result = self.review_engine.run(
                request,
                cancel,
                lambda stage, value, message: self._report_review_progress(
                    job_id, stage, value, message
                ),
            )
            if isinstance(result, ReviewEngineResult):
                self._apply_review_result(job_id, result)
        finally:
            self.review_engine.cleanup(job_id, workspace)

    def _apply_source_result(self, job_id: str, result: SourceResult) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.source = SourceMetadata(
                title=result.title,
                channel=result.channel,
                duration=self._format_duration(result.duration_seconds),
                thumbnail_url=f"/api/jobs/{job_id}/assets/thumbnail",
                youtube_video_id=result.youtube_video_id,
                duration_seconds=result.duration_seconds,
                width=result.width,
                height=result.height,
                fps=result.fps,
                file_size_bytes=result.file_size_bytes,
            )
            self._persist(job)
            self._log(job_id, "Source metadata attached")

    def source_readiness(self) -> dict[str, str]:
        readiness = getattr(self.source_ingestor, "readiness", None)
        return readiness() if readiness else {"status": "stub_ready"}

    def hook_readiness(self) -> dict[str, str]:
        readiness = getattr(self.hook_engine, "readiness", None)
        return readiness() if readiness else {"status": "ready"}

    def review_readiness(self) -> dict[str, str]:
        readiness = getattr(self.review_engine, "readiness", None)
        return readiness() if readiness else {"status": "ready"}

    def composer_readiness(self) -> dict[str, str]:
        readiness = getattr(self.composer, "readiness", None)
        return readiness() if readiness else {"status": "ready"}

    def thumbnail_path(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        path = self._job_dir(job.job_id) / "source" / "thumbnail.jpg"
        if not path.is_file():
            raise PipelineError("THUMBNAIL_NOT_FOUND", "Không tìm thấy thumbnail của công việc.", 404)
        return path

    def hook_path(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        path = self._job_dir(job.job_id) / "hook" / "final_hook.mp4"
        if job.hook_engine.status != StageStatus.COMPLETED or not path.is_file():
            raise PipelineError("HOOK_NOT_FOUND", "Không tìm thấy video Hook của công việc.", 404)
        return path

    def review_asset_path(self, job_id: str, filename: str) -> Path:
        job = self.get_job(job_id)
        allowed = {
            "review.mp4": ("review.mp4", StageStatus.COMPLETED),
            "metadata.json": ("metadata.json", StageStatus.COMPLETED),
            "proxy_metrics.json": ("proxy_metrics.json", StageStatus.COMPLETED),
        }
        if filename not in allowed or job.review_engine.status != allowed[filename][1]:
            raise PipelineError("REVIEW_ASSET_NOT_FOUND", "Không tìm thấy dữ liệu Review của công việc.", 404)
        path = (self._job_dir(job_id) / "review" / allowed[filename][0]).resolve()
        if path.parent != (self._job_dir(job_id) / "review").resolve() or not path.is_file():
            raise PipelineError("REVIEW_ASSET_NOT_FOUND", "Không tìm thấy dữ liệu Review của công việc.", 404)
        return path

    def final_path(self, job_id: str) -> Path:
        job = self.get_job(job_id)
        path = (self._job_dir(job_id) / "final" / "final_video.mp4").resolve()
        if job.status != JobStatus.COMPLETED or path.parent != (self._job_dir(job_id) / "final").resolve() or not path.is_file():
            raise PipelineError("FINAL_ASSET_NOT_FOUND", "Không tìm thấy video cuối của công việc.", 404)
        return path

    def open_final_folder(self, job_id: str) -> None:
        folder = self.final_path(job_id).parent
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as exc:
            raise PipelineError("OPEN_FOLDER_FAILED", "Không thể mở thư mục video cuối.", 500) from exc

    def _report_review_progress(self, job_id: str, stage_id: str, progress: int, message: str) -> None:
        review_ids = ("script", "voice", "footage", "review")
        if stage_id not in review_ids:
            return
        with self._lock:
            job = self._jobs[job_id]
            if job.status == JobStatus.CANCELLED:
                raise JobCancelled
            active_index = review_ids.index(stage_id)
            for previous_id in review_ids[:active_index]:
                previous = next(stage for stage in job.stages if stage.id == previous_id)
                if previous.status != StageStatus.COMPLETED:
                    previous.status = StageStatus.COMPLETED
                    previous.progress = 100
                    previous.finished_at = utc_now()
                    previous.elapsed_seconds = self._elapsed(previous.started_at)
                    previous.message = "Hoàn tất"
            stage = next(stage for stage in job.stages if stage.id == stage_id)
            if stage.status == StageStatus.PENDING:
                stage.status = StageStatus.RUNNING
                stage.started_at = utc_now()
            stage.progress = progress
            stage.message = message
            stage.elapsed_seconds = self._elapsed(stage.started_at)
            job.current_stage = stage_id
            job.status = JobStatus.PROCESSING
            job.review_engine.status = StageStatus.RUNNING
            job.review_engine.progress = round(sum(
                next(item for item in job.stages if item.id == current).progress
                for current in review_ids
            ) / len(review_ids))
            job.review_engine.message = message
            job.progress_percentage = round(sum(item.progress for item in job.stages) / len(job.stages))
            job.elapsed_seconds = self._elapsed(job.started_at)
            self._update_engine_elapsed(job)
            self._persist(job)

    def _apply_review_result(self, job_id: str, result: ReviewEngineResult) -> None:
        with self._lock:
            engine = self._jobs[job_id].review_engine
            engine.proxy_savings = f"{result.saved_percentage:.1f}%".replace(".", ",")
            engine.fallback_used = result.fallback_used
            engine.fallback_reason = result.fallback_reason
            engine.output_duration_seconds = result.duration_seconds
            engine.elapsed_seconds = result.runtime_seconds
            self._persist(self._jobs[job_id])

    def _finish_review(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for stage in job.stages:
                if stage.id in {"script", "voice", "footage", "review"}:
                    stage.status = StageStatus.COMPLETED
                    stage.progress = 100
                    stage.started_at = stage.started_at or utc_now()
                    stage.finished_at = utc_now()
                    stage.elapsed_seconds = self._elapsed(stage.started_at)
                    stage.message = "Hoàn tất"
            job.review_engine.status = StageStatus.COMPLETED
            job.review_engine.progress = 100
            job.review_engine.message = "Review hoàn tất"
            job.review_engine.preview_url = f"/api/jobs/{job_id}/assets/review"
            job.progress_percentage = round(sum(item.progress for item in job.stages) / len(job.stages))
            self._update_engine_elapsed(job)
            self._persist(job)
            self._log(job_id, "Review Engine completed")

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, round(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{size} B"
    def _start_stage(self, job_id: str, index: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if self._cancel_events[job_id].is_set():
                raise JobCancelled
            stage = job.stages[index]
            stage.status = StageStatus.RUNNING
            stage.started_at = utc_now()
            stage.message = "Đang xử lý"
            job.current_stage = stage.id
            job.status = self._job_status_for(stage.id)
            if stage.id == "hook":
                job.hook_engine.status = StageStatus.RUNNING
                job.hook_engine.progress = 0
                job.hook_engine.message = "Đang khởi chạy Hook Engine"
            if stage.id == "script":
                job.review_engine.status = StageStatus.RUNNING
            self._persist(job)
            self._log(job_id, f"Stage started: {stage.id}")

    def _report_progress(self, job_id: str, stage_id: str, progress: int, message: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if job.status == JobStatus.CANCELLED:
                raise JobCancelled
            stage = next(stage for stage in job.stages if stage.id == stage_id)
            stage.progress = progress
            stage.message = message
            stage.elapsed_seconds = self._elapsed(stage.started_at)
            if stage_id == "hook":
                job.hook_engine.progress = progress
                job.hook_engine.message = message
            job.elapsed_seconds = self._elapsed(job.started_at)
            job.progress_percentage = round(sum(item.progress for item in job.stages) / len(job.stages))
            self._update_engine_elapsed(job)
            self._persist(job)

    def _finish_stage(self, job_id: str, index: int) -> None:
        with self._lock:
            job = self._jobs[job_id]
            stage = job.stages[index]
            stage.status = StageStatus.COMPLETED
            stage.progress = 100
            stage.finished_at = utc_now()
            stage.elapsed_seconds = self._elapsed(stage.started_at)
            stage.message = "Hoàn tất"
            job.progress_percentage = round(sum(item.progress for item in job.stages) / len(job.stages))
            if stage.id == "hook":
                job.hook_engine.status = StageStatus.COMPLETED
                job.hook_engine.progress = 100
                job.hook_engine.message = "Hook hoàn tất"
                job.hook_engine.preview_url = f"/api/jobs/{job_id}/assets/hook"
            if stage.id == "review":
                job.review_engine.status = StageStatus.COMPLETED
                job.review_engine.proxy_savings = "42%"
            self._update_engine_elapsed(job)
            self._persist(job)
            self._log(job_id, f"Stage completed: {stage.id}")

    def _mark_cancelled(self, job: VideoJob) -> None:
        if job.status == JobStatus.CANCELLED:
            return
        job.status = JobStatus.CANCELLED
        job.finished_at = utc_now()
        job.elapsed_seconds = self._elapsed(job.started_at)
        job.error = ErrorData(code="JOB_CANCELLED", message="Công việc đã bị hủy.")
        for stage in job.stages:
            if stage.status in {StageStatus.PENDING, StageStatus.RUNNING}:
                stage.status = StageStatus.CANCELLED
                stage.finished_at = utc_now() if stage.started_at else None
                stage.elapsed_seconds = self._elapsed(stage.started_at)
                stage.message = "Đã hủy"
        for engine in (job.hook_engine, job.review_engine):
            if engine.status in {StageStatus.PENDING, StageStatus.RUNNING}:
                engine.status = StageStatus.CANCELLED
        self._persist(job)
        self._log(job.job_id, "Job cancelled")

    def _update_engine_elapsed(self, job: VideoJob) -> None:
        job.hook_engine.elapsed_seconds = sum(stage.elapsed_seconds for stage in job.stages if stage.id == "hook")
        if job.review_engine.status != StageStatus.COMPLETED:
            job.review_engine.elapsed_seconds = sum(
                stage.elapsed_seconds for stage in job.stages if stage.id in {"script", "voice", "footage", "review"}
            )

    def _recover_jobs(self) -> None:
        for metadata in self.workspace.glob("*/metadata/job.json"):
            job_id = metadata.parents[1].name
            if not SAFE_JOB_ID.fullmatch(job_id):
                continue
            try:
                job = VideoJob.model_validate_json(metadata.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 - corruption is tracked, not exposed
                self._corrupted.add(job_id)
                continue
            self._jobs[job_id] = job
            self._cancel_events[job_id] = Event()
            if job.status == JobStatus.QUEUED:
                continue
            if job.status not in TERMINAL_STATUSES:
                job.status = JobStatus.FAILED
                job.finished_at = utc_now()
                job.error = ErrorData(code="INTERRUPTED", message="Backend dừng khi công việc đang chạy.")
                for stage in job.stages:
                    if stage.status == StageStatus.RUNNING:
                        stage.status = StageStatus.FAILED
                        stage.error = job.error
                        stage.finished_at = utc_now()
                self._persist(job)
                self._log(job_id, "Recovered interrupted job as failed")

    def _dispatch_locked(self) -> None:
        self._refresh_queue_positions_locked()
        while len(self._workers) < self.max_concurrent_jobs:
            job = next((item for item in sorted(self._jobs.values(), key=lambda value: value.created_at) if item.status == JobStatus.QUEUED), None)
            if not job:
                break
            job.queue_position = None
            self._persist(job)
            worker = Thread(target=self._run_job, args=(job.job_id,), name=f"pipeline-{job.job_id[:8]}", daemon=True)
            self._workers[job.job_id] = worker
            self._log(job.job_id, "Job dispatched")
            worker.start()
        self._refresh_queue_positions_locked()

    def _refresh_queue_positions_locked(self) -> None:
        queued = sorted((job for job in self._jobs.values() if job.status == JobStatus.QUEUED and job.job_id not in self._workers), key=lambda item: item.created_at)
        positions = {job.job_id: index for index, job in enumerate(queued, 1)}
        for job in self._jobs.values():
            position = positions.get(job.job_id)
            if job.queue_position != position:
                job.queue_position = position
                self._persist(job)

    def queue_readiness(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "status": "ready",
                "running": len(self._workers),
                "queued": sum(job.status == JobStatus.QUEUED and job.job_id not in self._workers for job in self._jobs.values()),
                "max_concurrent": self.max_concurrent_jobs,
            }

    def _persist(self, job: VideoJob) -> None:
        metadata = self._job_dir(job.job_id) / "metadata" / "job.json"
        temporary = metadata.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        for attempt in range(20):
            try:
                os.replace(temporary, metadata)
                break
            except PermissionError:
                if attempt == 19:
                    raise
                sleep(0.005)

    def _log(self, job_id: str, message: str) -> None:
        log_path = self._job_dir(job_id) / "logs" / "pipeline.log"
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"{utc_now()} {message}\n")
        logging.getLogger("pipeline.worker").info("job_id=%s %s", job_id, message.replace("\n", " "))

    def _job_dir(self, job_id: str) -> Path:
        self._validate_job_id(job_id)
        return self.workspace / job_id

    @staticmethod
    def _validate_job_id(job_id: str) -> None:
        if not SAFE_JOB_ID.fullmatch(job_id):
            raise PipelineError("JOB_NOT_FOUND", "Không tìm thấy công việc.", 404)

    @staticmethod
    def _elapsed(started_at: str | None) -> float:
        if not started_at:
            return 0
        started = datetime.fromisoformat(started_at)
        return round((datetime.now(timezone.utc) - started).total_seconds(), 3)

    @staticmethod
    def _job_status_for(stage_id: str) -> JobStatus:
        if stage_id == "download":
            return JobStatus.DOWNLOADING
        if stage_id == "compose":
            return JobStatus.COMPOSING
        if stage_id == "validate":
            return JobStatus.VALIDATING_OUTPUT
        return JobStatus.PROCESSING
