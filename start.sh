#!/bin/sh
set -eu

cd -- "$(dirname -- "$0")"
for tool in uv node npm cc; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing $tool. Install the prerequisites listed in README.md, then try again." >&2
    exit 1
  fi
done

export UV_CACHE_DIR="$(pwd)/.uv-cache"
uv sync --locked
npm --prefix frontend ci --include=dev --engine-strict
npm --prefix frontend run build
echo "Starting PRUMO at http://${FIRELINE_HOST:-127.0.0.1}:${FIRELINE_PORT:-8000} (Ctrl+C to stop)."
exec uv run --locked uvicorn backend.app.main:app --host "${FIRELINE_HOST:-127.0.0.1}" --port "${FIRELINE_PORT:-8000}" --proxy-headers
