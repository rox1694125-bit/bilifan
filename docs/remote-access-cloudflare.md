# Bilifan Cloudflare Remote Access

This guide exposes the local Bilifan Web UI at:

```text
https://bilifan.buyaoting.top
```

The safe shape is:

```text
Browser -> Cloudflare Access -> Cloudflare Tunnel -> http://127.0.0.1:8792
```

Bilifan should continue to listen on `127.0.0.1`. Do not bind Bilifan directly to
`0.0.0.0` or forward a router port to it.

## Why This Shape

Bilifan can read local output files, call your local Codex environment, download
audio, and may use local cookies in CLI flows. Cloudflare Access is the outer
identity gate; Bilifan's local token remains the inner workbench guard.

## Local Prerequisites

```bash
cd /Volumes/mySSD/projects/bilifan
cloudflared --version
.venv/bin/python -m bilifan serve --no-open --port 8792 --public-url https://bilifan.buyaoting.top
```

In another terminal:

```bash
curl -I http://127.0.0.1:8792/
```

Expected: HTTP 200 from the local Bilifan page.

## One-Time Cloudflare Setup

These commands write to your Cloudflare account and DNS. Run them only when you
are ready to create the tunnel.

```bash
cloudflared tunnel login
cloudflared tunnel create bilifan
cloudflared tunnel route dns bilifan bilifan.buyaoting.top
```

Then create the Bilifan-specific local config at
`.bilifan/cloudflared-bilifan.yml`. This avoids overwriting the existing
insurance workbench tunnel config in `~/.cloudflared/config.yml`.

```yaml
tunnel: <bilifan-tunnel-id>
credentials-file: /Users/jack/.cloudflared/<bilifan-tunnel-id>.json
protocol: http2

ingress:
  - hostname: bilifan.buyaoting.top
    service: http://127.0.0.1:8792
  - service: http_status:404
```

Replace `<bilifan-tunnel-id>` with the id printed by `cloudflared tunnel create
bilifan`. This file is ignored by git because it lives under `.bilifan/`.

## Cloudflare Access

In Cloudflare Zero Trust:

1. Go to Access -> Applications.
2. Add a self-hosted application.
3. Domain: `bilifan.buyaoting.top`.
4. Policy: allow only your own email address or a small trusted email list.
5. Keep the app behind HTTPS.

Do not leave the application with a public allow-all policy.

Do not start `cloudflared tunnel run` before this Access application is active.
Without Access, the public page can expose Bilifan's embedded local UI token to
anyone who can load the hostname.

## Daily Startup

Terminal 1:

```bash
cd /Volumes/mySSD/projects/bilifan
scripts/start-bilifan-for-cloudflare.sh
```

Terminal 2:

```bash
cd /Volumes/mySSD/projects/bilifan
BILIFAN_ACCESS_CONFIGURED=1 scripts/start-cloudflared-bilifan.sh
```

Then open:

```text
https://bilifan.buyaoting.top
```

## Useful Environment Variables

```bash
export BILIFAN_PORT=8792
export BILIFAN_PUBLIC_URL=https://bilifan.buyaoting.top
export BILIFAN_TUNNEL_NAME=bilifan
export BILIFAN_CLOUDFLARED_CONFIG=.bilifan/cloudflared-bilifan.yml
export BILIFAN_ACCESS_CONFIGURED=1
export BILIFAN_PYTHON=.venv/bin/python
```

## Troubleshooting

- Local page works but public page does not: check `cloudflared tunnel run bilifan`
  logs and the DNS route.
- Public page asks for Access login repeatedly: check the Access application
  domain and allowed email policy.
- Bilifan API returns 403: refresh the page from the current server instance.
  Old tabs contain an old local token after restart.
- Video tasks fail remotely but work locally: the remote browser only controls
  the UI. All downloads, Whisper, Codex, and file writes still happen on the Mac
  running Bilifan.
