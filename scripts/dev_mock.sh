#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-/tmp/longlive-uv}"
uv sync --frozen
if [ ! -d node_modules ]; then npm ci; fi
npm run build
export LOG_PATH="${LOG_PATH:-logs/events.jsonl}"
env_args=()
if [ -f .env ]; then env_args=(--env-file .env); fi
exec .venv/bin/python -m uvicorn longlive.app:create_app --factory --host 127.0.0.1 --port "${PORT:-8080}" --workers 1 --ws-max-size 4096 "${env_args[@]}"
