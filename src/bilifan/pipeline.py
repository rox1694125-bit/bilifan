from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .bilibili import parse_bilibili_url
from .chunking import ChunkingError, LongVideoConfirmationRequired, build_chunks
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .media import MediaDownloadError, download_current_part_audio
from .metadata import MetadataIngestError, fetch_current_part_metadata
from .renderer import PdfExportError, export_report_pdf, render_report_html
from .runs import RunPaths, create_error_run, create_run
from .summarizer import SummarizationError, summarize_chunks
from .transcript import TranscriptError, build_transcript


class PipelineStage(str, Enum):
    PREFLIGHT = "preflight"
    METADATA = "metadata"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    CHUNKING = "chunking"
    SUMMARIZATION = "summarization"
    RENDER = "render"


ProgressCallback = Callable[[str, str, str], None]
LongVideoConfirmCallback = Callable[[str], bool]


@dataclass(frozen=True)
class PipelineRequest:
    url: str
    out: Path
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    output_format: str = "html,pdf"
    transcriber: str = "auto"
    force_whisper: bool = False
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    require_pdf: bool = False
    allow_long_video: bool = False
    yes_i_understand: bool = False
    overwrite: bool = False
    confirm_long_video: LongVideoConfirmCallback | None = None


@dataclass(frozen=True)
class PipelineResult:
    run_key: str
    run_dir: Path
    diagnostics_path: Path
    artifact_paths: list[str]
    warnings: list[str]


def default_progress(stage: str, status: str, message: str) -> None:
    return None


def validate_output_format(raw_format: str) -> None:
    _parse_output_formats(raw_format)


