from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

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
        source_readiness = job_manager.source_readiness()
        hook_readiness = job_manager.hook_readiness()
        review_readiness = job_manager.review_readiness()
        composer_readiness = job_manager.composer_readiness()
        return {
            "status": "ok" if all(item["status"] != "missing_dependency" for item in (source_readiness, hook_readiness, review_readiness, composer_readiness)) else "degraded",
            "mode": "real_pipeline",
            "workspace": str(job_manager.workspace),
            "dependencies": {
                "source_ingestor": source_readiness,
                "hook_engine": hook_readiness,
                "review_engine": review_readiness,
                "final_composer": composer_readiness,
            },
        }

    @app.post("/api/jobs", status_code=201)
    def create_job(request: CreateJobRequest) -> dict:
        return job_manager.create_job(request.youtube_url).model_dump(mode="json")

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return job_manager.get_job(job_id).model_dump(mode="json")

    @app.get("/api/jobs/{job_id}/assets/thumbnail")
    def get_thumbnail(job_id: str) -> FileResponse:
        return FileResponse(
            job_manager.thumbnail_path(job_id),
            media_type="image/jpeg",
            filename="thumbnail.jpg",
        )

    @app.get("/api/jobs/{job_id}/assets/hook")
    def get_hook(job_id: str) -> FileResponse:
        return FileResponse(job_manager.hook_path(job_id), media_type="video/mp4")

    @app.get("/api/jobs/{job_id}/assets/review")
    def get_review(job_id: str) -> FileResponse:
        return FileResponse(job_manager.review_asset_path(job_id, "review.mp4"), media_type="video/mp4")

    @app.get("/api/jobs/{job_id}/assets/final")
    def get_final(job_id: str) -> FileResponse:
        return FileResponse(job_manager.final_path(job_id), media_type="video/mp4")

    @app.post("/api/jobs/{job_id}/open-folder")
    def open_final_folder(job_id: str) -> dict[str, str]:
        job_manager.open_final_folder(job_id)
        return {"status": "opened"}

    @app.get("/api/jobs/{job_id}/assets/review-metadata")
    def get_review_metadata(job_id: str) -> FileResponse:
        return FileResponse(job_manager.review_asset_path(job_id, "metadata.json"), media_type="application/json")

    @app.get("/api/jobs/{job_id}/assets/proxy-metrics")
    def get_proxy_metrics(job_id: str) -> FileResponse:
        return FileResponse(job_manager.review_asset_path(job_id, "proxy_metrics.json"), media_type="application/json")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = job_manager.cancel_job(job_id)
        return {"job_id": job.job_id, "status": job.status}

    @app.post("/api/jobs/{job_id}/retry", status_code=201)
    def retry_job(job_id: str) -> dict:
        return job_manager.retry_job(job_id).model_dump(mode="json")

    return app


app = create_app()
