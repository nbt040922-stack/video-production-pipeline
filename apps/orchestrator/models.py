from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_youtube_url(value: str) -> bool:
    try:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"}:
            return False
        if parsed.hostname not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
            return False
        query = parse_qs(parsed.query)
        if query.get("list"):
            return False
        if parsed.hostname == "youtu.be":
            return len(parsed.path) > 1
        return bool(query.get("v")) or parsed.path.startswith(("/shorts/", "/live/"))
    except ValueError:
        return False


class JobStatus(StrEnum):
    QUEUED = "queued"
    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPOSING = "composing"
    VALIDATING_OUTPUT = "validating_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ErrorData(BaseModel):
    code: str
    message: str
    details: Any = None


class JobStage(BaseModel):
    id: str
    name: str
    status: StageStatus = StageStatus.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = 0
    message: str = "Đang chờ"
    error: ErrorData | None = None


class EngineStatus(BaseModel):
    status: StageStatus = StageStatus.PENDING
    elapsed_seconds: float = 0
    output_filename: str
    proxy_savings: str | None = None


class SourceMetadata(BaseModel):
    title: str
    channel: str
    duration: str
    status: str = "ready"
    thumbnail_url: str | None = None
    youtube_video_id: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    file_size_bytes: int | None = None


class OutputMetadata(BaseModel):
    filename: str
    resolution: str
    duration: str
    file_size: str
    relative_path: str


class VideoJob(BaseModel):
    job_id: str
    youtube_url: str
    status: JobStatus
    progress_percentage: int = 0
    current_stage: str | None = None
    stages: list[JobStage]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_seconds: float = 0
    error: ErrorData | None = None
    source: SourceMetadata | None = None
    hook_engine: EngineStatus
    review_engine: EngineStatus
    output: OutputMetadata | None = None
    attempt: int = 1
    retry_of: str | None = None


class CreateJobRequest(BaseModel):
    youtube_url: str

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, value: str) -> str:
        value = value.strip()
        if not is_youtube_url(value):
            raise ValueError("Liên kết YouTube không hợp lệ.")
        return value
