import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest
from fastapi.testclient import TestClient

from apps.orchestrator.adapters import JobCancelled, StubFinalComposer, StubHookEngineAdapter, StubSourceIngestor
from apps.orchestrator.api import create_app
from apps.orchestrator.job_manager import JobManager
from apps.orchestrator.review_engine_adapter import (
    ReviewEngineAdapter,
    ReviewEngineConfig,
    ReviewEngineError,
    ReviewEngineInput,
)
from apps.orchestrator.source_ingestor import ProbeResult


VALID_PROBE = ProbeResult(
    duration_seconds=12.5,
    width=1920,
    height=1080,
    fps=30,
    video_codec="h264",
    audio_codec="aac",
)

FAKE_CLI = r'''
import argparse, json, sys, time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("command")
p.add_argument("--job-id")
p.add_argument("--source-video")
p.add_argument("--youtube-url")
p.add_argument("--output-dir")
p.add_argument("--working-dir")
p.add_argument("--voice-reference")
p.add_argument("--voice-reference-text")
p.add_argument("--resume-policy")
p.add_argument("--progress-jsonl", action="store_true")
p.add_argument("--use-proxy-video", action="store_true")
p.add_argument("--json", action="store_true")
a = p.parse_args()

def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)

if a.command == "doctor":
    emit({"ready": True, "checks": {"fake": True}})
    raise SystemExit(0)

mode = a.job_id
if mode in {"slow", "cancel"}:
    time.sleep(30)
if mode == "failure":
    emit({"event":"error", "status":"failed", "error":{"code":"GEMINI_FAILED", "message":"secret upstream detail"}})
    raise SystemExit(2)

out = Path(a.output_dir)
out.mkdir(parents=True, exist_ok=True)
for stage in ("writing_review", "generating_voice", "transcribing", "selecting_windows", "indexing_proxy", "searching_scenes", "mapping_timeline", "rendering_review", "validating_output"):
    message = "Render timeline có sẵn" if stage == "rendering_review" else stage
    emit({"event":"stage", "stage":stage, "status":"started", "progress":0, "message":message})
    emit({"event":"stage", "stage":stage, "status":"completed", "progress":1, "message":stage})
(out / "review.mp4").write_bytes(b"video")
(out / "metadata.json").write_text(json.dumps({"duration_total_seconds":1.2}))
fallback = mode == "fallback"
metrics = {
    "source_duration":10.0, "proxy_duration":10.0 if fallback else 5.0,
    "saved_percentage":0.0 if fallback else 50.0,
    "fallback_count":1 if fallback else 0,
    "fallback_reason":"full_source" if fallback else None,
    "mapping_errors":0,
}
mapping = ({"windows":[], "fallback":True, "fallback_reason":"full_source"} if fallback else
           {"windows":[{"proxy_start":0,"proxy_end":5,"source_start":1,"source_end":6,"duration":5}], "fallback":False})
if mode == "invalid-mapping":
    mapping["windows"][0]["proxy_end"] = 4
if mode != "missing-metrics":
    (out / "proxy_metrics.json").write_text(json.dumps(metrics))
(out / "window_mapping.json").write_text(json.dumps(mapping))
for folder, name, data in (("script","review.json","{}"),("voice","voice.wav","voice"),("timeline","timeline.json","{}")):
    target = out / folder
    target.mkdir()
    (target / name).write_text(data)
emit({"event":"result", "status":"completed", "job_id":a.job_id, "review_video_path":str(out / "review.mp4")})
'''


