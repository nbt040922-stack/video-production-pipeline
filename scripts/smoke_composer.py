from __future__ import annotations

import sys
from pathlib import Path
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from apps.orchestrator.final_composer import FinalComposer


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python scripts/smoke_composer.py workspace/<job_id>")
        return 2
    workspace = Path(sys.argv[1]).resolve()
    adapter = FinalComposer()
    output = adapter.compose(workspace, Event(), lambda value, message: print(f"[{value:3}%] {message}"))
    adapter.validate(workspace, Event(), lambda value, message: print(f"[{value:3}%] {message}"))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
