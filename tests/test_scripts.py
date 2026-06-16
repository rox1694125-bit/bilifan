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
