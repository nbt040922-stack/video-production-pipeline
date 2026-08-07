import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from apps.orchestrator.adapters import StubFinalComposer, StubHookEngineAdapter, StubReviewEngineAdapter, StubSourceIngestor
from apps.orchestrator.api import create_app
from apps.orchestrator.accounts import UserStore
from apps.orchestrator.job_manager import JobManager, PipelineError, STAGES
from apps.orchestrator.models import EngineStatus, JobStage, JobStatus, VideoJob, utc_now
from apps.orchestrator.runtime import (
    InstanceLock,
    RuntimeConfig,
    SessionAuth,
    cleanup_jobs,
    configure_logging,
)


class BlockingSource(StubSourceIngestor):
    def __init__(self, release: Event):
        super().__init__(0.001)
        self.release = release

    def download(self, *args, **kwargs):
        if not self.release.wait(5):
            raise RuntimeError("test source timeout")
        return super().download(*args, **kwargs)


def manager(path: Path, source=None, **kwargs) -> JobManager:
    return JobManager(
        path,
        step_delay=0.001,
        source_ingestor=source or StubSourceIngestor(0.001),
        hook_engine=StubHookEngineAdapter(0.001),
        review_engine=StubReviewEngineAdapter(0.001),
        composer=StubFinalComposer(0.001),
        duplicate_window_seconds=kwargs.pop("duplicate_window_seconds", 0),
        **kwargs,
    )


def config(tmp_path: Path, auth: bool = True) -> RuntimeConfig:
    dist = tmp_path / "dist"
    dist.mkdir(exist_ok=True)
    (dist / "index.html").write_text("<html>LAN UI</html>", encoding="utf-8")
    return RuntimeConfig(
        environment="production",
        host="0.0.0.0",
        access_password="internal-pass" if auth else "",
        session_secret="s" * 48 if auth else "",
        database_path=tmp_path / "data" / "pipeline.db",
        frontend_dist=dist,
        log_dir=tmp_path / "logs",
        min_free_disk_gb=0,
        allow_insecure=not auth,
    )


def authenticated_client(tmp_path: Path) -> tuple[TestClient, JobManager]:
    job_manager = manager(tmp_path / "workspace")
    cfg = config(tmp_path)
    store = UserStore(cfg.database_path)
    store.create_user("tester", "Tester", "internal-pass", "admin")
    client = TestClient(create_app(job_manager, cfg, store))
    assert client.post("/api/auth/login", json={"username": "tester", "password": "internal-pass"}).status_code == 200
    return client, job_manager


