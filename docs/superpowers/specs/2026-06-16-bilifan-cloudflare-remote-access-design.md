# Bilifan Cloudflare Remote Access Design

## Goal

Expose the Bilifan Web UI at `https://bilifan.buyaoting.top` so the user can
operate the local Mac-hosted workbench from other computers.

## Decision

Use Cloudflare Tunnel with Cloudflare Access. Bilifan stays bound to
`127.0.0.1`, and `cloudflared` forwards `bilifan.buyaoting.top` to
`http://127.0.0.1:8792`.

## Security Boundary

Cloudflare Access is the outer identity boundary. Bilifan's per-server token
remains an inner guard against stale tabs and unauthenticated API calls. The
project must not encourage direct public binding or router port forwarding.

## Local Project Changes

- Add `bilifan serve --public-url` to print the remote entrypoint while keeping
  the bind address local-only.
- Add scripts for starting Bilifan and the named tunnel.
- Use a Bilifan-specific ignored `cloudflared` config under `.bilifan/` so the
  existing insurance workbench tunnel config is not overwritten.
- Refuse to start the public tunnel from the helper script unless the operator
  explicitly confirms Cloudflare Access is configured.
- Add Cloudflare setup documentation for `bilifan.buyaoting.top`.

## Out Of Scope

- Automatically creating Cloudflare tunnels, DNS routes, or Access policies.
- Replacing Cloudflare Access with Bilifan-managed multi-user auth.
- Running Bilifan as a background service at boot.
