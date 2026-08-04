from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.orchestrator.hook_engine_adapter import HookEngineAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real Hook Engine adapter once")
    parser.add_argument("thumbnail", type=Path, help="validated JPEG thumbnail")
    parser.add_argument("--workspace", type=Path, default=Path("workspace/manual-hook"))
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    (workspace / "source").mkdir(parents=True, exist_ok=True)
    (workspace / "hook").mkdir(exist_ok=True)
    thumbnail = workspace / "source" / "thumbnail.jpg"
    shutil.copy2(args.thumbnail.resolve(), thumbnail)

    adapter = HookEngineAdapter()
    adapter.prepare(thumbnail, "manual-hook", workspace)
    try:
        output = adapter.run(
            thumbnail,
            "manual-hook",
            workspace,
            Event(),
            lambda percent, message: print(f"[{percent:3d}%] {message}"),
        )
    finally:
        adapter.cleanup("manual-hook", workspace)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
