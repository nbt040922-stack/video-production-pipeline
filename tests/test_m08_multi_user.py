import json
import logging
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from apps.orchestrator.accounts import AccountError, UserStore, migrate_m08, verify_password
from apps.orchestrator.adapters import StubFinalComposer, StubHookEngineAdapter, StubReviewEngineAdapter, StubSourceIngestor
from apps.orchestrator.api import create_app
from apps.orchestrator.job_manager import JobManager, PipelineError
from apps.orchestrator.runtime import RuntimeConfig, configure_logging


class BlockingSource(StubSourceIngestor):
    def __init__(self, release: Event):
        super().__init__(0.001)
        self.release = release

    def download(self, *args, **kwargs):
        self.release.wait(5)
        return super().download(*args, **kwargs)


class FailingSource(StubSourceIngestor):
    def __init__(self):
        super().__init__(0.001)

    def download(self, *args, **kwargs):
        raise RuntimeError("expected failure")


def manager(path: Path, source=None, limit=5) -> JobManager:
    return JobManager(path, step_delay=0.001, source_ingestor=source or StubSourceIngestor(0.001),
                      hook_engine=StubHookEngineAdapter(0.001), review_engine=StubReviewEngineAdapter(0.001),
                      composer=StubFinalComposer(0.001), duplicate_window_seconds=0,
                      max_active_jobs_per_user=limit)


def configured_app(tmp_path: Path):
    cfg = RuntimeConfig(environment="production", host="0.0.0.0", session_secret="s" * 48,
                        database_path=tmp_path / "data" / "pipeline.db", frontend_dist=tmp_path / "dist",
                        min_free_disk_gb=0)
    store = UserStore(cfg.database_path)
    admin = store.create_user("admin", "Quản trị", "admin-pass-123", "admin")
    alice = store.create_user("alice", "Alice", "alice-pass-123")
    bob = store.create_user("bob", "Bob", "bob-pass-123")
    jobs = manager(tmp_path / "workspace")
    return create_app(jobs, cfg, store), jobs, store, {"admin": admin, "alice": alice, "bob": bob}


def login(client: TestClient, username: str) -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": f"{username}-pass-123"})
    assert response.status_code == 200


def test_passwords_are_salted_and_never_returned(tmp_path: Path) -> None:
    store = UserStore(tmp_path / "pipeline.db")
    first = store.create_user("first", "First", "same-password")
    store.create_user("second", "Second", "same-password")
    with store._connect() as connection:
        hashes = [row[0] for row in connection.execute("SELECT password_hash FROM users ORDER BY username")]
    assert hashes[0] != hashes[1]
    assert verify_password("same-password", hashes[0])
    assert "password" not in first.safe_dict()
    with pytest.raises(AccountError) as duplicate:
        store.create_user("FIRST", "Duplicate", "another-password")
    assert duplicate.value.code == "USERNAME_EXISTS"


def test_readiness_requires_initial_user_setup(tmp_path: Path) -> None:
    cfg = RuntimeConfig(environment="production", host="0.0.0.0", session_secret="s" * 48,
                        database_path=tmp_path / "data" / "pipeline.db", frontend_dist=tmp_path / "dist",
                        min_free_disk_gb=0)
    client = TestClient(create_app(manager(tmp_path / "workspace"), cfg))
    report = client.get("/api/readiness").json()
    assert report["status"] == "degraded"
    assert report["checks"]["database_ready"] is True
    assert report["checks"]["user_setup_ready"] is False
    assert report["user_setup_required"] is True
    assert client.get("/api/auth/me").json() == {"authenticated": False, "user": None}
    assert client.post("/api/auth/login", json={"username": "admin", "password": "not-configured"}).status_code == 503


def test_job_isolation_admin_visibility_and_legacy_policy(tmp_path: Path) -> None:
    app, jobs, _store, _users = configured_app(tmp_path)
    legacy = jobs.create_job("https://youtu.be/legacy")
    alice, bob, admin = TestClient(app), TestClient(app), TestClient(app)
    login(alice, "alice")
    login(bob, "bob")
    login(admin, "admin")

    created = alice.post("/api/jobs", json={"youtube_url": "https://youtu.be/alice"}).json()
    assert [job["job_id"] for job in alice.get("/api/jobs").json()] == [created["job_id"]]
    assert bob.get(f"/api/jobs/{created['job_id']}").status_code == 404
    assert bob.get(f"/api/jobs/{created['job_id']}/assets/final").status_code == 404
    assert bob.post(f"/api/jobs/{created['job_id']}/cancel").status_code == 404
    admin_ids = {job["job_id"] for job in admin.get("/api/jobs").json()}
    assert {legacy.job_id, created["job_id"]}.issubset(admin_ids)
    assert [job["job_id"] for job in admin.get("/api/jobs?owner=alice").json()] == [created["job_id"]]
    assert alice.get(f"/api/jobs/{legacy.job_id}").status_code == 404


def test_disable_and_password_reset_revoke_existing_sessions(tmp_path: Path) -> None:
    app, _jobs, store, _users = configured_app(tmp_path)
    client = TestClient(app)
    login(client, "alice")
    assert client.get("/api/jobs").status_code == 200
    store.set_enabled("alice", False)
    assert client.get("/api/jobs").status_code == 401
    store.set_enabled("alice", True)
    login(client, "alice")
    store.reset_password("alice", "new-alice-pass")
    assert client.get("/api/jobs").status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-123"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "alice", "password": "new-alice-pass"}).status_code == 200


