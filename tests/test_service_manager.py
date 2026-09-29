import importlib.util
import plistlib
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bilifan-service.py"


def load_manager():
    spec = importlib.util.spec_from_file_location("bilifan_service", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_watchdog_requires_consecutive_failures_and_cooldown():
    manager = load_manager()
    state = {"pid": 10, "since": 0, "failures": 0}
    for now in (130, 190):
        state, restart = manager.health_decision(state, pid=10, healthy=False, now=now)
        assert not restart
    state, restart = manager.health_decision(state, pid=10, healthy=False, now=250)
    assert restart
    for now in (310, 370, 430, 490):
        state, restart = manager.health_decision(state, pid=10, healthy=False, now=now)
        assert not restart
    state, restart = manager.health_decision(state, pid=10, healthy=False, now=550)
    assert restart


def test_watchdog_resets_on_recovery_and_new_process():
    manager = load_manager()
    state = {"pid": 10, "since": 0, "failures": 2}
    state, restart = manager.health_decision(state, pid=10, healthy=True, now=250)
    assert state["failures"] == 0 and not restart
    state, restart = manager.health_decision(state, pid=11, healthy=False, now=300)
    assert state["since"] == 300 and state["failures"] == 0 and not restart
    state, restart = manager.health_decision(state, pid=11, healthy=False, now=360)
    assert state["failures"] == 0 and not restart


def test_watchdog_never_restarts_unloaded_or_stopped_job():
    manager = load_manager()
    state = {"pid": 10, "since": 0, "failures": 99}
    state, restart = manager.health_decision(state, pid=None, healthy=False, now=500)
    assert not restart


def test_health_requires_expected_service_not_just_any_http_response():
    manager = load_manager()
    assert manager.valid_health("web", 403, {"detail": "Invalid Bilifan Web UI token."})
    assert not manager.valid_health("web", 403, {"detail": "unrelated"})
    assert manager.valid_health("tunnel", 200, {"readyConnections": 1})
    assert not manager.valid_health("tunnel", 200, {"readyConnections": 0})
    assert not manager.valid_health("tunnel", 302, {})


def test_generated_agents_use_local_bind_and_persistent_restart(tmp_path):
    manager = load_manager()
    plists = manager.make_plists(tmp_path, "/opt/homebrew/bin/cloudflared", {})
    for name, data in plists.items():
        assert plistlib.loads(plistlib.dumps(data)) == data
        assert data["RunAtLoad"]
        assert data["WorkingDirectory"] == str(manager.ROOT)
        assert "0.0.0.0" not in str(data)
        assert "token" not in data["ProgramArguments"]
    assert plists["web"]["KeepAlive"]
    assert plists["tunnel"]["KeepAlive"]
    assert plists["watchdog"]["StartInterval"] == 60
    assert "KeepAlive" not in plists["watchdog"]
    assert "127.0.0.1:20246" in plists["tunnel"]["ProgramArguments"]


def test_watchdog_is_read_only_when_agents_are_unloaded(tmp_path, monkeypatch):
    manager = load_manager()
    monkeypatch.setattr(manager, "LOG_DIR", tmp_path)
    monkeypatch.setattr(manager, "job_info", lambda name: {"loaded": False, "pid": None})
    monkeypatch.setattr(manager, "probe", lambda name: (False, "unreachable"))
    calls = []
    monkeypatch.setattr(manager, "launchctl", lambda *args, **kwargs: calls.append(args))
    manager.watchdog()
    assert not calls


@pytest.mark.parametrize("response,allowed", [
    ("302\nhttps://example.cloudflareaccess.com/cdn-cgi/access/login/bilifan.buyaoting.top", True),
    ("200\n", False),
    ("403\n", False),
    ("302\nhttps://unrelated.example/login", False),
])
def test_install_requires_the_access_gate(monkeypatch, response, allowed):
    manager = load_manager()
    monkeypatch.setattr(manager.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=response))
    if allowed:
        manager.check_access()
    else:
        with pytest.raises(RuntimeError):
            manager.check_access()


def test_watchdog_restarts_only_the_unhealthy_service(tmp_path, monkeypatch):
    manager = load_manager()
    monkeypatch.setattr(manager, "LOG_DIR", tmp_path)
    monkeypatch.setattr(manager.time, "time", lambda: 1000)
    monkeypatch.setattr(manager, "job_info", lambda name: {"loaded": True, "pid": 10 if name == "web" else 20})
    monkeypatch.setattr(manager, "probe", lambda name: (name == "tunnel", "probe result"))
    manager.atomic_json(tmp_path / "health.json", {
        "web": {"pid": 10, "since": 0, "failures": 2},
        "tunnel": {"pid": 20, "since": 0, "failures": 0},
    })
    calls = []

    def restart(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(manager, "launchctl", restart)
    manager.watchdog()
    assert calls == [("kickstart", "-k", manager.target("web"))]
    manager.watchdog()
    assert len(calls) == 1  # cooldown prevents repeated restart on the same failure


def test_manual_stop_disables_watchdog_first_and_never_kills_unrelated_jobs(monkeypatch):
    manager = load_manager()
    monkeypatch.setattr(manager, "job_info", lambda name: {"loaded": True, "pid": 10})
    waits = []
    monkeypatch.setattr(manager, "wait_unloaded", lambda name: waits.append(name))
    calls = []
    monkeypatch.setattr(manager, "launchctl", lambda *args, **kwargs: calls.append(args))
    manager.stop()
    assert calls == [(command, manager.target(name))
                     for name in ("watchdog", "tunnel", "web")
                     for command in ("disable", "bootout")]
    assert waits == ["watchdog", "tunnel", "web"]


def test_stop_waits_for_asynchronous_launchd_removal(monkeypatch):
    manager = load_manager()
    loaded = iter([True, True, False])
    monkeypatch.setattr(manager, "job_info", lambda name: {"loaded": next(loaded)})
    sleeps = []
    monkeypatch.setattr(manager.time, "sleep", lambda seconds: sleeps.append(seconds))
    manager.wait_unloaded("web")
    assert sleeps == [0.2, 0.2]
