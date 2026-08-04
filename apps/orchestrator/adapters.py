from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable, Protocol

ProgressCallback = Callable[[int, str], None]


class JobCancelled(Exception):
    pass


class SourceIngestor(Protocol):
    def download(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...
    def prepare_thumbnail(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


class HookEngineAdapter(Protocol):
    def generate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


class ReviewEngineAdapter(Protocol):
    def write_review(self, workspace: Path, cancel: Event, progress: ProgressCallback, fail: bool) -> None: ...
    def generate_voice(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...
    def select_footage(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...
    def render(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


class FinalComposer(Protocol):
    def compose(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> Path: ...
    def validate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None: ...


def _work(label: str, delay: float, cancel: Event, progress: ProgressCallback) -> None:
    for percent in (25, 65, 100):
        if cancel.wait(delay / 3):
            raise JobCancelled
        progress(percent, f"{label}: {percent}%")


class StubSourceIngestor:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def download(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang tải nguồn", self.delay, cancel, progress)
        (workspace / "source" / "source.txt").write_text("placeholder source\n", encoding="utf-8")

    def prepare_thumbnail(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang chuẩn bị ảnh bìa", self.delay, cancel, progress)
        (workspace / "source" / "thumbnail.txt").write_text("placeholder thumbnail\n", encoding="utf-8")


class StubHookEngineAdapter:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def generate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang tạo đoạn mở đầu", self.delay, cancel, progress)
        (workspace / "hook" / "final_hook.mp4").write_bytes(b"placeholder hook\n")


class StubReviewEngineAdapter:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def write_review(self, workspace: Path, cancel: Event, progress: ProgressCallback, fail: bool) -> None:
        _work("Đang viết bài đánh giá", self.delay, cancel, progress)
        if fail:
            raise RuntimeError("Controlled review adapter failure")

    def generate_voice(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang tạo giọng đọc", self.delay, cancel, progress)

    def select_footage(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang chọn cảnh quay", self.delay, cancel, progress)

    def render(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang dựng video đánh giá", self.delay, cancel, progress)
        (workspace / "review" / "review.mp4").write_bytes(b"placeholder review\n")


class StubFinalComposer:
    def __init__(self, delay: float) -> None:
        self.delay = delay

    def compose(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> Path:
        _work("Đang ghép video cuối", self.delay, cancel, progress)
        output = workspace / "final" / "final_video.mp4"
        output.write_bytes(b"placeholder final video\n")
        return output

    def validate(self, workspace: Path, cancel: Event, progress: ProgressCallback) -> None:
        _work("Đang kiểm tra đầu ra", self.delay, cancel, progress)
        if not (workspace / "final" / "final_video.mp4").is_file():
            raise RuntimeError("Final output is missing")
