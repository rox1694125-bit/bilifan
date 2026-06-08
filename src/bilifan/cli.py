import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer

from .bilibili import parse_bilibili_url
from .config import (
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    write_consent,
)
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .metadata import MetadataIngestError, fetch_current_part_metadata
from .runs import RunPaths, create_error_run, create_run

app = typer.Typer(no_args_is_help=True)

LOCAL_PROCESSING_NOTICE = (
    "Bilifan local processing consent:\n"
    "Bilifan prepares runs locally on this machine and writes output files under "
    "the selected --out directory. This foundation slice does not download media, "
    "call external AI tools, or generate a report."
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
    _reserved_mvp_options = (
        output_format,
        transcriber,
        force_whisper,
        llm_provider,
        llm_model,
        require_pdf,
        allow_long_video,
    )
    if debug_log:
        raise typer.BadParameter("--debug-log is reserved for a later slice.")

    uses_cookies = cookies_from_browser is not None or cookies_file is not None
    _ensure_consent(uses_cookies=uses_cookies, yes_i_understand=yes_i_understand)

    try:
        ref = parse_bilibili_url(url)
    except ValueError as exc:
        run = _create_error_run_with_retry(out)
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="InputError",
                exit_code=2,
                stage="preflight",
                video_id="",
                part_index=0,
                duration_check=None,
                transcript_check=None,
                artifact_paths=["diagnostics.json"],
                sanitized_message=sanitized_message,
                warnings=["foundation_slice_only"],
            ),
        )
        raise typer.BadParameter(sanitized_message) from exc

    try:
        run = create_run(out, ref, overwrite=overwrite)
    except FileExistsError as exc:
        raise typer.BadParameter(
            "Run directory already exists; use --overwrite or retry later."
        ) from exc

    try:
        metadata = fetch_current_part_metadata(
            ref,
            run.run_dir,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
    except MetadataIngestError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="MetadataIngestError",
                exit_code=1,
                stage="metadata",
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=None,
                transcript_check=None,
                artifact_paths=["diagnostics.json"],
                sanitized_message=sanitized_message,
                warnings=["metadata_failed"],
            ),
        )
        typer.echo(sanitized_message, err=True)
        raise typer.Exit(1) from exc

    _write_metadata(run.run_dir / "metadata.json", metadata)
    write_diagnostics(
        run.run_dir / "diagnostics.json",
        Diagnostics(
            error_type=None,
            exit_code=0,
            stage="metadata",
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=None,
            transcript_check=None,
            artifact_paths=["diagnostics.json", "metadata.json"],
            sanitized_message="Metadata ingest completed.",
            warnings=["metadata_only"],
        ),
    )
    typer.echo(f"Prepared Bilifan run: {_display_run_path(run)}")


def _create_error_run_with_retry(out: Path) -> RunPaths:
    for attempt in range(5):
        try:
            if attempt == 0:
                return create_error_run(out)
            next_second = datetime.now(timezone.utc) + timedelta(seconds=attempt)
            return create_error_run(out, now=next_second)
        except FileExistsError:
            continue
    raise typer.BadParameter("Could not create error diagnostics run; retry later.")


def _display_run_path(run: RunPaths) -> str:
    return f"{run.video_dir.name}/runs/{run.run_id}"


def _write_metadata(path: Path, metadata: dict) -> None:
    path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


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
