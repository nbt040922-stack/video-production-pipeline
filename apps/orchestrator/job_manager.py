from __future__ import annotations

import json
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
    HookEngineAdapter,
    JobCancelled,
    ReviewEngineAdapter,
    SourceIngestor,
    StubFinalComposer,
    StubHookEngineAdapter,
    StubReviewEngineAdapter,
    StubSourceIngestor,
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
        hook_engine: HookEngineAdapter | None = None,
        review_engine: ReviewEngineAdapter | None = None,
        composer: FinalComposer | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._jobs: dict[str, VideoJob] = {}
        self._corrupted: set[str] = set()
        self._cancel_events: dict[str, Event] = {}
        self._workers: dict[str, Thread] = {}
        self.step_delay = step_delay
        self.source_ingestor = source_ingestor or StubSourceIngestor(step_delay)
        self.hook_engine = hook_engine or StubHookEngineAdapter(step_delay)
        self.review_engine = review_engine or StubReviewEngineAdapter(step_delay)
        self.composer = composer or StubFinalComposer(step_delay)
        self._recover_jobs()

    def create_job(self, youtube_url: str, retry_of: str | None = None, attempt: int = 1) -> VideoJob:
        with self._lock:
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
            worker = Thread(target=self._run_job, args=(job_id,), name=f"pipeline-{job_id[:8]}", daemon=True)
            self._workers[job_id] = worker
            worker.start()
            return job.model_copy(deep=True)

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
            self._cancel_events[job_id].set()
            self._mark_cancelled(self._jobs[job_id])
            return self._jobs[job_id].model_copy(deep=True)

    def retry_job(self, job_id: str) -> VideoJob:
        original = self.get_job(job_id)
        if original.status != JobStatus.FAILED:
            raise PipelineError("INVALID_JOB_STATE", "Chỉ có thể thử lại công việc thất bại.", 409)
        return self.create_job(original.youtube_url, retry_of=original.job_id, attempt=original.attempt + 1)

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
            if cancel.wait(self.step_delay):
                raise JobCancelled

            with self._lock:
                job = self._jobs[job_id]
                job.source = SourceMetadata(
                    title="Bodycam Footage Review — Local Backend",
                    channel="Local pipeline fixture",
                    duration="12:48",
                )
                self._persist(job)

            for index, stage in enumerate(STAGES):
                self._start_stage(job_id, index)
                self._run_stage(job_id, stage[0], cancel)
                self._finish_stage(job_id, index)

            with self._lock:
                job = self._jobs[job_id]
                output_path = self._job_dir(job_id) / "final" / "final_video.mp4"
                job.status = JobStatus.COMPLETED
                job.current_stage = None
                job.progress_percentage = 100
                job.finished_at = utc_now()
                job.elapsed_seconds = self._elapsed(job.started_at)
                job.output = OutputMetadata(
                    filename=output_path.name,
                    resolution="1920×1080",
                    duration="13:02",
                    file_size=f"{output_path.stat().st_size} B",
                    relative_path=f"{job_id}/final/{output_path.name}",
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
                error = ErrorData(code="WORKER_ERROR", message="Xử lý công việc thất bại.")
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
                if job.hook_engine.status == StageStatus.RUNNING:
                    job.hook_engine.status = StageStatus.FAILED
                self._persist(job)
                self._log(job_id, f"Worker failed: {exc}\n{traceback.format_exc()}")

    def _run_stage(self, job_id: str, stage_id: str, cancel: Event) -> None:
        workspace = self._job_dir(job_id)
        progress = lambda value, message: self._report_progress(job_id, stage_id, value, message)
        job = self.get_job(job_id)
        fail = "fixture=fail" in job.youtube_url and job.attempt == 1
        actions = {
            "download": lambda: self.source_ingestor.download(workspace, cancel, progress),
            "thumbnail": lambda: self.source_ingestor.prepare_thumbnail(workspace, cancel, progress),
            "hook": lambda: self.hook_engine.generate(workspace, cancel, progress),
            "script": lambda: self.review_engine.write_review(workspace, cancel, progress, fail),
            "voice": lambda: self.review_engine.generate_voice(workspace, cancel, progress),
            "footage": lambda: self.review_engine.select_footage(workspace, cancel, progress),
            "review": lambda: self.review_engine.render(workspace, cancel, progress),
            "compose": lambda: self.composer.compose(workspace, cancel, progress),
            "validate": lambda: self.composer.validate(workspace, cancel, progress),
        }
        actions[stage_id]()

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