def test_user_can_change_own_password_and_keep_new_session(tmp_path: Path) -> None:
    app, _jobs, _store, _users = configured_app(tmp_path)
    client = TestClient(app)
    login(client, "alice")
    assert client.post("/api/auth/change-password", json={
        "current_password": "wrong-password", "new_password": "alice-new-pass"
    }).status_code == 400
    changed = client.post("/api/auth/change-password", json={
        "current_password": "alice-pass-123", "new_password": "alice-new-pass"
    })
    assert changed.status_code == 200
    assert client.get("/api/auth/me").json()["user"]["username"] == "alice"
    assert TestClient(app).post("/api/auth/login", json={
        "username": "alice", "password": "alice-pass-123"
    }).status_code == 401


def test_user_management_requires_admin_and_never_returns_hash(tmp_path: Path) -> None:
    app, _jobs, _store, _users = configured_app(tmp_path)
    alice, admin = TestClient(app), TestClient(app)
    login(alice, "alice")
    login(admin, "admin")
    assert alice.get("/api/admin/users").status_code == 403
    created = admin.post("/api/admin/users", json={
        "username": "charlie", "display_name": "Charlie", "password": "charlie-pass-123", "role": "user"
    })
    assert created.status_code == 201
    assert "password" not in json.dumps(created.json())
    assert admin.post("/api/admin/users", json={
        "username": "CHARLIE", "display_name": "Duplicate", "password": "charlie-pass-456"
    }).status_code == 409
    assert admin.post("/api/admin/users/charlie/disable").status_code == 200
    assert TestClient(app).post("/api/auth/login", json={
        "username": "charlie", "password": "charlie-pass-123"
    }).status_code == 403


def test_retry_authorization_for_failed_job(tmp_path: Path) -> None:
    cfg = RuntimeConfig(environment="production", host="0.0.0.0", session_secret="s" * 48,
                        database_path=tmp_path / "pipeline.db", min_free_disk_gb=0)
    store = UserStore(cfg.database_path)
    admin = store.create_user("admin", "Admin", "admin-pass-123", "admin")
    alice = store.create_user("alice", "Alice", "alice-pass-123")
    bob = store.create_user("bob", "Bob", "bob-pass-123")
    jobs = manager(tmp_path / "workspace", FailingSource())
    failed = jobs.create_job("https://youtu.be/fail", owner_user_id=bob.id, owner_username=bob.username)
    jobs.wait(failed.job_id, 5)
    app = create_app(jobs, cfg, store)
    alice_client, admin_client = TestClient(app), TestClient(app)
    login(alice_client, "alice")
    login(admin_client, "admin")
    assert alice_client.post(f"/api/jobs/{failed.job_id}/retry").status_code == 404
    retried = admin_client.post(f"/api/jobs/{failed.job_id}/retry")
    assert retried.status_code == 201
    assert retried.json()["owner_user_id"] == bob.id


def test_audit_log_is_json_and_contains_no_secrets(tmp_path: Path) -> None:
    logger = logging.getLogger("pipeline.audit")
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    configure_logging(tmp_path / "logs")
    app, _jobs, _store, _users = configured_app(tmp_path)
    client = TestClient(app)
    client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"})
    client.post("/api/auth/login", json={"username": "alice", "password": "alice-pass-123"})
    client.post("/api/auth/logout")
    logger.handlers[0].flush()
    lines = (tmp_path / "logs" / "audit.log").read_text(encoding="utf-8").splitlines()
    assert all(isinstance(json.loads(line)["success"], bool) for line in lines)
    text = "\n".join(lines)
    assert "wrong-password" not in text and "alice-pass-123" not in text and "s" * 48 not in text


def test_per_user_active_limit_does_not_change_global_fifo(tmp_path: Path) -> None:
    release = Event()
    jobs = manager(tmp_path / "workspace", BlockingSource(release), limit=1)
    try:
        jobs.create_job("https://youtu.be/a", owner_user_id="a", owner_username="alice")
        with pytest.raises(PipelineError, match="giới hạn") as error:
            jobs.create_job("https://youtu.be/a2", owner_user_id="a", owner_username="alice")
        assert error.value.code == "USER_JOB_LIMIT_REACHED"
        other = jobs.create_job("https://youtu.be/b", owner_user_id="b", owner_username="bob")
        assert jobs.get_job(other.job_id).queue_position == 1
    finally:
        release.set()


def test_migration_is_idempotent_and_backs_up_legacy_jobs(tmp_path: Path) -> None:
    metadata = tmp_path / "workspace" / ("a" * 32) / "metadata" / "job.json"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(json.dumps({"job_id": "a" * 32}), encoding="utf-8")
    database = tmp_path / "data" / "pipeline.db"
    first = migrate_m08(database, tmp_path / "workspace")
    second = migrate_m08(database, tmp_path / "workspace")
    assert first["backed_up_jobs"] == 1
    assert second["backed_up_jobs"] == 0
    assert (tmp_path / "data" / "m08-backup" / "jobs" / f"{'a' * 32}.json").is_file()


def test_job_owner_survives_manager_restart(tmp_path: Path) -> None:
    first = manager(tmp_path / "workspace")
    created = first.create_job("https://youtu.be/persist", owner_user_id="u_alice", owner_username="alice")
    assert first.wait(created.job_id, 5).owner_username == "alice"
    recovered = manager(tmp_path / "workspace")
    job = recovered.get_job(created.job_id)
    assert job.owner_user_id == "u_alice" and job.owner_username == "alice"
