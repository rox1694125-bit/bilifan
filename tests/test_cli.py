from typer.testing import CliRunner

from bilifan.cli import app


runner = CliRunner()


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output
