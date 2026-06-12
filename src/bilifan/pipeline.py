from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .bilibili import BilibiliPartRef
from .bundle import write_content_bundle
from .chunking import ChunkingError, LongVideoConfirmationRequired, build_chunks
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .exports import ExportError, write_notes_markdown, write_transcript_exports
from .media import MediaDownloadError, download_current_part_audio, publish_audio_artifact
from .metadata import MetadataIngestError, fetch_current_part_metadata
from .renderer import PdfExportError, export_report_pdf, render_report_html
from .runs import RunPaths, create_error_run, create_run
from .sources import SourceAdapterError, SourceOptions, resolve_source_adapter
from .sources.bilibili import BilibiliAdapter
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
    language: str = "auto"
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


class PipelineRunError(Exception):
    def __init__(
        self,
        message: str,
        *,
        run_key: str,
        diagnostics_path: Path,
        artifact_paths: list[str],
        warnings: list[str],
        exit_code: int = 1,
    ) -> None:
        super().__init__(message)
        self.run_key = run_key
        self.diagnostics_path = diagnostics_path
        self.artifact_paths = artifact_paths
        self.warnings = warnings
        self.exit_code = exit_code


def default_progress(stage: str, status: str, message: str) -> None:
    return None


def validate_output_format(raw_format: str) -> None:
    _parse_output_formats(raw_format)


def validate_language(language: str) -> None:
    if language not in {"auto", "zh", "en"}:
        raise ValueError("--language must be auto, zh, or en.")


