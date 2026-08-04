#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."
[ -x .venv/bin/python ] || { echo "Run ./setup.sh first."; exit 1; }
[ -d node_modules ] || { echo "Run npm install first."; exit 1; }

VITE_PIPELINE_MODE=backend
VITE_API_BASE_URL=http://127.0.0.1:8000
export VITE_PIPELINE_MODE VITE_API_BASE_URL

.venv/bin/python -m uvicorn apps.orchestrator.api:app --host 127.0.0.1 --port 8000 &
backend_pid=$!
trap 'kill "$backend_pid" 2>/dev/null || true' EXIT INT TERM

echo "Backend: http://127.0.0.1:8000"
echo "Frontend: http://127.0.0.1:5173"
npm run dev -- --host 127.0.0.1 --port 5173
