#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${BILIFAN_PORT:-8792}"
PUBLIC_URL="${BILIFAN_PUBLIC_URL:-https://bilifan.buyaoting.top}"
PYTHON_BIN="${BILIFAN_PYTHON:-.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Bilifan Python runtime not found: $PYTHON_BIN" >&2
  echo "Run uv sync --extra dev first, or set BILIFAN_PYTHON." >&2
  exit 1
fi

echo "Starting Bilifan for Cloudflare Tunnel"
echo "Local URL: http://127.0.0.1:${PORT}/"
echo "Public URL: ${PUBLIC_URL}"

exec "$PYTHON_BIN" -m bilifan serve \
  --no-open \
  --port "$PORT" \
  --strict-port \
  --public-url "$PUBLIC_URL"
