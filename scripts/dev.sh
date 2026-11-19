#!/usr/bin/env bash
# Local development: backend on :8000, Vite with API proxy on :5173.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
. .venv/bin/activate
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend/requirements.txt -r backend/requirements-dev.txt

if [[ ! -d frontend/node_modules ]]; then
  (cd frontend && pnpm install)
fi

mkdir -p .devdata
export DATA_DIR="$root/.devdata"
export HOST_ROOT="${HOST_ROOT:-/}"
export HOST_PROC="${HOST_PROC:-/proc}"
export HOST_SYS="${HOST_SYS:-/sys}"
export HOST_OS_RELEASE="${HOST_OS_RELEASE:-/etc/os-release}"
export OPENRGB_HOST="${OPENRGB_HOST:-127.0.0.1}"
export OPENRGB_PORT="${OPENRGB_PORT:-6742}"
export AURASYNC_WEBHOOK_TOKEN="${AURASYNC_WEBHOOK_TOKEN:-dev-token}"
export AURASYNC_LOG_LEVEL=INFO

python -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 &
backend_pid=$!

cleanup() {
  kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd frontend
  pnpm dev
)