def make_engine(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "engine"
    root.mkdir(parents=True)
    (root / "review_cli.py").write_text(FAKE_CLI, encoding="utf-8")
    (root / "GEMINI_PROMPT.txt").write_text("prompt", encoding="utf-8")
    omnivoice = root / ".venv-omnivoice" / "Scripts"
    omnivoice.mkdir(parents=True)
    (omnivoice / "omnivoice-infer.exe").write_bytes(b"fake")
    voice = tmp_path / "voice.wav"
    voice.write_bytes(b"voice")
    return root, voice


def make_workspace(tmp_path: Path, *, source: bool = True, metadata: bool = True) -> Path:
    workspace = tmp_path / "workspace"
    for folder in ("source", "hook", "review", "final", "metadata", "logs"):
        (workspace / folder).mkdir(parents=True)
    if source:
        (workspace / "source" / "source.mp4").write_bytes(b"source-original")
    if metadata:
        (workspace / "source" / "metadata.json").write_text(json.dumps({"duration_seconds": 10}))
    (workspace / "hook" / "final_hook.mp4").write_bytes(b"hook-original")
    return workspace


def make_adapter(tmp_path: Path, *, timeout: int = 5, probe=VALID_PROBE, credentials: bool = True):
    root, voice = make_engine(tmp_path)
    config = ReviewEngineConfig(
        engine_path=root,
        python_path=sys.executable,
        timeout_seconds=timeout,
        ffmpeg_path=sys.executable,
        ffprobe_path=sys.executable,
        voice_reference_path=voice,
        use_proxy_video=True,
        gemini_api_key="gemini" if credentials else "",
        twelve_labs_api_key="twelve" if credentials else "",
    )
    return ReviewEngineAdapter(config, probe_runner=lambda _path: probe)


def request(workspace: Path, job_id: str = "success") -> ReviewEngineInput:
    return ReviewEngineInput(
        job_id=job_id,
        youtube_url="https://youtu.be/demo123",
        source_video_path=workspace / "source" / "source.mp4",
        source_metadata_path=workspace / "source" / "metadata.json",
        workspace=workspace,
    )


def run_prepared(adapter: ReviewEngineAdapter, item: ReviewEngineInput):
    adapter.prepare(item)
    return adapter.run(item, Event(), lambda *_: None)


def test_prepare_success_and_readiness(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    item = request(make_workspace(tmp_path))
    adapter.prepare(item)
    assert adapter.status(item.job_id)["status"] == "prepared"
    assert adapter.readiness()["status"] == "ready"


def test_env_config_uses_engine_voice_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = tmp_path / "engine"
    engine.mkdir()
    voice = engine / "voice.wav"
    voice.write_bytes(b"voice")
    monkeypatch.setenv("REVIEW_ENGINE_PATH", str(engine))
    monkeypatch.delenv("REVIEW_VOICE_REFERENCE_PATH", raising=False)

    assert ReviewEngineConfig.from_env().voice_reference_path == voice


def test_missing_openai_configuration_selects_gemini(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REVIEW_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("REVIEW_LLM_MODEL", raising=False)

    environment = make_adapter(tmp_path)._engine_environment()

    assert environment["REVIEW_LLM_PROVIDER"] == "gemini"


def test_missing_engine_source_and_credentials_are_structured(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    adapter = make_adapter(tmp_path)
    adapter.config = ReviewEngineConfig(engine_path=tmp_path / "missing")
    with pytest.raises(ReviewEngineError) as missing_engine:
        adapter.prepare(request(workspace))
    assert missing_engine.value.code == "REVIEW_ENGINE_NOT_CONFIGURED"

    adapter = make_adapter(tmp_path / "second")
    item = request(make_workspace(tmp_path / "second"))
    item.source_video_path.unlink()
    with pytest.raises(ReviewEngineError) as missing_source:
        adapter.prepare(item)
    assert missing_source.value.code == "REVIEW_OUTPUT_INVALID"

    adapter = make_adapter(tmp_path / "third", credentials=False)
    with pytest.raises(ReviewEngineError) as missing_credentials:
        adapter.prepare(request(make_workspace(tmp_path / "third")))
    assert missing_credentials.value.code == "REVIEW_ENGINE_CREDENTIALS_MISSING"


def test_success_normalizes_outputs_and_preserves_source_and_hook(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path)
    result = run_prepared(make_adapter(tmp_path), request(workspace))
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert result.review_video_path == workspace / "review" / "review.mp4"
    assert metadata["review_video_path"] == "review/review.mp4"
    assert metadata["source_video_path"] == "source/source.mp4"
    assert result.saved_percentage == 50
    assert "Render timeline có sẵn" in (workspace / "review" / "logs" / "engine.jsonl").read_text(encoding="utf-8")
    assert (workspace / "source" / "source.mp4").read_bytes() == b"source-original"
    assert (workspace / "hook" / "final_hook.mp4").read_bytes() == b"hook-original"


def test_engine_failure_maps_safe_error(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path)
    item = request(make_workspace(tmp_path), "failure")
    adapter.prepare(item)
    with pytest.raises(ReviewEngineError) as captured:
        adapter.run(item, Event(), lambda *_: None)
    assert captured.value.code == "GEMINI_FAILED"
    assert "secret" not in captured.value.message


def test_timeout_and_cancel_stop_process(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path / "timeout", timeout=1)
    item = request(make_workspace(tmp_path / "timeout"), "slow")
    adapter.prepare(item)
    with pytest.raises(ReviewEngineError) as captured:
        adapter.run(item, Event(), lambda *_: None)
    assert captured.value.code == "REVIEW_ENGINE_TIMEOUT"

    adapter = make_adapter(tmp_path / "cancel")
    item = request(make_workspace(tmp_path / "cancel"), "cancel")
    adapter.prepare(item)
    cancelled = Event()
    errors = []
    worker = threading.Thread(target=lambda: _capture(lambda: adapter.run(item, cancelled, lambda *_: None), errors))
    worker.start()
    time.sleep(0.2)
    cancelled.set()
    worker.join(5)
    assert errors and isinstance(errors[0], JobCancelled)


def _capture(action, errors: list[Exception]) -> None:
    try:
        action()
    except Exception as error:  # test thread boundary
        errors.append(error)


def test_invalid_video_missing_metrics_and_mapping_are_rejected(tmp_path: Path) -> None:
    invalid_probe = VALID_PROBE.model_copy(update={"audio_codec": None})
    adapter = make_adapter(tmp_path / "video", probe=invalid_probe)
    with pytest.raises(ReviewEngineError) as invalid_video:
        run_prepared(adapter, request(make_workspace(tmp_path / "video")))
    assert invalid_video.value.code == "REVIEW_OUTPUT_INVALID"

    adapter = make_adapter(tmp_path / "metrics")
    with pytest.raises(ReviewEngineError) as missing_metrics:
        run_prepared(adapter, request(make_workspace(tmp_path / "metrics"), "missing-metrics"))
    assert missing_metrics.value.code == "REVIEW_OUTPUT_INVALID"

    adapter = make_adapter(tmp_path / "mapping")
    with pytest.raises(ReviewEngineError) as invalid_mapping:
        run_prepared(adapter, request(make_workspace(tmp_path / "mapping"), "invalid-mapping"))
    assert invalid_mapping.value.code == "PROXY_MAPPING_FAILED"


def test_valid_full_source_fallback(tmp_path: Path) -> None:
    result = run_prepared(make_adapter(tmp_path), request(make_workspace(tmp_path), "fallback"))
    assert result.fallback_used is True
    assert result.saved_percentage == 0
    assert result.fallback_reason == "full_source"


def test_concurrent_jobs_do_not_mix_outputs(tmp_path: Path) -> None:
    root, voice = make_engine(tmp_path)
    config = ReviewEngineConfig(
        engine_path=root, python_path=sys.executable, ffmpeg_path=sys.executable,
        ffprobe_path=sys.executable, voice_reference_path=voice,
        gemini_api_key="g", twelve_labs_api_key="t",
    )
    adapter = ReviewEngineAdapter(config, probe_runner=lambda _path: VALID_PROBE)
    requests = [request(make_workspace(tmp_path / name), name) for name in ("one", "two")]
    for item in requests:
        adapter.prepare(item)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda item: adapter.run(item, Event(), lambda *_: None), requests))
    assert results[0].review_video_path != results[1].review_video_path
    assert all(result.review_video_path.is_file() for result in results)


def test_job_manager_receives_review_metadata_and_serves_safe_assets(tmp_path: Path) -> None:
    adapter = make_adapter(tmp_path / "adapter")
    manager = JobManager(
        tmp_path / "jobs",
        step_delay=0.001,
        source_ingestor=StubSourceIngestor(0.001),
        hook_engine=StubHookEngineAdapter(0.001),
        review_engine=adapter,
        composer=StubFinalComposer(0.001),
    )
    client = TestClient(create_app(manager))
    created = client.post("/api/jobs", json={"youtube_url": "https://youtu.be/demo123"}).json()
    job = manager.wait(created["job_id"], 5)
    assert job.status == "completed"
    assert job.review_engine.proxy_savings == "50,0%"
    assert job.review_engine.preview_url.endswith("/assets/review")
    assert job.review_engine.output_duration_seconds == 12.5
    assert job.review_engine.elapsed_seconds == 1.2
    assert client.get(f"/api/jobs/{job.job_id}/assets/review").status_code == 200
    assert client.get(f"/api/jobs/{job.job_id}/assets/review-metadata").status_code == 200
    assert client.get(f"/api/jobs/{job.job_id}/assets/proxy-metrics").status_code == 200
    assert client.get(f"/api/jobs/{job.job_id}/assets/../../source/source.mp4").status_code in {404, 422}


def test_recovery_marks_review_interrupted_without_rerun(tmp_path: Path) -> None:
    job_id = "a" * 32
    metadata = tmp_path / job_id / "metadata"
    metadata.mkdir(parents=True)
    for folder in ("source", "hook", "review", "final", "logs"):
        (tmp_path / job_id / folder).mkdir()
    payload = {
        "job_id": job_id, "youtube_url": "https://youtu.be/demo123", "status": "processing",
        "current_stage": "footage", "created_at": "2026-01-01T00:00:00+00:00",
        "started_at": "2026-01-01T00:00:00+00:00",
        "stages": [{"id": name, "name": name, "status": "running" if name == "footage" else "pending"}
                   for name in ("download","thumbnail","hook","script","voice","footage","review","compose","validate")],
        "hook_engine": {"output_filename":"final_hook.mp4"},
        "review_engine": {"output_filename":"review.mp4"},
    }
    (metadata / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    manager = JobManager(tmp_path, review_engine=make_adapter(tmp_path / "adapter"))
    assert manager.get_job(job_id).error.code == "INTERRUPTED"
    assert not (tmp_path / job_id / "review" / "review.mp4").exists()
