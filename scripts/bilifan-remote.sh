#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PORT="${BILIFAN_PORT:-8792}"
PUBLIC_URL="${BILIFAN_PUBLIC_URL:-https://bilifan.buyaoting.top}"
WEB_SESSION="${BILIFAN_WEB_TMUX_SESSION:-bilifan-web}"
TUNNEL_SESSION="${BILIFAN_TUNNEL_TMUX_SESSION:-bilifan-tunnel}"
COMMAND="${1:-status}"

usage() {
  cat <<'USAGE'
Usage: scripts/bilifan-remote.sh start|stop|restart|status|logs

Daily commands:
  scripts/bilifan-remote.sh restart   Restart Bilifan Web UI and Cloudflare tunnel
  scripts/bilifan-remote.sh status    Show local/remote entrypoints and tmux status
  scripts/bilifan-remote.sh logs      Show where to inspect Web UI and tunnel logs
  scripts/bilifan-remote.sh stop      Stop both tmux sessions
USAGE
}

require_tmux() {
  if ! command -v tmux >/dev/null 2>&1; then
    echo "tmux is not installed or not on PATH." >&2
    exit 1
  fi
}

session_label() {
  local session="$1"
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "running"
  else
    echo "stopped"
  fi
}

show_status() {
  require_tmux
  echo "Bilifan remote status"
  echo "  Web UI tmux:   $WEB_SESSION ($(session_label "$WEB_SESSION"))"
  echo "  Tunnel tmux:   $TUNNEL_SESSION ($(session_label "$TUNNEL_SESSION"))"
  echo "  Local URL:     http://127.0.0.1:${PORT}/"
  echo "  Public URL:    ${PUBLIC_URL}"
  if command -v curl >/dev/null 2>&1; then
    local code
    code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 2 "http://127.0.0.1:${PORT}/api/status" 2>/dev/null || true)"
    case "$code" in
      200)
        echo "  Local API:     reachable"
        ;;
      403)
        echo "  Local API:     reachable, token required"
        ;;
      000|"")
        echo "  Local API:     not reachable"
        ;;
      *)
        echo "  Local API:     HTTP $code"
        ;;
    esac
  fi
  echo "  Note: old browser tabs may show 403 after restart; reopen the Public URL."
}

show_logs() {
  require_tmux
  echo "Inspect logs interactively:"
  echo "  tmux attach -t $WEB_SESSION"
  echo "  tmux attach -t $TUNNEL_SESSION"
  echo
  capture_recent_output "$WEB_SESSION" "Web UI"
  echo
  capture_recent_output "$TUNNEL_SESSION" "Cloudflare tunnel"
}

capture_recent_output() {
  local session="$1"
  local label="$2"
  if tmux has-session -t "$session" 2>/dev/null; then
    echo "Recent $label output:"
    tmux capture-pane -pt "$session" -S -20 || true
  else
    echo "$label tmux session is not running: $session"
  fi
}

case "$COMMAND" in
  start)
    scripts/start-bilifan-remote-tmux.sh
    show_status
    ;;
  stop)
    scripts/stop-bilifan-remote-tmux.sh
    ;;
  restart)
    scripts/stop-bilifan-remote-tmux.sh
    scripts/start-bilifan-remote-tmux.sh
    show_status
    ;;
  status)
    show_status
    ;;
  logs)
    show_logs
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