def run_summarize_pipeline(
    request: PipelineRequest,
    *,
    progress_callback: ProgressCallback = default_progress,
) -> PipelineResult:
    requested_formats = _parse_output_formats(request.output_format)
    should_export_pdf = "pdf" in requested_formats or request.require_pdf

    _progress(progress_callback, PipelineStage.PREFLIGHT, "running", "Validating input.")
    try:
        ref = parse_bilibili_url(request.url)
    except ValueError as exc:
        run = _create_error_run_with_retry(request.out)
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="InputError",
                exit_code=2,
                stage=PipelineStage.PREFLIGHT.value,
                video_id="",
                part_index=0,
                duration_check=None,
                transcript_check=None,
                artifact_paths=["diagnostics.json"],
                sanitized_message=sanitized_message,
                warnings=["foundation_slice_only"],
            ),
        )
        _progress(
            progress_callback,
            PipelineStage.PREFLIGHT,
            "failed",
            sanitized_message,
        )
        raise ValueError(sanitized_message) from exc

    try:
        run = create_run(request.out, ref, overwrite=request.overwrite)
    except FileExistsError as exc:
        message = "Run directory already exists; use --overwrite or retry later."
        _progress(progress_callback, PipelineStage.PREFLIGHT, "failed", message)
        raise ValueError(message) from exc
    _progress(progress_callback, PipelineStage.PREFLIGHT, "done", "Input accepted.")

    _progress(progress_callback, PipelineStage.METADATA, "running", "Fetching metadata.")
    try:
        metadata = fetch_current_part_metadata(
            ref,
            run.run_dir,
            cookies_from_browser=request.cookies_from_browser,
            cookies_file=request.cookies_file,
        )
    except MetadataIngestError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="MetadataIngestError",
                exit_code=1,
                stage=PipelineStage.METADATA.value,
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=None,
                transcript_check=None,
                artifact_paths=["diagnostics.json"],
                sanitized_message=sanitized_message,
                warnings=["metadata_failed"],
            ),
        )
        _progress(progress_callback, PipelineStage.METADATA, "failed", sanitized_message)
        raise

    _write_json(run.run_dir / "metadata.json", metadata)
    _progress(progress_callback, PipelineStage.METADATA, "done", "Metadata saved.")

    _progress(progress_callback, PipelineStage.AUDIO, "running", "Downloading audio.")
    try:
        media = download_current_part_audio(
            ref,
            metadata,
            run.run_dir,
            cookies_from_browser=request.cookies_from_browser,
            cookies_file=request.cookies_file,
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
        _progress(progress_callback, PipelineStage.AUDIO, "failed", sanitized_message)
        raise
    _progress(progress_callback, PipelineStage.AUDIO, "done", "Audio ready.")

    _progress(progress_callback, PipelineStage.TRANSCRIPT, "running", "Building transcript.")
    try:
        transcript = build_transcript(
            metadata,
            media,
            run.run_dir,
            force_whisper=request.force_whisper,
            transcriber=request.transcriber,
        )
    except TranscriptError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="TranscriptError",
                exit_code=1,
                stage=PipelineStage.TRANSCRIPT.value,
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
        _progress(progress_callback, PipelineStage.TRANSCRIPT, "failed", sanitized_message)
        raise

    _write_json(run.run_dir / "transcript.json", transcript)
    _progress(progress_callback, PipelineStage.TRANSCRIPT, "done", "Transcript saved.")

    _progress(progress_callback, PipelineStage.CHUNKING, "running", "Building chunks.")
    try:
        chunks = build_chunks(
            transcript,
            media,
            allow_long_video=request.allow_long_video,
            long_video_confirmed=request.yes_i_understand,
        )
    except LongVideoConfirmationRequired as exc:
        if request.confirm_long_video is None:
            _progress(
                progress_callback,
                PipelineStage.CHUNKING,
                "failed",
                exc.sanitized_message,
            )
            raise
        if not request.confirm_long_video(exc.sanitized_message):
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=exc.sanitized_message,
                warnings=["chunking_confirmation_required"],
            )
            _progress(
                progress_callback,
                PipelineStage.CHUNKING,
                "failed",
                exc.sanitized_message,
            )
            raise
        try:
            chunks = build_chunks(
                transcript,
                media,
                allow_long_video=request.allow_long_video,
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
            _progress(
                progress_callback,
                PipelineStage.CHUNKING,
                "failed",
                sanitized_message,
            )
            raise
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
        _progress(progress_callback, PipelineStage.CHUNKING, "failed", sanitized_message)
        raise

    _write_json(run.run_dir / "chunks.json", chunks)
    _progress(progress_callback, PipelineStage.CHUNKING, "done", "Chunks saved.")

    _progress(
        progress_callback,
        PipelineStage.SUMMARIZATION,
        "running",
        "Summarizing chunks.",
    )
    try:
        chapters = summarize_chunks(
            ref=ref,
            metadata=metadata,
            chunks=chunks,
            run_dir=run.run_dir,
            provider=request.llm_provider,
            model=request.llm_model,
            style="学习笔记",
        )
    except SummarizationError as exc:
        sanitized_message = redact_text(str(exc))
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="SummarizationError",
                exit_code=1,
                stage=PipelineStage.SUMMARIZATION.value,
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
        _progress(
            progress_callback,
            PipelineStage.SUMMARIZATION,
            "failed",
            sanitized_message,
        )
        raise
    _write_json(run.run_dir / "chapters.json", chapters)
    _progress(
        progress_callback,
        PipelineStage.SUMMARIZATION,
        "done",
        "Summaries saved.",
    )

    _progress(progress_callback, PipelineStage.RENDER, "running", "Rendering report.")
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
            if request.require_pdf:
                write_diagnostics(
                    run.run_dir / "diagnostics.json",
                    Diagnostics(
                        error_type="PdfExportError",
                        exit_code=1,
                        stage=PipelineStage.RENDER.value,
                        video_id=ref.bvid,
                        part_index=ref.part_index,
                        duration_check=media["duration_check"],
                        transcript_check=transcript["transcript_check"],
                        artifact_paths=render_artifacts,
                        sanitized_message=sanitized_message,
                        warnings=["pdf_failed"],
                    ),
                )
                _progress(progress_callback, PipelineStage.RENDER, "failed", sanitized_message)
                raise
            render_warnings.append("pdf_failed")

    if transcript["transcript_check"]["status"] == "transcript_incomplete":
        render_warnings.append("transcript_incomplete")

    write_diagnostics(
        run.run_dir / "diagnostics.json",
        Diagnostics(
            error_type=None,
            exit_code=0,
            stage=PipelineStage.RENDER.value,
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=media["duration_check"],
            transcript_check=transcript["transcript_check"],
            artifact_paths=render_artifacts,
            sanitized_message="Report rendering completed.",
            warnings=render_warnings,
        ),
    )
    _progress(progress_callback, PipelineStage.RENDER, "done", "Render complete.")
    return PipelineResult(
        run_key=_display_run_path(run),
        run_dir=run.run_dir,
        diagnostics_path=run.run_dir / "diagnostics.json",
        artifact_paths=render_artifacts,
        warnings=render_warnings,
    )


def _progress(
    progress_callback: ProgressCallback,
    stage: PipelineStage,
    status: str,
    message: str,
) -> None:
    progress_callback(stage.value, status, redact_text(message))


def _write_chunking_failure_diagnostics(
    run: RunPaths,
    ref: Any,
    media: dict[str, Any],
    transcript: dict[str, Any],
    *,
    sanitized_message: str,
    warnings: list[str],
) -> None:
    write_diagnostics(
        run.run_dir / "diagnostics.json",
        Diagnostics(
            error_type="ChunkingError",
            exit_code=1,
            stage=PipelineStage.CHUNKING.value,
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
    formats = {item.strip().lower() for item in raw_format.split(",") if item.strip()}
    if not formats:
        raise ValueError("--format must include html, pdf, or html,pdf.")
    unsupported = formats - {"html", "pdf"}
    if unsupported:
        raise ValueError("Unsupported --format value: " + ", ".join(sorted(unsupported)))
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
    raise ValueError("Could not create error diagnostics run; retry later.")


def _display_run_path(run: RunPaths) -> str:
    return f"{run.video_dir.name}/runs/{run.run_id}"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
