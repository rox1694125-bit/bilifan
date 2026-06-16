#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${BILIFAN_PORT:-8792}"
PUBLIC_URL="${BILIFAN_PUBLIC_URL:-https://bilifan.buyaoting.top}"
TUNNEL_NAME="${BILIFAN_TUNNEL_NAME:-bilifan}"
CONFIG_PATH="${BILIFAN_CLOUDFLARED_CONFIG:-.bilifan/cloudflared-bilifan.yml}"
WEB_SESSION="${BILIFAN_WEB_TMUX_SESSION:-bilifan-web}"
TUNNEL_SESSION="${BILIFAN_TUNNEL_TMUX_SESSION:-bilifan-tunnel}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed or not on PATH." >&2
  exit 1
fi

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Bilifan Python runtime not found: $ROOT/.venv/bin/python" >&2
  exit 1
fi

if [[ ! -f "$ROOT/$CONFIG_PATH" ]]; then
  echo "Bilifan cloudflared config not found: $ROOT/$CONFIG_PATH" >&2
  exit 1
fi

if tmux has-session -t "$WEB_SESSION" 2>/dev/null; then
  echo "tmux session already running: $WEB_SESSION"
else
  tmux new-session -d -s "$WEB_SESSION" \
    "cd '$ROOT' && exec .venv/bin/python -m bilifan serve --no-open --port '$PORT' --strict-port --public-url '$PUBLIC_URL'"
  echo "started tmux session: $WEB_SESSION"
fi

if tmux has-session -t "$TUNNEL_SESSION" 2>/dev/null; then
  echo "tmux session already running: $TUNNEL_SESSION"
else
  tmux new-session -d -s "$TUNNEL_SESSION" \
    "cd '$ROOT' && exec env BILIFAN_ACCESS_CONFIGURED=1 BILIFAN_TUNNEL_NAME='$TUNNEL_NAME' BILIFAN_CLOUDFLARED_CONFIG='$CONFIG_PATH' scripts/start-cloudflared-bilifan.sh"
  echo "started tmux session: $TUNNEL_SESSION"
fi

echo "Local URL: http://127.0.0.1:${PORT}/"
echo "Public URL: ${PUBLIC_URL}"