def run_summarize_pipeline(
    request: PipelineRequest,
    *,
    progress_callback: ProgressCallback = default_progress,
) -> PipelineResult:
    requested_formats = _parse_output_formats(request.output_format)
    validate_language(request.language)
    should_export_pdf = "pdf" in requested_formats or request.require_pdf

    _progress(progress_callback, PipelineStage.PREFLIGHT, "running", "Validating input.")
    try:
        adapter = resolve_source_adapter(request.url)
        source_ref = adapter.parse_url(request.url)
        ref = _legacy_run_ref(adapter, source_ref)
    except (SourceAdapterError, ValueError) as exc:
        run = _create_error_run_with_retry(request.out)
        sanitized_message = redact_text(str(exc))
        artifact_paths = ["diagnostics.json"]
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
                artifact_paths=artifact_paths,
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
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=["foundation_slice_only"],
            exit_code=2,
        ) from exc

    try:
        run = create_run(request.out, ref, overwrite=request.overwrite)
    except FileExistsError as exc:
        message = "Run directory already exists; use --overwrite or retry later."
        _progress(progress_callback, PipelineStage.PREFLIGHT, "failed", message)
        raise ValueError(message) from exc
    _progress(progress_callback, PipelineStage.PREFLIGHT, "done", "Input accepted.")

    _progress(progress_callback, PipelineStage.METADATA, "running", "Fetching metadata.")
    try:
        source_options = SourceOptions(
            cookies_from_browser=request.cookies_from_browser,
            cookies_file=request.cookies_file,
            language=request.language,
            force_whisper=request.force_whisper,
        )
        metadata = _fetch_source_metadata(
            adapter,
            source_ref,
            ref,
            run.run_dir,
            source_options,
        )
        metadata["platform"] = adapter.platform
    except MetadataIngestError as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = ["diagnostics.json"]
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
                artifact_paths=artifact_paths,
                sanitized_message=sanitized_message,
                warnings=["metadata_failed"],
            ),
        )
        _progress(progress_callback, PipelineStage.METADATA, "failed", sanitized_message)
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=["metadata_failed"],
        ) from exc

    _write_json(run.run_dir / "metadata.json", metadata)
    _progress(progress_callback, PipelineStage.METADATA, "done", "Metadata saved.")

    _progress(progress_callback, PipelineStage.AUDIO, "running", "Downloading audio.")
    try:
        media = _download_source_audio(
            adapter,
            source_ref,
            ref,
            metadata,
            run.run_dir,
            source_options,
        )
    except MediaDownloadError as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = ["diagnostics.json", "metadata.json"]
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
                artifact_paths=artifact_paths,
                sanitized_message=sanitized_message,
                warnings=["media_failed"],
            ),
        )
        _progress(progress_callback, PipelineStage.AUDIO, "failed", sanitized_message)
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=["media_failed"],
        ) from exc
    _progress(progress_callback, PipelineStage.AUDIO, "done", "Audio ready.")

    _progress(progress_callback, PipelineStage.TRANSCRIPT, "running", "Building transcript.")
    try:
        transcript = build_transcript(
            metadata,
            media,
            run.run_dir,
            force_whisper=request.force_whisper,
            language=request.language,
            transcriber=request.transcriber,
        )
    except TranscriptError as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = [
            "diagnostics.json",
            "metadata.json",
            media["audio_path"],
        ]
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
                artifact_paths=artifact_paths,
                sanitized_message=sanitized_message,
                warnings=["transcript_failed"],
            ),
        )
        _progress(progress_callback, PipelineStage.TRANSCRIPT, "failed", sanitized_message)
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=["transcript_failed"],
        ) from exc

    _write_json(run.run_dir / "transcript.json", transcript)
    transcript_export_artifacts: list[str] = []
    export_warnings: list[str] = []
    try:
        transcript_export_artifacts = write_transcript_exports(
            run_dir=run.run_dir,
            metadata=metadata,
            transcript=transcript,
        )
    except ExportError:
        export_warnings.append("transcript_export_failed")
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
                warnings=[*export_warnings, "chunking_confirmation_required"],
                transcript_export_artifacts=transcript_export_artifacts,
            )
            _progress(
                progress_callback,
                PipelineStage.CHUNKING,
                "failed",
                exc.sanitized_message,
            )
            raise _pipeline_run_error(
                run,
                exc.sanitized_message,
                artifact_paths=_chunking_failure_artifacts(
                    media,
                    transcript_export_artifacts,
                ),
                warnings=[*export_warnings, "chunking_confirmation_required"],
            ) from exc
        try:
            chunks = build_chunks(
                transcript,
                media,
                allow_long_video=request.allow_long_video,
                long_video_confirmed=True,
            )
        except ChunkingError as retry_exc:
            sanitized_message = redact_text(str(retry_exc))
            artifact_paths = _chunking_failure_artifacts(
                media,
                transcript_export_artifacts,
            )
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=sanitized_message,
                warnings=[*export_warnings, "chunking_failed"],
                transcript_export_artifacts=transcript_export_artifacts,
            )
            _progress(
                progress_callback,
                PipelineStage.CHUNKING,
                "failed",
                sanitized_message,
            )
            raise _pipeline_run_error(
                run,
                sanitized_message,
                artifact_paths=artifact_paths,
                warnings=[*export_warnings, "chunking_failed"],
            ) from retry_exc
    except ChunkingError as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = _chunking_failure_artifacts(media, transcript_export_artifacts)
        _write_chunking_failure_diagnostics(
            run,
            ref,
            media,
            transcript,
            sanitized_message=sanitized_message,
            warnings=[*export_warnings, "chunking_failed"],
            transcript_export_artifacts=transcript_export_artifacts,
        )
        _progress(progress_callback, PipelineStage.CHUNKING, "failed", sanitized_message)
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=[*export_warnings, "chunking_failed"],
        ) from exc

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
        artifact_paths = [
            "diagnostics.json",
            "metadata.json",
            media["audio_path"],
            "transcript.json",
            *transcript_export_artifacts,
            "chunks.json",
            *_partial_summary_artifacts(run.run_dir),
        ]
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
                artifact_paths=artifact_paths,
                sanitized_message=sanitized_message,
                warnings=[*export_warnings, "summarization_failed"],
            ),
        )
        _progress(
            progress_callback,
            PipelineStage.SUMMARIZATION,
            "failed",
            sanitized_message,
        )
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=[*export_warnings, "summarization_failed"],
        ) from exc
    _write_json(run.run_dir / "chapters.json", chapters)
    notes_artifacts: list[str] = []
    try:
        notes_artifacts = write_notes_markdown(
            run_dir=run.run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
        )
    except ExportError:
        export_warnings.append("notes_export_failed")
    _progress(
        progress_callback,
        PipelineStage.SUMMARIZATION,
        "done",
        "Summaries saved.",
    )

    render_warnings: list[str] = list(export_warnings)
    render_base_artifacts = [
        "diagnostics.json",
        "metadata.json",
        media["audio_path"],
        "transcript.json",
        *transcript_export_artifacts,
        "chunks.json",
        "chapters.json",
        *notes_artifacts,
    ]
    _progress(progress_callback, PipelineStage.RENDER, "running", "Rendering report.")
    try:
        report_html = render_report_html(
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            run_dir=run.run_dir,
        )
    except Exception as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = list(render_base_artifacts)
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type="RenderError",
                exit_code=1,
                stage=PipelineStage.RENDER.value,
                video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=media["duration_check"],
                transcript_check=transcript["transcript_check"],
                artifact_paths=artifact_paths,
                sanitized_message=sanitized_message,
                warnings=render_warnings,
            ),
        )
        _progress(progress_callback, PipelineStage.RENDER, "failed", sanitized_message)
        raise _pipeline_run_error(
            run,
            sanitized_message,
            artifact_paths=artifact_paths,
            warnings=render_warnings,
        ) from exc
    render_artifacts = [*render_base_artifacts, report_html.name]
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
                artifact_paths = list(render_artifacts)
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
                        artifact_paths=artifact_paths,
                        sanitized_message=sanitized_message,
                        warnings=[*render_warnings, "pdf_failed"],
                    ),
                )
                _progress(progress_callback, PipelineStage.RENDER, "failed", sanitized_message)
                raise _pipeline_run_error(
                    run,
                    sanitized_message,
                    artifact_paths=artifact_paths,
                    warnings=[*render_warnings, "pdf_failed"],
                ) from exc
            render_warnings.append("pdf_failed")

    if transcript["transcript_check"]["status"] == "transcript_incomplete":
        render_warnings.append("transcript_incomplete")

    try:
        audio_artifact_path = publish_audio_artifact(run.run_dir, media)
        render_artifacts = [
            audio_artifact_path if path == media["audio_path"] else path
            for path in render_artifacts
        ]
    except MediaDownloadError:
        render_warnings.append("audio_publish_failed")

    bundle_path = write_content_bundle(
        run_dir=run.run_dir,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        artifact_paths=render_artifacts,
        platform=adapter.platform,
        source_id=source_ref.source_id,
        part_id=source_ref.part_id,
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
    )
    render_artifacts.append(bundle_path.name)

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


