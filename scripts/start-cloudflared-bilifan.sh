#!/usr/bin/env bash
set -euo pipefail

TUNNEL_NAME="${BILIFAN_TUNNEL_NAME:-bilifan}"
CONFIG_PATH="${BILIFAN_CLOUDFLARED_CONFIG:-.bilifan/cloudflared-bilifan.yml}"
ACCESS_CONFIGURED="${BILIFAN_ACCESS_CONFIGURED:-}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed or not on PATH." >&2
  echo "Install it with: brew install cloudflared" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "No Bilifan cloudflared config found: $CONFIG_PATH" >&2
  echo "Follow docs/remote-access-cloudflare.md before running this script." >&2
  exit 1
fi

if [[ "$ACCESS_CONFIGURED" != "1" ]]; then
  echo "Refusing to start the public tunnel until Cloudflare Access is configured." >&2
  echo "After Access restricts bilifan.buyaoting.top to your email, run:" >&2
  echo "BILIFAN_ACCESS_CONFIGURED=1 $0" >&2
  exit 1
fi

echo "Starting Cloudflare Tunnel: ${TUNNEL_NAME}"
exec cloudflared tunnel --config "$CONFIG_PATH" run "$TUNNEL_NAME"
