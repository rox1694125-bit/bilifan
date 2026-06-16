# Bilifan Cloudflare Remote Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prepare Bilifan for safe Cloudflare Tunnel remote access at `https://bilifan.buyaoting.top`.

**Architecture:** Bilifan continues to listen only on `127.0.0.1`; Cloudflare Tunnel forwards the public hostname to the local port. Cloudflare Access provides the outer login layer, and Bilifan's local token remains active.

**Tech Stack:** Typer CLI, FastAPI Web UI, `cloudflared`, shell scripts, pytest.

---

### Task 1: Public URL CLI Display

**Files:**
- Modify: `src/bilifan/cli.py`
- Test: `tests/test_cli.py`

- [x] **Step 1: Write failing tests**

Add tests proving `--public-url https://bilifan.buyaoting.top` prints a public
entrypoint and still binds uvicorn to `127.0.0.1`, and proving non-HTTPS public
URLs are rejected.

- [x] **Step 2: Run tests to verify failure**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py::test_serve_public_url_prints_remote_entrypoint_without_changing_bind tests/test_cli.py::test_serve_public_url_rejects_non_https_url -q
```

Expected before implementation: both tests fail because `--public-url` does not
exist.

- [x] **Step 3: Implement minimal CLI support**

Add `--public-url`, validate that it starts with `https://`, reject query strings
and fragments, print `Local URL:` and `Public URL:`, and keep `uvicorn.run(...,
host="127.0.0.1")`.

- [x] **Step 4: Run tests to verify pass**

Run:

```bash
.venv/bin/python -m pytest tests/test_cli.py::test_serve_public_url_prints_remote_entrypoint_without_changing_bind tests/test_cli.py::test_serve_public_url_rejects_non_https_url -q
```

Expected: `2 passed`.

### Task 2: Cloudflare Docs And Scripts

**Files:**
- Create: `docs/remote-access-cloudflare.md`
- Create: `scripts/start-bilifan-for-cloudflare.sh`
- Create: `scripts/start-cloudflared-bilifan.sh`
- Create local ignored file: `.bilifan/cloudflared-bilifan.yml`
- Modify: `README.md`

- [x] **Step 1: Document the safe network shape**

Document Browser -> Cloudflare Access -> Cloudflare Tunnel ->
`http://127.0.0.1:8792`, and explicitly warn against direct public binding.

- [x] **Step 2: Add startup scripts**

Add one script for starting Bilifan with `--public-url` and one script for
running the named Cloudflare tunnel from `.bilifan/cloudflared-bilifan.yml`.
The tunnel script refuses to run unless `BILIFAN_ACCESS_CONFIGURED=1` is set.

- [x] **Step 3: Verify docs and scripts**

Run:

```bash
bash -n scripts/start-bilifan-for-cloudflare.sh
bash -n scripts/start-cloudflared-bilifan.sh
.venv/bin/python -m pytest tests/test_cli.py -q
```

Expected: shell syntax checks pass and CLI tests pass.
