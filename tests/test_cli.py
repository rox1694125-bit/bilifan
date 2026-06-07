import json

from typer.testing import CliRunner

import bilifan.cli as cli
from bilifan.cli import app


runner = CliRunner()
URL = "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999"


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output


def test_summarize_declines_local_processing_consent_without_writing_config(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        ["summarize", URL, "--out", str(outputs)],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "local processing consent" in result.output
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_prepares_offline_preflight_run_with_yes_flag(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "Prepared Bilifan run:" in result.output
    assert "BV1abcDEF12G_p2/runs/" in result.output
    assert str(outputs) not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert run_dir.is_dir()
    assert diagnostics["error_type"] is None
    assert diagnostics["exit_code"] == 0
    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["duration_check"] is None
    assert diagnostics["transcript_check"] is None
    assert diagnostics["warnings"] == ["foundation_slice_only"]
    assert (config_home / "config.json").exists()


def test_summarize_records_cookie_notice_without_storing_cookie_file_name(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    config_text = (config_home / "config.json").read_text(encoding="utf-8")
    assert "local_processing_notice_accepted_at" in config_text
    assert "cookies_notice_accepted_at" in config_text
    assert "bili-cookies.txt" not in config_text
    assert "/Users/jack" not in config_text


def test_summarize_invalid_url_writes_sanitized_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    invalid_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G/extra"
        "?p=2&vd_source=tracking-secret"
    )

    result = runner.invoke(
        app,
        ["summarize", invalid_url, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    error_runs = list((outputs / "_errors" / "runs").iterdir())
    assert len(error_runs) == 1

    diagnostics = json.loads(
        (error_runs[0] / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics["error_type"] == "InputError"
    assert diagnostics["exit_code"] == 2
    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == ""
    assert diagnostics["part_index"] == 0
    assert "vd_source" not in diagnostics["sanitized_message"]


def test_summarize_invalid_url_requires_consent_before_writing_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--out",
            str(outputs),
        ],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_invalid_url_retries_error_run_collision_without_leaking_path(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    original_create_error_run = cli.create_error_run
    calls = 0

    def fake_create_error_run(out_dir, *, now=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileExistsError("/Users/jack/outputs/_errors/runs/collision")
        return original_create_error_run(out_dir, now=now)

    monkeypatch.setattr(cli, "create_error_run", fake_create_error_run)

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert calls == 2
    assert "/Users/jack" not in result.output
    assert "collision" not in result.output
    assert len(list((outputs / "_errors" / "runs").glob("*/diagnostics.json"))) == 1


def test_summarize_debug_log_is_reserved_for_later_slice(tmp_path):
    config_home = tmp_path / "config-home"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--debug-log",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "--debug-log is reserved for a later slice" in result.output