class _GenericRunRef:
    def __init__(self, source_ref: Any, adapter: Any) -> None:
        self._source_ref = source_ref
        self._adapter = adapter
        self.bvid = source_ref.source_id
        self.part_index = 1
        self.sanitized_url = source_ref.canonical_url

    @property
    def output_id(self) -> str:
        return self._adapter.output_id(self._source_ref)

    def timestamp_url(self, seconds: float) -> str:
        return self._adapter.timestamp_url(self._source_ref, seconds)


def _legacy_run_ref(adapter: Any, source_ref: Any) -> BilibiliPartRef | _GenericRunRef:
    if isinstance(adapter, BilibiliAdapter):
        return adapter.legacy_ref(source_ref)
    return _GenericRunRef(source_ref, adapter)


def _fetch_source_metadata(
    adapter: Any,
    source_ref: Any,
    ref: Any,
    run_dir: Path,
    source_options: SourceOptions,
) -> dict[str, Any]:
    if isinstance(adapter, BilibiliAdapter):
        return fetch_current_part_metadata(
            ref,
            run_dir,
            cookies_from_browser=source_options.cookies_from_browser,
            cookies_file=source_options.cookies_file,
        )
    return adapter.fetch_metadata(source_ref, run_dir, source_options)


def _download_source_audio(
    adapter: Any,
    source_ref: Any,
    ref: Any,
    metadata: dict[str, Any],
    run_dir: Path,
    source_options: SourceOptions,
) -> dict[str, Any]:
    if isinstance(adapter, BilibiliAdapter):
        return download_current_part_audio(
            ref,
            metadata,
            run_dir,
            cookies_from_browser=source_options.cookies_from_browser,
            cookies_file=source_options.cookies_file,
        )
    return adapter.download_audio(source_ref, metadata, run_dir, source_options)


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
    transcript_export_artifacts: list[str],
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
            artifact_paths=_chunking_failure_artifacts(
                media,
                transcript_export_artifacts,
            ),
            sanitized_message=sanitized_message,
            warnings=warnings,
        ),
    )


def _chunking_failure_artifacts(
    media: dict[str, Any],
    transcript_export_artifacts: list[str],
) -> list[str]:
    return [
        "diagnostics.json",
        "metadata.json",
        media["audio_path"],
        "transcript.json",
        *transcript_export_artifacts,
    ]


def _pipeline_run_error(
    run: RunPaths,
    message: str,
    *,
    artifact_paths: list[str],
    warnings: list[str],
    exit_code: int = 1,
) -> PipelineRunError:
    return PipelineRunError(
        message,
        run_key=_display_run_path(run),
        diagnostics_path=run.run_dir / "diagnostics.json",
        artifact_paths=artifact_paths,
        warnings=warnings,
        exit_code=exit_code,
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
