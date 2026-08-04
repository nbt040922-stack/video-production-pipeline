from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .job_manager import JobManager, PipelineError
from .models import CreateJobRequest


def create_app(manager: JobManager | None = None) -> FastAPI:
    job_manager = manager or JobManager(os.getenv("PIPELINE_WORKSPACE", "workspace"))
    app = FastAPI(title="Video Production Pipeline API", version="0.1.0")
    app.state.job_manager = job_manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173")],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(PipelineError)
    async def pipeline_error_handler(_request: Request, exc: PipelineError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "INVALID_YOUTUBE_URL",
                    "message": "Liên kết YouTube không hợp lệ.",
                    "details": None,
                }
            },
        )

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "mode": "stub",
            "workspace": str(job_manager.workspace),
            "dependencies": {
                "source_ingestor": "stub_ready",
                "hook_engine": "stub_ready",
                "review_engine": "stub_ready",
                "final_composer": "stub_ready",
            },
        }

    @app.post("/api/jobs", status_code=201)
    def create_job(request: CreateJobRequest) -> dict:
        return job_manager.create_job(request.youtube_url).model_dump(mode="json")

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return job_manager.get_job(job_id).model_dump(mode="json")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = job_manager.cancel_job(job_id)
        return {"job_id": job.job_id, "status": job.status}

    @app.post("/api/jobs/{job_id}/retry", status_code=201)
    def retry_job(job_id: str) -> dict:
        return job_manager.retry_job(job_id).model_dump(mode="json")

    return app


app = create_app()
