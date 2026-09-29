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

### Automatic login startup and recovery (macOS)

Install from a normal terminal as your logged-in user (do not use `sudo`):

```bash
cd /Volumes/mySSD/projects/bilifan
.venv/bin/python scripts/bilifan-service.py install
```

The installer verifies that the public URL still redirects to Cloudflare Access,
then migrates only Bilifan's legacy tmux sessions to three user LaunchAgents:
`top.buyaoting.bilifan.web`, `.tunnel`, and `.watchdog`. It preserves existing
explicit Bilifan token/config environment values if present. Plists are installed
under `~/Library/LaunchAgents` with mode 0600; logs and self-check state are in
`~/Library/Logs/BiliFAN`. No DNS, Access policy, proxy settings or file permissions
on the project data are changed.

- Web and Tunnel use `RunAtLoad` and `KeepAlive`; launchd relaunches exited
  processes, with 30-second throttling on rapid failures.
- The watchdog runs every 60 seconds. It checks the expected protected response
  from `127.0.0.1:8792/api/status` and the Tunnel's own readiness endpoint at
  `127.0.0.1:20246/ready` (at least one active edge connection).
- After a two-minute startup grace period, three consecutive failed checks
  restart only the unhealthy service. Each service has a five-minute restart
  cooldown. Healthy checks reset the failure counter.
- `cloudflared` also reconnects by itself after network interruptions. Its
  existing protocol configuration is preserved. The watchdog does not edit
  routing, credentials, authentication or Clash configuration.
- Logs rotate at 10 MiB with one backup per service. The health state is saved
  in `health.json`; periodic checks do not authenticate to external accounts.

After installation, the existing commands below automatically use launchd.
`stop` **also disables login auto-start** until `start` is run again. `status`
and `check` only inspect health; `watchdog` performs recovery.

```bash
scripts/bilifan-remote.sh status
scripts/bilifan-remote.sh check
scripts/bilifan-remote.sh logs
scripts/bilifan-remote.sh stop
scripts/bilifan-remote.sh start
```

Startup happens **after logging into macOS**, not before the FileVault/login
screen. The project is on an external SSD: it must be mounted at the same path,
and the Mac must be awake and online to serve visitors. launchd retries startup
when dependencies become available. This cannot fix revoked credentials,
damaged data, a powered-off machine, or a broken upstream network. A successful
public `302` only verifies the Access gate, not the application behind it.
Service recovery does not automatically re-run interrupted video jobs; the
existing queue marks an in-progress job as interrupted on restart.

The installation can be repeated to update the agents; previous plists are
backed up in the log directory. To remove auto-start, run `stop` first, remove
only these three plists and `.bilifan/launchd-installed.json`; the legacy tmux
commands then become available again.

On first background launch, macOS may request removable-volume access for
Python and cloudflared because the project is on `mySSD`. Complete the system
permission prompt yourself; until it is resolved the process can appear running
while waiting to open files. Do not disable macOS privacy protection to work
around this. After runtime/binary upgrades macOS may request access again.

Implementation references: [Apple launchd jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
and [cloudflared readiness semantics](https://github.com/cloudflare/cloudflared/blob/master/metrics/readiness.go).

Installation verification on 2026-09-06: all three jobs enabled; protected Web
health passed; Tunnel readiness reported four connections. Individually sending
SIGTERM to the managed Web and Tunnel resulted in new healthy processes without
manual restart. Manual stop followed by a watchdog invocation left both jobs
stopped; subsequent start restored both. Fifteen focused tests passed. The
existing insurance-workbench Tunnel process was unchanged. The public browser
reached Cloudflare Access's email-code login screen; post-login UI and an actual
full computer reboot were not exercised in this verification.

### Legacy tmux startup (before launchd installation)

Recommended daily entrypoint:

```bash
cd /Volumes/mySSD/projects/bilifan
scripts/bilifan-remote.sh restart
```

Check status:

```bash
scripts/bilifan-remote.sh status
```

Then open:

```text
https://bilifan.buyaoting.top
```

After Access login, the current-task panel should show the remote access status,
the public entrypoint, and the current job stage.

Stop both sessions:

```bash
cd /Volumes/mySSD/projects/bilifan
scripts/bilifan-remote.sh stop
```

Inspect recent output:

```bash
scripts/bilifan-remote.sh logs
```

Foreground alternative:

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

## Useful Environment Variables

The following overrides apply to the foreground and legacy tmux scripts.
The installed launchd manager currently uses the fixed deployment at port 8792,
`https://bilifan.buyaoting.top/`, the `bilifan` tunnel, the project-local
`.bilifan/cloudflared-bilifan.yml`, and `.venv/bin/python`. Setting these variables
does not reconfigure installed LaunchAgents. The installer only preserves the
explicit token/config/Codex executable overrides documented above.

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
- Bilifan API returns 403: this usually means the server was restarted and an
  old browser tab kept polling with an old local token. Reopen
  `https://bilifan.buyaoting.top` or refresh the current page; this is not a
  failed video task.
- Video tasks fail remotely but work locally: the remote browser only controls
  the UI. All downloads, Whisper, Codex, and file writes still happen on the Mac
  running Bilifan.
