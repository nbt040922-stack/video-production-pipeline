import json
import subprocess
import sys
from pathlib import Path
from threading import Event
from typing import Callable

import pytest
from PIL import Image

from apps.orchestrator.adapters import JobCancelled
from apps.orchestrator.hook_engine_adapter import (
    HookEngineAdapter,
    HookEngineConfig,
    HookEngineError,
)
from apps.orchestrator.source_ingestor import ProbeResult


VALID_PROBE = ProbeResult(
    duration_seconds=5.0,
    width=1920,
    height=1080,
    fps=30,
    video_codec="h264",
    audio_codec="aac",
)


def make_workspace(tmp_path: Path, *, thumbnail: bool = True) -> Path:
    (tmp_path / "source").mkdir(parents=True)
    (tmp_path / "hook").mkdir()
    if thumbnail:
        Image.new("RGB", (640, 360), "#332266").save(tmp_path / "source" / "thumbnail.jpg", format="JPEG")
    return tmp_path


def make_engine(tmp_path: Path) -> Path:
    root = tmp_path / "engine"
    motion = root / "motion_library" / "user" / "motion1"
    motion.mkdir(parents=True)
    (root / "main.py").write_text("# fake CLI\n", encoding="utf-8")
    (root / "ComfyUI").mkdir()
    (root / "ComfyUI" / "main.py").write_text("# fake ComfyUI\n", encoding="utf-8")
    (motion / "metadata.json").write_text(json.dumps({"motion_id": "motion1"}), encoding="utf-8")
    return root


def config(root: Path) -> HookEngineConfig:
    return HookEngineConfig(
        engine_path=root,
        python_path=sys.executable,
        ffmpeg_path=sys.executable,
        ffprobe_path=sys.executable,
        server="http://127.0.0.1:1",
        timeout_seconds=2,
    )


class FakeRunner:
    def __init__(self, *, failure: bool = False) -> None:
        self.failure = failure
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        _cwd: Path,
        _timeout: int,
        cancelled: Callable[[], bool],
        tick: Callable[[float], None],
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if cancelled():
            raise JobCancelled
        tick(1)
        if self.failure:
            return subprocess.CompletedProcess(command, 1, "", "engine exploded")
        if "generate" in command:
            output = Path(command[command.index("--output") + 1]).parent / "engine123" / "raw_candidate.mp4"
            output.parent.mkdir()
            output.write_bytes(b"raw video")
            (output.parent / "generation_metadata.json").write_text(
                json.dumps({"job_id": "engine123"}), encoding="utf-8"
            )
            return subprocess.CompletedProcess(command, 0, f"[PASS] Phase 3 job engine123: {output}\n", "")
        output_dir = Path(command[command.index("--output-dir") + 1])
        output = output_dir / "engine123" / "final_hook.mp4"
        output.parent.mkdir(parents=True)
        output.write_bytes(b"final video")
        return subprocess.CompletedProcess(command, 0, f"[PASS] Phase 4 job engine123: {output}\n", "")


def prepared_adapter(tmp_path: Path, runner: Callable | None = None, probe: ProbeResult = VALID_PROBE):
    workspace = make_workspace(tmp_path / "workspace")
    adapter = HookEngineAdapter(
        config(make_engine(tmp_path)),
        command_runner=runner or FakeRunner(),
        probe_runner=lambda _path: probe,
    )
    thumbnail = workspace / "source" / "thumbnail.jpg"
    adapter.prepare(thumbnail, "job123", workspace)
    return adapter, workspace, thumbnail


def test_successful_generation_collects_validated_output(tmp_path: Path) -> None:
    runner = FakeRunner()
    adapter, workspace, thumbnail = prepared_adapter(tmp_path, runner)

    output = adapter.run(thumbnail, "job123", workspace, Event(), lambda *_: None)
    adapter.cleanup("job123", workspace)
    metadata = json.loads((workspace / "hook" / "metadata.json").read_text(encoding="utf-8"))

    assert output == workspace / "hook" / "final_hook.mp4"
    assert output.is_file()
    assert metadata["duration_seconds"] == 5.0
    assert metadata["final_video_path"] == "hook/final_hook.mp4"
    assert ["generate" in command for command in runner.commands] == [True, False]
    assert adapter.status("job123")["status"] == "completed"
    assert not (workspace / "hook" / "_engine").exists()


def test_missing_thumbnail_is_rejected(tmp_path: Path) -> None:
    workspace = make_workspace(tmp_path / "workspace", thumbnail=False)
    adapter = HookEngineAdapter(config(make_engine(tmp_path)), command_runner=FakeRunner(), probe_runner=lambda _: VALID_PROBE)

    with pytest.raises(HookEngineError) as captured:
        adapter.prepare(workspace / "source" / "thumbnail.jpg", "job123", workspace)
    assert captured.value.code == "HOOK_THUMBNAIL_MISSING"


def test_engine_failure_is_structured(tmp_path: Path) -> None:
    adapter, workspace, thumbnail = prepared_adapter(tmp_path, FakeRunner(failure=True))
    with pytest.raises(HookEngineError) as captured:
        adapter.run(thumbnail, "job123", workspace, Event(), lambda *_: None)
    assert captured.value.code == "HOOK_ENGINE_FAILED"


def test_timeout_is_structured(tmp_path: Path) -> None:
    def timeout_runner(*_args):
        raise TimeoutError("slow engine")

    adapter, workspace, thumbnail = prepared_adapter(tmp_path, timeout_runner)
    with pytest.raises(HookEngineError) as captured:
        adapter.run(thumbnail, "job123", workspace, Event(), lambda *_: None)
    assert captured.value.code == "HOOK_TIMEOUT"


def test_cancel_stops_prepared_job(tmp_path: Path) -> None:
    adapter, workspace, thumbnail = prepared_adapter(tmp_path)
    adapter.cancel("job123")

    with pytest.raises(JobCancelled):
        adapter.run(thumbnail, "job123", workspace, Event(), lambda *_: None)
    assert adapter.status("job123")["status"] == "cancelled"


def test_invalid_output_duration_is_rejected(tmp_path: Path) -> None:
    invalid = ProbeResult(
        duration_seconds=8,
        width=1920,
        height=1080,
        fps=30,
        video_codec="h264",
        audio_codec="aac",
    )
    adapter, workspace, thumbnail = prepared_adapter(tmp_path, probe=invalid)

    with pytest.raises(HookEngineError) as captured:
        adapter.run(thumbnail, "job123", workspace, Event(), lambda *_: None)
    assert captured.value.code == "HOOK_OUTPUT_INVALID"
    adapter.cleanup("job123", workspace)
    assert not (workspace / "hook" / "final_hook.mp4").exists()

def test_large_cli_output_does_not_deadlock(tmp_path: Path) -> None:
    adapter, _workspace, _thumbnail = prepared_adapter(tmp_path)
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.write('o' * 262144); sys.stderr.write('e' * 262144)",
    ]

    result = adapter._execute("job123", command, tmp_path, 5, lambda: False, lambda _elapsed: None)

    assert result.returncode == 0
    assert len(result.stdout) == 262144
    assert len(result.stderr) == 262144
