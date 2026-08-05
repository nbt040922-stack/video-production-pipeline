#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
root=$(pwd)
[ -x .venv/bin/python ] || { echo "Run ./setup.sh first."; exit 1; }
[ -d node_modules ] || { echo "Run npm install first."; exit 1; }
python="$root/.venv/bin/python"

sibling_hook="$(dirname "$root")/AI_hook_engine"
if [ -z "${HOOK_ENGINE_PATH:-}" ]; then
    if [ -f "$sibling_hook/ComfyUI/main.py" ]; then
        HOOK_ENGINE_PATH=$sibling_hook
    else
        HOOK_ENGINE_PATH="$root/engines/hook-engine"
    fi
fi
comfy_root="$HOOK_ENGINE_PATH/ComfyUI"
HOOK_ENGINE_PYTHON=${HOOK_ENGINE_PYTHON:-"$comfy_root/.venv/bin/python"}
HOOK_ENGINE_SERVER=${HOOK_ENGINE_SERVER:-http://127.0.0.1:8188}
HOOK_MOTION_ID=${HOOK_MOTION_ID:-motion1}
[ -f "$comfy_root/main.py" ] || { echo "Hook runtime missing: $comfy_root/main.py. Set HOOK_ENGINE_PATH."; exit 1; }
[ -x "$HOOK_ENGINE_PYTHON" ] || { echo "Hook Python missing: $HOOK_ENGINE_PYTHON. Set HOOK_ENGINE_PYTHON."; exit 1; }

comfy_host=$($python -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).hostname or "127.0.0.1")' "$HOOK_ENGINE_SERVER")
comfy_port=$($python -c 'import sys, urllib.parse; print(urllib.parse.urlparse(sys.argv[1]).port or 8188)' "$HOOK_ENGINE_SERVER")
comfy_ready() {
    "$python" -c 'import sys, urllib.request; urllib.request.urlopen(sys.argv[1].rstrip("/") + "/system_stats", timeout=1).close()' "$HOOK_ENGINE_SERVER" >/dev/null 2>&1
}

VITE_PIPELINE_MODE=backend
VITE_API_BASE_URL=http://127.0.0.1:8000
export VITE_PIPELINE_MODE VITE_API_BASE_URL HOOK_ENGINE_PATH HOOK_ENGINE_PYTHON HOOK_ENGINE_SERVER HOOK_MOTION_ID

comfy_pid=""
backend_pid=""
cleanup() {
    [ -z "$backend_pid" ] || kill "$backend_pid" 2>/dev/null || true
    [ -z "$comfy_pid" ] || kill "$comfy_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if comfy_ready; then
    echo "Hook ComfyUI already running: $HOOK_ENGINE_SERVER"
else
    mkdir -p workspace/services
    "$HOOK_ENGINE_PYTHON" "$comfy_root/main.py" --listen "$comfy_host" --port "$comfy_port" \
        >workspace/services/comfyui.stdout.log 2>workspace/services/comfyui.stderr.log &
    comfy_pid=$!
    echo "Starting Hook ComfyUI: $HOOK_ENGINE_SERVER"
    attempt=0
    while ! comfy_ready; do
        kill -0 "$comfy_pid" 2>/dev/null || { echo "Hook ComfyUI stopped during startup. See workspace/services logs."; exit 1; }
        attempt=$((attempt + 1))
        [ "$attempt" -lt 120 ] || { echo "Hook ComfyUI startup timed out after 120 seconds."; exit 1; }
        sleep 1
    done
fi

.venv/bin/python -m uvicorn apps.orchestrator.api:app --host 127.0.0.1 --port 8000 &
backend_pid=$!

echo "Backend: http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"
npm run dev -- --host 127.0.0.1 --port 5173
