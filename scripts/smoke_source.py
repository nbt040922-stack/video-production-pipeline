"""Manual real-download smoke test; excluded from pytest."""

import argparse
import sys
from pathlib import Path
from threading import Event
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.orchestrator.source_ingestor import RealSourceIngestor  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Download one real YouTube source into workspace/")
    parser.add_argument("youtube_url")
    args = parser.parse_args()

    job_id = uuid4().hex
    workspace = Path("workspace") / job_id
    (workspace / "source").mkdir(parents=True)
    ingestor = RealSourceIngestor()
    report = lambda progress, message: print(f"{progress:3d}% {message}")
    result = ingestor.download(args.youtube_url, job_id, workspace, Event(), report)
    result = ingestor.prepare_thumbnail(result, job_id, workspace, Event(), report)
    print(result.metadata_path)


if __name__ == "__main__":
    main()
