from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .accounts import AccountError, User, UserStore, audit_event
from .job_manager import JobManager, PipelineError
from .models import CreateJobRequest, VideoJob
from .runtime import RuntimeConfig, SessionAuth, is_local_client, readiness


class LoginRequest(BaseModel):
    username: str
    password: str


class CreateUserRequest(BaseModel):
    username: str
    display_name: str
    password: str
    role: str = "user"


class PasswordRequest(BaseModel):
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RoleRequest(BaseModel):
    role: str


def create_app(manager: JobManager | None = None, config: RuntimeConfig | None = None,
               user_store: UserStore | None = None) -> FastAPI:
    runtime = config or RuntimeConfig.from_env()
    runtime.validate()
    job_manager = manager or JobManager(
        os.getenv("PIPELINE_WORKSPACE", "workspace"),
        max_active_jobs_per_user=runtime.max_active_jobs_per_user,
    )
    store = user_store or UserStore(runtime.database_path)
    store.initialize()
    auth = SessionAuth(runtime.session_secret, runtime.session_ttl_hours) if runtime.auth_enabled else None
    app = FastAPI(title="Video Production Pipeline API", version="0.3.0")
    app.state.job_manager = job_manager
    app.state.runtime_config = runtime
    app.state.user_store = store

    if runtime.environment != "production":
        origins = [item.strip() for item in os.getenv(
            "PIPELINE_DEV_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
        ).split(",") if item.strip()]
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    public_api = {"/api/health", "/api/readiness", "/api/auth/login", "/api/auth/session", "/api/auth/me"}

    @app.middleware("http")
    async def session_and_access_log(request: Request, call_next):
        request.state.user = None
        if auth:
            payload = auth.decode(request.cookies.get(auth.cookie_name))
            if payload:
                user = store.get_by_id(payload["uid"], include_disabled=True)
                if user and user.enabled and user.session_version == payload["sv"]:
                    request.state.user = user
            if request.url.path.startswith("/api/") and request.url.path not in public_api and not request.state.user:
                return _error(401, "AUTH_REQUIRED", "Cần đăng nhập.")
        response = await call_next(request)
        logging.getLogger("pipeline.access").info(
            "%s %s %s client=%s user=%s", request.method, request.url.path, response.status_code,
            request.client.host if request.client else "unknown",
            request.state.user.username if request.state.user else "anonymous",
        )
        return response

    @app.exception_handler(PipelineError)
    async def pipeline_error_handler(_request: Request, exc: PipelineError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code,
                            content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}})

    @app.exception_handler(AccountError)
    async def account_error_handler(_request: Request, exc: AccountError) -> JSONResponse:
        status = 404 if exc.code == "USER_NOT_FOUND" else 409 if exc.code in {"USERNAME_EXISTS", "LAST_ADMIN"} else 400
        return _error(status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        return _error(422, "INVALID_YOUTUBE_URL", "Liên kết YouTube không hợp lệ.")

    def current_user(request: Request) -> User | None:
        return request.state.user

    def require_admin(request: Request) -> User:
        user = current_user(request)
        if not user or user.role != "admin":
            raise PipelineError("ADMIN_REQUIRED", "Chỉ quản trị viên được thực hiện thao tác này.", 403)
        return user

    def owned_job(request: Request, job_id: str) -> VideoJob:
        job = job_manager.get_job(job_id)
        user = current_user(request)
        if auth and (not user or (user.role != "admin" and job.owner_user_id != user.id)):
            raise PipelineError("JOB_NOT_FOUND", "Không tìm thấy công việc.", 404)
        return job

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/readiness")
    def get_readiness() -> dict:
        return readiness(runtime, job_manager.workspace, job_manager, store)

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, request: Request):
        if not auth:
            return {"authenticated": True, "user": _local_user()}
        if store.count() == 0:
            return _error(503, "USER_SETUP_REQUIRED", "Chưa có tài khoản admin. Hãy chạy lệnh create-admin trên máy chủ.")
        try:
            user = store.authenticate(payload.username, payload.password)
        except AccountError as exc:
            audit_event("login", target=payload.username.strip().lower(), client_ip=_client_ip(request), success=False)
            return _error(401 if exc.code != "ACCOUNT_DISABLED" else 403, exc.code, exc.message)
        audit_event("login", actor=user, client_ip=_client_ip(request))
        response = JSONResponse({"authenticated": True, "user": user.safe_dict()})
        response.set_cookie(auth.cookie_name, auth.issue(user.id, user.session_version),
                            max_age=runtime.session_ttl_hours * 3600, httponly=True,
                            samesite="strict", secure=False, path="/")
        return response

    @app.get("/api/auth/session")
    @app.get("/api/auth/me")
    def session(request: Request) -> dict:
        user = current_user(request)
        return {"authenticated": not auth or bool(user), "user": user.safe_dict() if user else (_local_user() if not auth else None)}

    @app.post("/api/auth/logout")
    def logout(request: Request):
        audit_event("logout", actor=current_user(request), client_ip=_client_ip(request))
        response = JSONResponse({"authenticated": False})
        if auth:
            response.delete_cookie(auth.cookie_name, path="/")
        return response

    @app.post("/api/auth/change-password")
    def change_password(payload: ChangePasswordRequest, request: Request):
        user = current_user(request)
        if not auth or not user:
            raise PipelineError("AUTH_REQUIRED", "Cần đăng nhập.", 401)
        try:
            store.authenticate(user.username, payload.current_password)
        except AccountError:
            raise PipelineError("INVALID_CURRENT_PASSWORD", "Mật khẩu hiện tại không đúng.", 400)
        updated = store.reset_password(user.username, payload.new_password)
        audit_event("user.change_password", actor=updated, target=updated.username, client_ip=_client_ip(request))
        response = JSONResponse({"user": updated.safe_dict()})
        response.set_cookie(auth.cookie_name, auth.issue(updated.id, updated.session_version),
                            max_age=runtime.session_ttl_hours * 3600, httponly=True,
                            samesite="strict", secure=False, path="/")
        return response

    @app.get("/api/jobs")
    def list_jobs(request: Request, owner: str | None = None, status: str | None = None) -> list[dict]:
        user = current_user(request)
        if auth and user and user.role != "admin":
            return job_manager.list_jobs(owner_user_id=user.id, status=status, restrict_owner=True)
        return job_manager.list_jobs(owner_username=owner, status=status)

    @app.post("/api/jobs", status_code=201)
    def create_job(payload: CreateJobRequest, request: Request) -> dict:
        user = current_user(request)
        job = job_manager.create_job(payload.youtube_url,
                                     owner_user_id=user.id if user else None,
                                     owner_username=user.username if user else "legacy")
        audit_event("job.create", actor=user, target=job.job_id, client_ip=_client_ip(request))
        return job.model_dump(mode="json")

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict:
        return owned_job(request, job_id).model_dump(mode="json")

    def asset(request: Request, job_id: str, path: Path, media_type: str,
              filename: str | None = None) -> FileResponse:
        owned_job(request, job_id)
        return FileResponse(path, media_type=media_type, filename=filename)

    @app.get("/api/jobs/{job_id}/assets/thumbnail")
    def get_thumbnail(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.thumbnail_path(job_id), "image/jpeg")

    @app.get("/api/jobs/{job_id}/assets/hook")
    def get_hook(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.hook_path(job_id), "video/mp4")

    @app.get("/api/jobs/{job_id}/assets/review")
    def get_review(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.review_asset_path(job_id, "review.mp4"), "video/mp4")

    @app.get("/api/jobs/{job_id}/assets/final")
    def get_final(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.final_path(job_id), "video/mp4")

    @app.get("/api/jobs/{job_id}/assets/final/download")
    def download_final(job_id: str, request: Request) -> FileResponse:
        response = asset(request, job_id, job_manager.final_path(job_id), "video/mp4", "final_video.mp4")
        audit_event("job.download", actor=current_user(request), target=job_id, client_ip=_client_ip(request))
        return response

    @app.post("/api/jobs/{job_id}/open-folder")
    def open_final_folder(job_id: str, request: Request) -> dict[str, str]:
        owned_job(request, job_id)
        if not is_local_client(_client_ip(request)):
            raise PipelineError("LOCAL_ONLY", "Chỉ máy chủ mới có thể mở thư mục.", 403)
        job_manager.open_final_folder(job_id)
        return {"status": "opened"}

    @app.get("/api/jobs/{job_id}/assets/review-metadata")
    def get_review_metadata(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.review_asset_path(job_id, "metadata.json"), "application/json")

    @app.get("/api/jobs/{job_id}/assets/proxy-metrics")
    def get_proxy_metrics(job_id: str, request: Request) -> FileResponse:
        return asset(request, job_id, job_manager.review_asset_path(job_id, "proxy_metrics.json"), "application/json")

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, request: Request) -> dict:
        owned_job(request, job_id)
        job = job_manager.cancel_job(job_id)
        audit_event("job.cancel", actor=current_user(request), target=job_id, client_ip=_client_ip(request))
        return {"job_id": job.job_id, "status": job.status}

    @app.post("/api/jobs/{job_id}/retry", status_code=201)
    def retry_job(job_id: str, request: Request) -> dict:
        owned_job(request, job_id)
        job = job_manager.retry_job(job_id)
        audit_event("job.retry", actor=current_user(request), target=job.job_id, client_ip=_client_ip(request))
        return job.model_dump(mode="json")

    @app.get("/api/admin/users")
    def list_users(request: Request) -> list[dict]:
        require_admin(request)
        return [user.safe_dict() for user in store.list_users()]

    @app.post("/api/admin/users", status_code=201)
    def create_user(payload: CreateUserRequest, request: Request) -> dict:
        actor = require_admin(request)
        user = store.create_user(payload.username, payload.display_name, payload.password, payload.role)
        audit_event("user.create", actor=actor, target=user.username, client_ip=_client_ip(request))
        return user.safe_dict()

    @app.post("/api/admin/users/{username}/enable")
    def enable_user(username: str, request: Request) -> dict:
        actor = require_admin(request)
        user = store.set_enabled(username, True)
        audit_event("user.enable", actor=actor, target=user.username, client_ip=_client_ip(request))
        return user.safe_dict()

    @app.post("/api/admin/users/{username}/disable")
    def disable_user(username: str, request: Request) -> dict:
        actor = require_admin(request)
        user = store.set_enabled(username, False)
        audit_event("user.disable", actor=actor, target=user.username, client_ip=_client_ip(request))
        return user.safe_dict()

    @app.post("/api/admin/users/{username}/reset-password")
    def reset_password(username: str, payload: PasswordRequest, request: Request) -> dict:
        actor = require_admin(request)
        user = store.reset_password(username, payload.password)
        audit_event("user.reset_password", actor=actor, target=user.username, client_ip=_client_ip(request))
        return user.safe_dict()

    @app.post("/api/admin/users/{username}/set-role")
    def set_role(username: str, payload: RoleRequest, request: Request) -> dict:
        actor = require_admin(request)
        user = store.set_role(username, payload.role)
        audit_event("user.set_role", actor=actor, target=user.username, client_ip=_client_ip(request))
        return user.safe_dict()

    @app.get("/{full_path:path}")
    def frontend(full_path: str):
        if full_path.startswith("api/"):
            return _error(404, "NOT_FOUND", "Không tìm thấy API.")
        index = runtime.frontend_dist / "index.html"
        if not index.is_file():
            return _error(503, "FRONTEND_BUILD_MISSING", "Chưa có frontend production build.")
        frontend_root = runtime.frontend_dist.resolve()
        candidate = (frontend_root / full_path).resolve()
        if full_path and candidate.is_relative_to(frontend_root) and candidate.is_file():
            return FileResponse(candidate)
        if full_path and Path(full_path).suffix:
            return _error(404, "ASSET_NOT_FOUND", "Không tìm thấy tệp frontend.")
        return FileResponse(index)

    return app


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": None}})


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _local_user() -> dict[str, str | bool | None]:
    return {"id": "local", "username": "local", "display_name": "Máy cục bộ", "role": "admin",
            "enabled": True, "created_at": "", "updated_at": "", "last_login_at": None}


app = create_app()
