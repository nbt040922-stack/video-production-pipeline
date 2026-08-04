import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.orchestrator.adapters import StubSourceIngestor
from apps.orchestrator.api import create_app
from apps.orchestrator.job_manager import JobManager


VALID_URL = "https://www.youtube.com/watch?v=demo123"
FAIL_URL = "https://youtu.be/demo123?fixture=fail"


def make_manager(path: Path, delay: float = 0.01) -> JobManager:
    return JobManager(path, step_delay=delay, source_ingestor=StubSourceIngestor(delay))


@pytest.fixture
def manager(tmp_path: Path) -> JobManager:
    return make_manager(tmp_path)


@pytest.fixture
def client(manager: JobManager) -> TestClient:
    return TestClient(create_app(manager))


def create_job(client: TestClient, url: str = VALID_URL) -> dict:
    response = client.post("/api/jobs", json={"youtube_url": url})
    assert response.status_code == 201
    return response.json()


def wait_for_terminal(client: TestClient, job_id: str, timeout: float = 3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not finish")


def test_health(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["dependencies"]["source_ingestor"]["status"] == "stub_ready"
    assert response.json()["dependencies"]["hook_engine"] == "stub_ready"


def test_valid_job_creates_isolated_workspace_and_metadata(client: TestClient, manager: JobManager) -> None:
    job = create_job(client)
    job_dir = manager.workspace / job["job_id"]

    assert job["status"] == "queued"
    assert len(job["stages"]) == 9
    assert {path.name for path in job_dir.iterdir()} == {"source", "hook", "review", "final", "metadata", "logs"}
    assert json.loads((job_dir / "metadata" / "job.json").read_text(encoding="utf-8"))["job_id"] == job["job_id"]


def test_invalid_youtube_url_returns_structured_error(client: TestClient) -> None:
    response = client.post("/api/jobs", json={"youtube_url": "https://example.com/video"})
    assert response.status_code == 422
    assert response.json() == {
        "error": {"code": "INVALID_YOUTUBE_URL", "message": "Liên kết YouTube không hợp lệ.", "details": None}
    }


def test_job_progresses_and_completes_with_output(client: TestClient, manager: JobManager) -> None:
    created = create_job(client)
    job = wait_for_terminal(client, created["job_id"])

    assert job["status"] == "completed"
    assert job["progress_percentage"] == 100
    assert all(stage["status"] == "completed" for stage in job["stages"])
    assert job["output"]["filename"] == "final_video.mp4"
    assert job["source"]["youtube_video_id"] == "stub-video"
    assert job["source"]["thumbnail_url"] == f"/api/jobs/{job['job_id']}/assets/thumbnail"
    assert (manager.workspace / job["output"]["relative_path"]).is_file()
    thumbnail = client.get(f"/api/jobs/{job['job_id']}/assets/thumbnail")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"
    assert (manager.workspace / job["job_id"] / "logs" / "pipeline.log").is_file()


def test_cancellation(tmp_path: Path) -> None:
    manager = make_manager(tmp_path, delay=0.1)
    client = TestClient(create_app(manager))
    created = create_job(client)
    response = client.post(f"/api/jobs/{created['job_id']}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert wait_for_terminal(client, created["job_id"])["status"] == "cancelled"


def test_controlled_failure_writes_safe_error_and_traceback_log(client: TestClient, manager: JobManager) -> None:
    created = create_job(client, FAIL_URL)
    job = wait_for_terminal(client, created["job_id"])

    assert job["status"] == "failed"
    assert job["error"]["code"] == "WORKER_ERROR"
    assert "traceback" not in json.dumps(job).lower()
    log = (manager.workspace / job["job_id"] / "logs" / "pipeline.log").read_text(encoding="utf-8")
    assert "Controlled review adapter failure" in log


def test_retry_creates_new_successful_attempt(client: TestClient) -> None:
    failed = wait_for_terminal(client, create_job(client, FAIL_URL)["job_id"])
    response = client.post(f"/api/jobs/{failed['job_id']}/retry")

    assert response.status_code == 201
    retried = response.json()
    assert retried["job_id"] != failed["job_id"]
    assert retried["retry_of"] == failed["job_id"]
    assert retried["attempt"] == 2
    assert wait_for_terminal(client, retried["job_id"])["status"] == "completed"


def test_retry_rejects_non_failed_job(client: TestClient) -> None:
    completed = wait_for_terminal(client, create_job(client)["job_id"])
    response = client.post(f"/api/jobs/{completed['job_id']}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_JOB_STATE"


def test_unknown_job(client: TestClient) -> None:
    response = client.get(f"/api/jobs/{'0' * 32}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"


def test_concurrent_jobs_remain_isolated(client: TestClient, manager: JobManager) -> None:
    first = create_job(client)
    second = create_job(client, "https://youtu.be/another")
    first_result = wait_for_terminal(client, first["job_id"])
    second_result = wait_for_terminal(client, second["job_id"])

    assert first_result["job_id"] != second_result["job_id"]
    assert (manager.workspace / first_result["job_id"] / "metadata" / "job.json").is_file()
    assert (manager.workspace / second_result["job_id"] / "metadata" / "job.json").is_file()


def test_atomic_metadata_is_always_valid_json(client: TestClient, manager: JobManager) -> None:
    created = create_job(client)
    metadata = manager.workspace / created["job_id"] / "metadata" / "job.json"

    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            persisted = json.loads(metadata.read_text(encoding="utf-8"))
        except PermissionError:
            time.sleep(0.002)
            continue
        assert persisted["job_id"] == created["job_id"]
        if persisted["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.002)
    else:
        raise AssertionError("metadata did not reach a terminal state")


def test_corrupted_metadata_returns_structured_error(tmp_path: Path) -> None:
    job_id = "f" * 32
    metadata = tmp_path / job_id / "metadata"
    metadata.mkdir(parents=True)
    (metadata / "job.json").write_text("{not-json", encoding="utf-8")
    client = TestClient(create_app(make_manager(tmp_path)))

    response = client.get(f"/api/jobs/{job_id}")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "CORRUPTED_JOB_METADATA"