def test_authentication_login_logout_and_protection(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    store = UserStore(cfg.database_path)
    store.create_user("tester", "Tester", "internal-pass", "user")
    app = create_app(manager(tmp_path / "workspace"), cfg, store)
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/auth/login", json={"username": "tester", "password": "wrong"}).status_code == 401
    login = client.post("/api/auth/login", json={"username": "tester", "password": "internal-pass"})
    assert login.status_code == 200
    assert "HttpOnly" in login.headers["set-cookie"]
    assert "SameSite=strict" in login.headers["set-cookie"]
    assert client.get("/api/jobs").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/jobs").status_code == 401


def test_session_expiry() -> None:
    auth = SessionAuth("s" * 48, ttl_hours=1)
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = auth.issue("u1", 1, issued)
    assert auth.valid(token, issued + timedelta(minutes=59))
    assert not auth.valid(token, issued + timedelta(hours=1))


def test_queue_order_capacity_cancel_and_duplicate(tmp_path: Path) -> None:
    release = Event()
    job_manager = manager(tmp_path, BlockingSource(release), max_concurrent_jobs=1, max_queued_jobs=1, duplicate_window_seconds=60)
    try:
        first = job_manager.create_job("https://youtu.be/first")
        second = job_manager.create_job("https://youtu.be/second")
        assert job_manager.get_job(first.job_id).queue_position is None
        assert job_manager.get_job(second.job_id).queue_position == 1
        assert job_manager.queue_readiness()["running"] == 1
        with pytest.raises(PipelineError) as full:
            job_manager.create_job("https://youtu.be/third")
        assert full.value.code == "QUEUE_FULL"
        with pytest.raises(PipelineError) as duplicate:
            job_manager.create_job("https://youtu.be/first")
        assert duplicate.value.code in {"QUEUE_FULL", "DUPLICATE_JOB"}
        assert job_manager.cancel_job(second.job_id).status == JobStatus.CANCELLED
    finally:
        release.set()
    assert job_manager.wait(first.job_id, 5).status == JobStatus.COMPLETED


def test_duplicate_submission_window(tmp_path: Path) -> None:
    release = Event()
    job_manager = manager(tmp_path, BlockingSource(release), max_queued_jobs=5, duplicate_window_seconds=60)
    try:
        job_manager.create_job("https://youtu.be/same")
        with pytest.raises(PipelineError) as caught:
            job_manager.create_job("https://youtu.be/same")
        assert caught.value.code == "DUPLICATE_JOB"
    finally:
        release.set()


def test_queued_job_recovers_but_interrupted_job_does_not(tmp_path: Path) -> None:
    for job_id, status in (("a" * 32, "queued"), ("b" * 32, "processing"), ("c" * 32, "queued")):
        root = tmp_path / job_id
        for folder in ("source", "hook", "review", "final", "metadata", "logs"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        job = VideoJob(
            job_id=job_id,
            youtube_url="https://youtu.be/" + job_id[0],
            status=status,
            stages=[JobStage(id=stage_id, name=name) for stage_id, name in STAGES],
            created_at=utc_now(),
            hook_engine=EngineStatus(output_filename="final_hook.mp4"),
            review_engine=EngineStatus(output_filename="review.mp4"),
        )
        (root / "metadata" / "job.json").write_text(job.model_dump_json(), encoding="utf-8")

    release = Event()
    recovered = manager(tmp_path, BlockingSource(release))
    try:
        assert recovered.get_job("c" * 32).queue_position == 1
        interrupted = recovered.get_job("b" * 32)
        assert interrupted.status == JobStatus.FAILED
        assert interrupted.error.code == "INTERRUPTED"
    finally:
        release.set()
    assert recovered.wait("a" * 32, 5).status == JobStatus.COMPLETED
    assert recovered.wait("c" * 32, 5).status == JobStatus.COMPLETED


def test_static_spa_api_precedence_and_readiness(tmp_path: Path) -> None:
    cfg = config(tmp_path, auth=False)
    client = TestClient(create_app(manager(tmp_path / "workspace"), cfg))
    assert "LAN UI" in client.get("/").text
    assert "LAN UI" in client.get("/jobs/history").text
    assert client.get("/api/not-real").status_code == 404
    assert client.get("/api/readiness").json()["status"] == "ready"

    missing = RuntimeConfig(
        environment="development",
        frontend_dist=tmp_path / "missing",
        log_dir=tmp_path / "logs2",
        min_free_disk_gb=10**9,
        allow_insecure=True,
    )
    degraded = TestClient(create_app(manager(tmp_path / "other"), missing))
    assert degraded.get("/").status_code == 503
    report = degraded.get("/api/readiness").json()
    assert report["status"] == "degraded"
    assert report["checks"]["frontend"] is False
    assert report["checks"]["disk"] is False


def test_final_asset_range_and_remote_open_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, job_manager = authenticated_client(tmp_path)
    created = client.post("/api/jobs", json={"youtube_url": "https://youtu.be/range"}).json()
    completed = job_manager.wait(created["job_id"], 5)
    response = client.get(f"/api/jobs/{completed.job_id}/assets/final", headers={"Range": "bytes=0-7"})
    assert response.status_code in {200, 206}
    assert len(response.content) <= 24

    monkeypatch.setattr("apps.orchestrator.api.is_local_client", lambda _host: False)
    assert client.post(f"/api/jobs/{completed.job_id}/open-folder").status_code == 403


def test_instance_lock_and_stale_lock(tmp_path: Path) -> None:
    path = tmp_path / "server.lock"
    first = InstanceLock(path)
    first.acquire()
    with pytest.raises(RuntimeError):
        InstanceLock(path).acquire()
    first.release()
    path.write_text("99999999", encoding="ascii")
    stale = InstanceLock(path)
    stale.acquire()
    stale.release()


def test_retention_dry_run_apply_and_path_safety(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    old = workspace / ("c" * 32)
    metadata = old / "metadata"
    metadata.mkdir(parents=True)
    payload = {
        "status": "completed",
        "created_at": "2025-01-01T00:00:00+00:00",
        "finished_at": "2025-01-02T00:00:00+00:00",
    }
    (metadata / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    (old / "video.bin").write_bytes(b"1234")
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    preview = cleanup_jobs(workspace, 7, 100, dry_run=True, now=now)
    assert preview["deleted_job_ids"] == ["c" * 32]
    assert preview["completed_jobs"] == 1
    assert preview["completed_over_limit"] == 0
    assert old.exists()
    applied = cleanup_jobs(workspace, 7, 100, dry_run=False, now=now)
    assert applied["reclaimed_bytes"] >= 4
    assert not old.exists()

    outside = tmp_path / "outside"
    outside.mkdir()
    link = workspace / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    assert cleanup_jobs(workspace, 0, 100, dry_run=False, now=now)["deleted_job_ids"] == []
    assert outside.exists()


def test_logs_do_not_contain_auth_secrets(tmp_path: Path) -> None:
    cfg = config(tmp_path)
    configure_logging(cfg.log_dir)
    store = UserStore(cfg.database_path)
    store.create_user("tester", "Tester", "internal-pass", "user")
    client = TestClient(create_app(manager(tmp_path / "workspace"), cfg, store))
    client.post("/api/auth/login", json={"username": "tester", "password": "internal-pass"})
    for logger_name in ("pipeline.server", "pipeline.access", "pipeline.worker"):
        logging.getLogger(logger_name).handlers[0].flush()
    text = "".join(path.read_text(encoding="utf-8") for path in cfg.log_dir.glob("*.log"))
    assert "internal-pass" not in text
    assert "s" * 48 not in text


def test_production_rejects_missing_auth(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="PIPELINE_SESSION_SECRET"):
        RuntimeConfig(environment="production", host="0.0.0.0", frontend_dist=tmp_path).validate()


def test_operational_scripts_are_idempotent_and_scoped() -> None:
    install = Path("scripts/install-background-task.ps1").read_text(encoding="utf-8")
    uninstall = Path("scripts/uninstall-background-task.ps1").read_text(encoding="utf-8")
    firewall = Path("scripts/allow-lan-firewall.ps1").read_text(encoding="utf-8")
    stop = Path("scripts/stop-background-task.ps1").read_text(encoding="utf-8")
    assert "Register-ScheduledTask" in install and "-Force" in install and "IgnoreNew" in install
    assert "Get-ScheduledTask" in uninstall and "Unregister-ScheduledTask" in uninstall
    assert 'Video Production Pipeline LAN (TCP)' in firewall
    assert "-RemoteAddress LocalSubnet" in firewall
    assert "Remove-NetFirewallRule" in firewall and "New-NetFirewallRule" in firewall
    assert "Win32_Process" in stop and "CommandLine" in stop
    for script in (Path("scripts/production-watchdog.ps1"), Path("scripts/stop-background-task.ps1"), Path("scripts/status-background-task.ps1")):
        assert 'Join-Path $Root ".env"' in script.read_text(encoding="utf-8")

    launcher = Path("CHAY_LAN.cmd").read_text(encoding="utf-8")
    assert "PIPELINE_ACCESS_PASSWORD" not in launcher
    assert "generate-secret" in launcher
    assert "migrate-m08" in launcher and "create-admin" in launcher
    assert "allow-lan-firewall.ps1" in launcher
    assert "install-background-task.ps1" in launcher
    assert "/api/health" in launcher
    assert "-RemoteAddress Any" not in launcher
