from typer.testing import CliRunner

from bilifan.cli import app


runner = CliRunner()


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output


def test_summarize_command_prints_preflight_message():
    url = "https://www.bilibili.com/video/BV1abcDEF12G?p=2"

    result = runner.invoke(app, ["summarize", url])

    assert result.exit_code == 0
    assert f"preflight pending for {url}" in result.output
