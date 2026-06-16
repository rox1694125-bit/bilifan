#!/usr/bin/env bash
set -euo pipefail

WEB_SESSION="${BILIFAN_WEB_TMUX_SESSION:-bilifan-web}"
TUNNEL_SESSION="${BILIFAN_TUNNEL_TMUX_SESSION:-bilifan-tunnel}"

if ! command -v tmux >/dev/null 2>&1; then
  echo "tmux is not installed or not on PATH." >&2
  exit 1
fi

for session in "$TUNNEL_SESSION" "$WEB_SESSION"; do
  if tmux has-session -t "$session" 2>/dev/null; then
    tmux kill-session -t "$session"
    echo "stopped tmux session: $session"
  else
    echo "tmux session not running: $session"
  fi
done
