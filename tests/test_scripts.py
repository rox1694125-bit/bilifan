import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_bilifan_remote_script_is_a_valid_single_entrypoint():
    script = ROOT / "scripts" / "bilifan-remote.sh"

    result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    content = script.read_text(encoding="utf-8")

    assert result.returncode == 0, result.stderr
    assert "start|stop|restart|status|logs" in content
    assert "start-bilifan-remote-tmux.sh" in content
    assert "stop-bilifan-remote-tmux.sh" in content
    assert 'capture_recent_output "$WEB_SESSION" "Web UI"' in content
    assert 'capture_recent_output "$TUNNEL_SESSION" "Cloudflare tunnel"' in content
    assert 'echo "Recent $label output:"' in content
    assert "https://bilifan.buyaoting.top" in content


def test_remote_start_script_starts_without_web_token(tmp_path):
    # Isolate from installed launch agents; this test must never start real services.
    script = tmp_path / "project" / "scripts" / "start-bilifan-remote-tmux.sh"
    script.parent.mkdir(parents=True)
    script.write_text((ROOT / "scripts" / script.name).read_text(), encoding="utf-8")
    runtime = script.parent.parent / ".venv" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("#!/bin/sh\nexit 0\n")
    runtime.chmod(0o755)
    config = script.parent.parent / ".bilifan" / "cloudflared-bilifan.yml"
    config.parent.mkdir()
    config.write_text("# test fixture\n")
    fake_tmux = tmp_path / "tmux"
    fake_tmux.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "has-session" ]]; then exit 1; fi\n'
        'if [[ "${1:-}" == "new-session" ]]; then exit 0; fi\n'
        "exit 2\n",
        encoding="utf-8",
    )
    fake_tmux.chmod(0o755)
    env = os.environ | {"PATH": f"{tmp_path}:{os.environ['PATH']}", "BILIFAN_WEB_TOKEN": ""}

    result = subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "started tmux session: bilifan-web" in result.stdout
