import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import typer

from .bilibili import parse_bilibili_url
from .chunking import ChunkingError, LongVideoConfirmationRequired, build_chunks
from .config import (
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    write_consent,
)
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .media import MediaDownloadError, download_current_part_audio
from .metadata import MetadataIngestError, fetch_current_part_metadata
from .renderer import PdfExportError, export_report_pdf, render_report_html
from .runs import RunPaths, create_error_run, create_run
from .summarizer import SummarizationError, summarize_chunks
from .transcript import TranscriptError, build_transcript

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
    _reserved_mvp_options = (
        require_pdf,
    )
    if debug_log:
        raise typer.BadParameter("--debug-log is reserved for a later slice.")
    requested_formats = _parse_output_formats(output_format)
    should_export_pdf = "pdf" in requested_formats or require_pdf

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
    try:
        media = download_current_part_audio(
            ref,
            metadata,
            run.run_dir,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
        )
    except MediaDownloadError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="MediaDownloadError",
                exit_code=1,
                stage="media",
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=exc.duration_check,
                transcript_check=None,
                artifact_paths=["diagnostics.json", "metadata.json"],
                sanitized_message=sanitized_message,
                warnings=["media_failed"],
            ),
        )
        typer.echo(sanitized_message, err=True)
        raise typer.Exit(1) from exc

    try:
        transcript = build_transcript(
            metadata,
            media,
            run.run_dir,
            force_whisper=force_whisper,
            transcriber=transcriber,
        )
    except TranscriptError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="TranscriptError",
                exit_code=1,
                stage="transcript",
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=media["duration_check"],
                transcript_check=exc.transcript_check,
                artifact_paths=[
                    "diagnostics.json",
                    "metadata.json",
                    media["audio_path"],
                ],
                sanitized_message=sanitized_message,
                warnings=["transcript_failed"],
            ),
        )
        typer.echo(sanitized_message, err=True)
        raise typer.Exit(1) from exc

    _write_json(run.run_dir / "transcript.json", transcript)
    try:
        chunks = build_chunks(
            transcript,
            media,
            allow_long_video=allow_long_video,
            long_video_confirmed=yes_i_understand,
        )
    except LongVideoConfirmationRequired as exc:
        if not typer.confirm(f"{exc.sanitized_message} Continue?"):
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=exc.sanitized_message,
                warnings=["chunking_confirmation_required"],
            )
            raise typer.Exit(1) from exc
        try:
            chunks = build_chunks(
                transcript,
                media,
                allow_long_video=allow_long_video,
                long_video_confirmed=True,
            )
        except ChunkingError as retry_exc:
            sanitized_message = redact_text(str(retry_exc))
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=sanitized_message,
                warnings=["chunking_failed"],
            )
            typer.echo(sanitized_message, err=True)
            raise typer.Exit(1) from retry_exc
    except ChunkingError as exc:
        sanitized_message = redact_text(str(exc))
        _write_chunking_failure_diagnostics(
            run,
            ref,
            media,
            transcript,
            sanitized_message=sanitized_message,
            warnings=["chunking_failed"],
        )
        typer.echo(sanitized_message, err=True)
        raise typer.Exit(1) from exc

    _write_json(run.run_dir / "chunks.json", chunks)
    try:
        chapters = summarize_chunks(
            ref=ref,
            metadata=metadata,
            chunks=chunks,
            run_dir=run.run_dir,
            provider=llm_provider,
            model=llm_model,
            style="学习笔记",
        )
    except SummarizationError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="SummarizationError",
                exit_code=1,
                stage="summarization",
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=media["duration_check"],
                transcript_check=transcript["transcript_check"],
                artifact_paths=[
                    "diagnostics.json",
                    "metadata.json",
                    media["audio_path"],
                    "transcript.json",
                    "chunks.json",
                    *_partial_summary_artifacts(run.run_dir),
                ],
                sanitized_message=sanitized_message,
                warnings=["summarization_failed"],
            ),
        )
        typer.echo(sanitized_message, err=True)
        raise typer.Exit(1) from exc

    _write_json(run.run_dir / "chapters.json", chapters)
    report_html = render_report_html(
        ref=ref,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        run_dir=run.run_dir,
    )
    render_warnings: list[str] = []
    render_artifacts = [
        "diagnostics.json",
        "metadata.json",
        media["audio_path"],
        "transcript.json",
        "chunks.json",
        "chapters.json",
        report_html.name,
    ]
    if should_export_pdf:
        try:
            report_pdf = export_report_pdf(
                html_path=report_html,
                pdf_path=run.run_dir / "report.pdf",
            )
            render_artifacts.append(report_pdf.name)
        except PdfExportError as exc:
            sanitized_message = redact_text(str(exc))
            if require_pdf:
                write_diagnostics(
                    run.run_dir / "diagnostics.json",
                    Diagnostics(
                        error_type="PdfExportError",
                        exit_code=1,
                        stage="render",
                        video_id=ref.bvid,
                        part_index=ref.part_index,
                        duration_check=media["duration_check"],
                        transcript_check=transcript["transcript_check"],
                        artifact_paths=render_artifacts,
                        sanitized_message=sanitized_message,
                        warnings=["pdf_failed"],
                    ),
                )
                typer.echo(sanitized_message, err=True)
                raise typer.Exit(1) from exc
            render_warnings.append("pdf_failed")

    if transcript["transcript_check"]["status"] == "transcript_incomplete":
        render_warnings.append("transcript_incomplete")

    write_diagnostics(
        run.run_dir / "diagnostics.json",
        Diagnostics(
            error_type=None,
            exit_code=0,
            stage="render",
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=media["duration_check"],
            transcript_check=transcript["transcript_check"],
            artifact_paths=render_artifacts,
            sanitized_message="Report rendering completed.",
            warnings=render_warnings,
        ),
    )
    typer.echo(f"Prepared Bilifan run: {_display_run_path(run)}")


def _write_chunking_failure_diagnostics(
    run: RunPaths,
    ref,
    media: dict,
    transcript: dict,
    *,
    sanitized_message: str,
    warnings: list[str],
) -> None:
    write_diagnostics(
        run.run_dir / "diagnostics.json",
        Diagnostics(
            error_type="ChunkingError",
            exit_code=1,
            stage="chunking",
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=media["duration_check"],
            transcript_check=transcript["transcript_check"],
            artifact_paths=[
                "diagnostics.json",
                "metadata.json",
                media["audio_path"],
                "transcript.json",
            ],
            sanitized_message=sanitized_message,
            warnings=warnings,
        ),
    )


def _partial_summary_artifacts(run_dir: Path) -> list[str]:
    partial_dir = run_dir / "partial_summaries"
    if not partial_dir.is_dir():
        return []
    return [
        f"partial_summaries/{path.name}"
        for path in sorted(partial_dir.glob("*.json"))
        if path.is_file()
    ]


def _parse_output_formats(raw_format: str) -> set[str]:
    formats = {
        item.strip().lower()
        for item in raw_format.split(",")
        if item.strip()
    }
    if not formats:
        raise typer.BadParameter("--format must include html, pdf, or html,pdf.")
    unsupported = formats - {"html", "pdf"}
    if unsupported:
        raise typer.BadParameter(
            "Unsupported --format value: " + ", ".join(sorted(unsupported))
        )
    return formats


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
    _write_json(path, metadata)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
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
