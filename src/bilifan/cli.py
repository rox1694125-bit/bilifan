from pathlib import Path

import typer

from .chunking import ChunkingError, LongVideoConfirmationRequired
from .config import (
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    write_consent,
)
from .diagnostics import redact_text
from .media import MediaDownloadError
from .metadata import MetadataIngestError
from .pipeline import (
    PipelineRequest,
    PipelineRunError,
    run_summarize_pipeline,
    validate_output_format,
)
from .renderer import PdfExportError
from .summarizer import SummarizationError
from .transcript import TranscriptError

app = typer.Typer(no_args_is_help=True)

LOCAL_PROCESSING_NOTICE = (
    "Bilifan local processing consent:\n"
    "Bilifan prepares runs locally on this machine, downloads current-P audio for "
    "local processing, and writes output files under the selected --out directory. "
    "By default it calls your configured Codex CLI to summarize transcript chunks, "
    "which may send transcript text to the model service behind that Codex account."
)
COOKIES_NOTICE = (
    "Bilifan cookies notice:\n"
    "Cookie options are reserved for local use only. Bilifan does not store cookies "
    "or cookie file names in reports or config."
)


@app.callback()
def callback() -> None:
    pass


@app.command()
def summarize(
    url: str,
    out: Path = typer.Option(Path("./outputs"), "--out"),
    cookies_from_browser: str | None = typer.Option(None, "--cookies-from-browser"),
    cookies_file: Path | None = typer.Option(None, "--cookies-file"),
    output_format: str = typer.Option("html,pdf", "--format"),
    transcriber: str = typer.Option("auto", "--transcriber"),
    force_whisper: bool = typer.Option(False, "--force-whisper"),
    llm_provider: str = typer.Option("codex-exec", "--llm-provider"),
    llm_model: str = typer.Option("gpt-5.5", "--llm-model"),
    require_pdf: bool = typer.Option(False, "--require-pdf"),
    allow_long_video: bool = typer.Option(False, "--allow-long-video"),
    yes_i_understand: bool = typer.Option(False, "--yes-i-understand"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    debug_log: bool = typer.Option(False, "--debug-log"),
) -> None:
    """Prepare a local Bilifan run for one Bilibili current-P URL."""
    if debug_log:
        raise typer.BadParameter("--debug-log is reserved for a later slice.")
    try:
        validate_output_format(output_format)
    except ValueError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc

    uses_cookies = cookies_from_browser is not None or cookies_file is not None
    _ensure_consent(uses_cookies=uses_cookies, yes_i_understand=yes_i_understand)

    try:
        result = run_summarize_pipeline(
            PipelineRequest(
                url=url,
                out=out,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                output_format=output_format,
                transcriber=transcriber,
                force_whisper=force_whisper,
                llm_provider=llm_provider,
                llm_model=llm_model,
                require_pdf=require_pdf,
                allow_long_video=allow_long_video,
                yes_i_understand=yes_i_understand,
                overwrite=overwrite,
                confirm_long_video=lambda message: typer.confirm(
                    f"{message} Continue?"
                ),
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc
    except PipelineRunError as exc:
        if exc.exit_code == 2:
            raise typer.BadParameter(redact_text(str(exc))) from exc
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(exc.exit_code) from exc
    except (
        MetadataIngestError,
        MediaDownloadError,
        TranscriptError,
        ChunkingError,
        SummarizationError,
        PdfExportError,
        LongVideoConfirmationRequired,
    ) as exc:
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Prepared Bilifan run: {result.run_key}")


def _ensure_consent(*, uses_cookies: bool, yes_i_understand: bool) -> None:
    config_path = default_config_path()
    needs_local_notice = not has_local_processing_consent(config_path)
    needs_cookies_notice = uses_cookies and not has_cookies_consent(config_path)

    if not needs_local_notice and not needs_cookies_notice:
        return

    if yes_i_understand:
        write_consent(
            config_path,
            local_processing=needs_local_notice,
            cookies=needs_cookies_notice,
            accepted_via="yes-i-understand",
        )
        return

    if needs_local_notice:
        typer.echo(LOCAL_PROCESSING_NOTICE)
        accepted = typer.confirm("Continue?", default=False)
        if not accepted:
            raise typer.Exit(1)
        write_consent(config_path, local_processing=True, accepted_via="prompt")

    if needs_cookies_notice:
        typer.echo(COOKIES_NOTICE)
        accepted = typer.confirm("Continue with cookies?", default=False)
        if not accepted:
            raise typer.Exit(1)
        write_consent(config_path, cookies=True, accepted_via="prompt")


def main() -> None:
    app()
