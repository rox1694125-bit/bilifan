#!/usr/bin/env python3
"""Manage BiliFAN's per-user launchd jobs, with conservative health recovery."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
SCRIPT = ROOT / "scripts/bilifan-service.py"
AGENT_DIR = Path.home() / "Library/LaunchAgents"
LOG_DIR = Path.home() / "Library/Logs/BiliFAN"
MARKER = ROOT / ".bilifan/launchd-installed.json"
DOMAIN = f"gui/{os.getuid()}"
PUBLIC_URL = "https://bilifan.buyaoting.top/"
LABELS = {name: f"top.buyaoting.bilifan.{name}" for name in ("web", "tunnel", "watchdog")}
URLS = {"web": "http://127.0.0.1:8792/api/status", "tunnel": "http://127.0.0.1:20246/ready"}
STARTUP_GRACE = 120
FAILURES_REQUIRED = 3
RESTART_COOLDOWN = 300


def launchctl(*args, check=True):
    result = subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=45)
    if check and result.returncode:
        raise RuntimeError(f"launchctl {' '.join(args)}: {result.stderr.strip()}")
    return result


def target(name):
    return f"{DOMAIN}/{LABELS[name]}"


def plist_path(name):
    return AGENT_DIR / f"{LABELS[name]}.plist"


def job_info(name):
    result = launchctl("print", target(name), check=False)
    match = re.search(r"^\s*pid = (\d+)$", result.stdout, re.M)
    return {"loaded": result.returncode == 0, "pid": int(match[1]) if match else None}


def valid_health(name, code, body):
    if not isinstance(body, dict):
        return False
    if name == "web":
        return code == 403 and body.get("detail") == "Invalid Bilifan Web UI token."
    return code == 200 and isinstance(body.get("readyConnections"), int) and body["readyConnections"] > 0


def probe(name):
    # Loopback requests must never inherit HTTP_PROXY / system proxy settings.
    opener = build_opener(ProxyHandler({}))
    try:
        try:
            response = opener.open(URLS[name], timeout=8)
        except HTTPError as exc:
            response = exc
        with response:
            code = response.code
            body = json.loads(response.read(16384))
        good = valid_health(name, code, body)
        detail = f"HTTP {code}"
        if name == "tunnel" and good:
            detail += f", {body['readyConnections']} edge connections"
        return good, detail
    except (OSError, ValueError) as exc:
        return False, type(exc).__name__


def health_decision(previous, *, pid, healthy, now):
    state = dict(previous)
    if pid is None:
        # launchd already restarts crashed processes; never undo an intentional stop.
        return {}, False
    if state.get("pid") != pid:
        state = {"pid": pid, "since": now, "failures": 0,
                 "last_restart": state.get("last_restart", 0)}
    if healthy:
        state["failures"] = 0
        return state, False
    if now - state.get("since", now) < STARTUP_GRACE:
        return state, False
    state["failures"] = state.get("failures", 0) + 1
    restart = (state["failures"] >= FAILURES_REQUIRED
               and (not state.get("last_restart")
                    or now - state["last_restart"] >= RESTART_COOLDOWN))
    if restart:
        state.update(last_restart=now, failures=0)
    return state, restart


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def watchdog():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "watchdog.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        state_path = LOG_DIR / "health.json"
        try:
            state = json.loads(state_path.read_text())
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        now = time.time()
        for name in ("web", "tunnel"):
            info = job_info(name)
            healthy, detail = probe(name) if info["loaded"] else (False, "not loaded")
            previous = state.get(name, {})
            updated, restart = health_decision(previous, pid=info["pid"], healthy=healthy, now=now)
            updated.update(healthy=healthy, detail=detail, checked_at=now)
            if restart:
                # Recheck the PID to avoid killing a replacement that launchd just started.
                if job_info(name)["pid"] == info["pid"]:
                    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} restart {name}: {detail}", flush=True)
                    result = launchctl("kickstart", "-k", target(name), check=False)
                    if result.returncode:
                        updated["restart_error"] = result.stderr.strip()
                        print(f"restart failed for {name}: {result.stderr.strip()}", flush=True)
            elif previous.get("healthy") != healthy:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {name}: {detail}; healthy={healthy}", flush=True)
            state[name] = updated
        atomic_json(state_path, state)
        # copy/truncate retains launchd's open descriptors; keep one bounded backup.
        for name in LABELS:
            log = LOG_DIR / f"{name}.log"
            if log.exists() and log.stat().st_size > 10 * 1024 * 1024:
                shutil.copyfile(log, log.with_suffix(".log.1"))
                with log.open("r+") as stream:
                    stream.truncate(0)


def make_plists(log_dir, cloudflared, extra_env):
    env = {
        "HOME": str(Path.home()),
        "PATH": f"{ROOT / '.venv/bin'}:{Path.home() / '.local/bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "PYTHONUNBUFFERED": "1",
    }
    commands = {
        "web": [str(PYTHON), "-m", "bilifan", "serve", "--no-open", "--host", "127.0.0.1",
                "--port", "8792", "--strict-port", "--public-url", PUBLIC_URL],
        "tunnel": [cloudflared, "tunnel", "--no-autoupdate", "--config",
                   str(ROOT / ".bilifan/cloudflared-bilifan.yml"),
                   "--metrics", "127.0.0.1:20246", "run", "bilifan"],
        "watchdog": [str(PYTHON), str(SCRIPT), "watchdog"],
    }
    result = {}
    for name, args in commands.items():
        data = {
            "Label": LABELS[name], "ProgramArguments": args,
            "WorkingDirectory": str(ROOT), "RunAtLoad": True,
            "EnvironmentVariables": env | (extra_env if name == "web" else {}),
            "StandardOutPath": str(log_dir / f"{name}.log"),
            "StandardErrorPath": str(log_dir / f"{name}.log"),
            "ThrottleInterval": 30, "ExitTimeOut": 30,
        }
        if name == "watchdog":
            data["StartInterval"] = 60
        else:
            data["KeepAlive"] = True
        result[name] = data
    return result


def check_access():
    # curl HEAD matches the manual check; Python's default HTTP client is blocked
    # by this hostname's edge bot filtering. Never follow the authentication URL.
    result = subprocess.run(
        ["/usr/bin/curl", "-sS", "-I", "--max-time", "15", "-o", "/dev/null",
         "-w", "%{http_code}\\n%{redirect_url}", PUBLIC_URL],
        capture_output=True, text=True, timeout=20, check=True,
    )
    code, _, location = result.stdout.partition("\n")
    parsed = urlsplit(location)
    if not (code == "302" and parsed.scheme == "https" and
            (parsed.hostname or "").endswith(".cloudflareaccess.com") and
            parsed.path.startswith("/cdn-cgi/access/login/")):
        raise RuntimeError("Cannot confirm the existing Cloudflare Access login gate; refusing installation.")


def legacy_sessions():
    binary = shutil.which("tmux")
    if not binary:
        return []
    result = []
    for socket_args in ([], ["-L", "bilifan"]):
        base = [binary, *socket_args]
        for name in ("bilifan-web", "bilifan-tunnel"):
            check = subprocess.run([*base, "list-panes", "-t", name, "-F", "#{pane_current_path}"],
                                   capture_output=True, text=True, timeout=5)
            if check.returncode == 0:
                if any(Path(line).resolve() != ROOT for line in check.stdout.splitlines()):
                    raise RuntimeError(f"Refusing to stop {name}: unexpected tmux working directory.")
                result.append((base, name))
    return result


def retained_env(sessions):
    result = {}
    allowed = ("BILIFAN_WEB_TOKEN", "BILIFAN_CONFIG_HOME", "BILIFAN_CODEX_BIN")
    if plist_path("web").exists():
        old = plistlib.loads(plist_path("web").read_bytes()).get("EnvironmentVariables", {})
        result.update({key: old[key] for key in allowed if old.get(key)})
    for base, name in sessions:
        if name != "bilifan-web":
            continue
        for key in allowed:
            read = subprocess.run([*base, "show-environment", "-t", name, key],
                                  capture_output=True, text=True, timeout=5)
            if read.returncode == 0 and read.stdout.startswith(key + "="):
                value = read.stdout.rstrip("\n").split("=", 1)[1]
                if value:
                    result[key] = value
    result.update({key: os.environ[key] for key in allowed if os.environ.get(key)})
    return result


def install():
    if sys.platform != "darwin" or os.getuid() == 0:
        raise RuntimeError("Install as the logged-in macOS user, without sudo.")
    cloudflared = shutil.which("cloudflared")
    if not cloudflared or not PYTHON.exists() or not (ROOT / ".bilifan/cloudflared-bilifan.yml").exists():
        raise RuntimeError("Missing Python runtime, cloudflared, or Bilifan tunnel configuration.")
    check_access()
    sessions = legacy_sessions()
    documents = make_plists(LOG_DIR, cloudflared, retained_env(sessions))
    AGENT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.chmod(0o700)
    for name, data in documents.items():
        path = plist_path(name)
        if path.exists():
            old = plistlib.loads(path.read_bytes())
            if old.get("WorkingDirectory") != str(ROOT):
                raise RuntimeError(f"Existing agent belongs to a different project: {path}")
            backup = LOG_DIR / f"{path.name}.{time.time_ns()}.bak"
            shutil.copyfile(path, backup)
            backup.chmod(0o600)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(plistlib.dumps(data))
        temporary.chmod(0o600)
        temporary.replace(path)
        subprocess.run(["/usr/bin/plutil", "-lint", str(path)], check=True)
    # Do not touch other projects' tmux sessions or launch agents.
    stop()
    for base, name in sessions:
        subprocess.run([*base, "kill-session", "-t", name], check=True)
    atomic_json(MARKER, {"root": str(ROOT), "labels": LABELS, "installed_at": time.time()})
    start()
    print("Installed login startup and automatic recovery. Public URL: " + PUBLIC_URL)


def start():
    for name in LABELS:
        if not plist_path(name).exists():
            raise RuntimeError("LaunchAgents not installed. Run: .venv/bin/python scripts/bilifan-service.py install")
        launchctl("enable", target(name))
        if not job_info(name)["loaded"]:
            launchctl("bootstrap", DOMAIN, str(plist_path(name)))
        elif name != "watchdog" and not job_info(name)["pid"]:
            launchctl("kickstart", target(name))


def stop():
    # Persistent disable also prevents the watchdog/login from undoing manual stop.
    for name in ("watchdog", "tunnel", "web"):
        launchctl("disable", target(name))
        if job_info(name)["loaded"]:
            launchctl("bootout", target(name))
            wait_unloaded(name)


def wait_unloaded(name):
    # bootout acknowledges before a job finishes its graceful shutdown. A start
    # during that gap can observe the dying job and incorrectly skip bootstrap.
    deadline = time.monotonic() + 40
    while job_info(name)["loaded"]:
        if time.monotonic() >= deadline:
            raise RuntimeError(f"{name} has not finished stopping; retry start after it exits.")
        time.sleep(0.2)


def show_status():
    good = True
    for name in LABELS:
        info = job_info(name)
        if name == "watchdog":
            print(f"watchdog: {'loaded (every 60s)' if info['loaded'] else 'stopped'}")
            good = good and info["loaded"]
        else:
            healthy, detail = probe(name)
            print(f"{name}: pid={info['pid']}, healthy={healthy}, {detail}")
            good = good and info["loaded"] and bool(info["pid"]) and healthy
    print("Public URL: " + PUBLIC_URL)
    print("Logs: " + str(LOG_DIR))
    print("Local checks do not verify the page after Cloudflare Access login.")
    return good


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["install", "start", "stop", "restart", "status", "check", "logs", "watchdog"])
    args = parser.parse_args()
    if args.command == "install":
        install()
    elif args.command == "start":
        start()
    elif args.command == "stop":
        stop()
        print("Stopped; login auto-start disabled until the next start command.")
    elif args.command == "restart":
        stop()
        start()
    elif args.command in ("status", "check"):
        return 0 if show_status() else 1
    elif args.command == "watchdog":
        watchdog()
    else:
        for name in LABELS:
            log = LOG_DIR / f"{name}.log"
            print(f"{name}: {log}")
            if log.exists():
                subprocess.run(["/usr/bin/tail", "-n", "20", str(log)], check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"BiliFAN service error: {exc}", file=sys.stderr)
        raise SystemExit(1)
