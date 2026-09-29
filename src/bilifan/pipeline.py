from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .article import ArticleError, generate_transcript_article
from .bilibili import BilibiliPartRef
from .bundle import write_content_bundle
from .chunking import (
    ChunkingError,
    LongVideoConfirmationRequired,
    LongVideoLimitExceeded,
    build_chunks,
    estimate_chunk_plan,
    validate_video_duration,
)
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .media import MediaDownloadError, download_current_part_audio, publish_audio_artifact
from .metadata import MetadataIngestError, fetch_current_part_metadata
from .renderer import PdfExportError, render_report_html
from .renderer import export_html_pdf, render_transcript_html
from .runs import RunPaths, create_error_run, create_run
from .sources import SourceAdapterError, SourceOptions, resolve_source_adapter
from .sources.bilibili import BilibiliAdapter
from .summarizer import SummarizationError, summarize_article_sections
from .transcript import TranscriptError, build_transcript
from .visuals import enrich_chapters_with_visuals, visual_artifact_paths


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
    summary_template: str = "学习笔记"
    with_frames: bool = False
    with_diagrams: bool = False
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
    long_video_confirmed = _check_metadata_duration(request, metadata, run, ref, progress_callback)
    _progress(
        progress_callback,
        PipelineStage.METADATA,
        "done",
        _metadata_done_message(metadata),
    )

    media = _metadata_media(metadata)
    transcript: dict[str, Any] | None = None
    if _requires_audio_before_transcript(request):
        media = _download_audio_or_fail(
            adapter,
            source_ref,
            ref,
            metadata,
            run,
            source_options,
            progress_callback,
        )

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
        if request.transcriber == "auto" and not request.force_whisper and not _has_audio(media):
            media = _download_audio_or_fail(
                adapter,
                source_ref,
                ref,
                metadata,
                run,
                source_options,
                progress_callback,
            )
            _progress(
                progress_callback,
                PipelineStage.TRANSCRIPT,
                "running",
                "Building transcript with Whisper.",
            )
            try:
                transcript = build_transcript(
                    metadata,
                    media,
                    run.run_dir,
                    force_whisper=request.force_whisper,
                    language=request.language,
                    transcriber=request.transcriber,
                )
            except TranscriptError as retry_exc:
                _raise_transcript_failure(
                    retry_exc,
                    run=run,
                    ref=ref,
                    media=media,
                    progress_callback=progress_callback,
                )
        else:
            _raise_transcript_failure(
                exc,
                run=run,
                ref=ref,
                media=media,
                progress_callback=progress_callback,
            )
    assert transcript is not None

    _write_json(run.run_dir / "transcript.json", transcript)
    export_warnings = _transcript_pipeline_warnings(transcript)
    _progress(progress_callback, PipelineStage.TRANSCRIPT, "done", "Transcript saved.")

    _progress(progress_callback, PipelineStage.CHUNKING, "running", "Building chunks.")
    try:
        chunks = build_chunks(
            transcript,
            media,
            allow_long_video=request.allow_long_video,
            long_video_confirmed=long_video_confirmed,
        )
    except LongVideoConfirmationRequired as exc:
        if request.confirm_long_video is None or not request.confirm_long_video(exc.sanitized_message):
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=exc.sanitized_message,
                warnings=[*export_warnings, "chunking_confirmation_required"],
                transcript_export_artifacts=[],
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
                    [],
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
                [],
            )
            _write_chunking_failure_diagnostics(
                run,
                ref,
                media,
                transcript,
                sanitized_message=sanitized_message,
                warnings=[*export_warnings, "chunking_failed"],
                transcript_export_artifacts=[],
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
        artifact_paths = _chunking_failure_artifacts(media, [])
        _write_chunking_failure_diagnostics(
            run,
            ref,
            media,
            transcript,
            sanitized_message=sanitized_message,
            warnings=[*export_warnings, "chunking_failed"],
            transcript_export_artifacts=[],
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
        "Generating transcript article.",
    )
    try:
        article = generate_transcript_article(
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chunks=chunks,
            run_dir=run.run_dir,
            provider=request.llm_provider,
            model=request.llm_model,
        )
        chapters = summarize_article_sections(
            ref=ref,
            metadata=metadata,
            article=article,
            run_dir=run.run_dir,
            provider=request.llm_provider,
            model=request.llm_model,
            style=request.summary_template,
        )
    except (ArticleError, SummarizationError) as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = [
            "diagnostics.json",
            "metadata.json",
            *_media_artifact_paths(media),
            "transcript.json",
            "chunks.json",
            *_existing_named_artifacts(run.run_dir, ["transcript_article.json"]),
            *_partial_summary_artifacts(run.run_dir),
        ]
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type=exc.__class__.__name__,
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
    visual_warnings = enrich_chapters_with_visuals(
        ref=ref,
        chapters=chapters,
        media=media,
        run_dir=run.run_dir,
        with_frames=request.with_frames,
        with_diagrams=request.with_diagrams,
    )
    export_warnings.extend(visual_warnings)
    visual_artifacts = visual_artifact_paths(chapters)
    _write_json(run.run_dir / "chapters.json", chapters)
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
        *_media_artifact_paths(media),
        "transcript.json",
        "chunks.json",
        "transcript_article.json",
        "chapters.json",
        *visual_artifacts,
    ]
    _progress(progress_callback, PipelineStage.RENDER, "running", "Rendering outputs.")
    render_artifacts = list(render_base_artifacts)
    try:
        transcript_html = render_transcript_html(
            ref=ref,
            metadata=metadata,
            article=article,
            run_dir=run.run_dir,
        )
        render_artifacts.append(transcript_html.name)
        report_html = render_report_html(
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            run_dir=run.run_dir,
        )
        render_artifacts.append(report_html.name)
    except Exception as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = list(render_artifacts)
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
    if should_export_pdf:
        for html_path, pdf_name in (
            (transcript_html, "transcript.pdf"),
            (report_html, "report.pdf"),
        ):
            try:
                pdf_path = export_html_pdf(
                    html_path=html_path,
                    pdf_path=run.run_dir / pdf_name,
                )
                render_artifacts.append(pdf_path.name)
            except PdfExportError as exc:
                sanitized_message = redact_text(str(exc))
                render_warnings = _append_unique(render_warnings, "pdf_failed")
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
                            warnings=render_warnings,
                        ),
                    )
                    _progress(
                        progress_callback,
                        PipelineStage.RENDER,
                        "failed",
                        sanitized_message,
                    )
                    raise _pipeline_run_error(
                        run,
                        sanitized_message,
                        artifact_paths=artifact_paths,
                        warnings=render_warnings,
                    ) from exc

    if transcript["transcript_check"]["status"] == "transcript_incomplete":
        render_warnings = _append_unique(render_warnings, "transcript_incomplete")

    if _has_audio(media):
        try:
            audio_artifact_path = publish_audio_artifact(run.run_dir, media)
            render_artifacts = [
                audio_artifact_path if path == media["audio_path"] else path
                for path in render_artifacts
            ]
        except MediaDownloadError:
            render_warnings.append("audio_publish_failed")

    try:
        bundle_path = write_content_bundle(
            run_dir=run.run_dir,
            metadata=metadata,
            transcript=transcript,
            transcript_article=article,
            chapters=chapters,
            artifact_paths=render_artifacts,
            platform=adapter.platform,
            source_id=source_ref.source_id,
            part_id=source_ref.part_id,
            llm_provider=request.llm_provider,
            llm_model=request.llm_model,
        )
    except Exception as exc:
        sanitized_message = redact_text(str(exc))
        artifact_paths = list(render_artifacts)
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type=exc.__class__.__name__,
                exit_code=1,
                stage="bundle",
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


def _download_audio_or_fail(
    adapter: Any,
    source_ref: Any,
    ref: Any,
    metadata: dict[str, Any],
    run: RunPaths,
    source_options: SourceOptions,
    progress_callback: ProgressCallback,
) -> dict[str, Any]:
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
    return media


def _raise_transcript_failure(
    exc: TranscriptError,
    *,
    run: RunPaths,
    ref: Any,
    media: dict[str, Any],
    progress_callback: ProgressCallback,
) -> None:
    sanitized_message = redact_text(str(exc))
    artifact_paths = [
        "diagnostics.json",
        "metadata.json",
        *_media_artifact_paths(media),
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


def _check_metadata_duration(
    request: PipelineRequest,
    metadata: dict[str, Any],
    run: RunPaths,
    ref: Any,
    progress_callback: ProgressCallback,
) -> bool:
    confirmed = request.yes_i_understand
    try:
        validate_video_duration(
            metadata.get("duration"),
            allow_long_video=request.allow_long_video,
            long_video_confirmed=confirmed,
        )
    except (LongVideoConfirmationRequired, LongVideoLimitExceeded) as exc:
        if (
            isinstance(exc, LongVideoConfirmationRequired)
            and request.confirm_long_video is not None
            and request.confirm_long_video(exc.sanitized_message)
        ):
            return True
        warnings = [
            "long_video_confirmation_required" if isinstance(exc, LongVideoConfirmationRequired)
            else "long_video_limit_exceeded"
        ]
        artifact_paths = ["metadata.json", "diagnostics.json"]
        write_diagnostics(
            run.run_dir / "diagnostics.json",
            Diagnostics(
                error_type=type(exc).__name__, exit_code=1,
                stage=PipelineStage.METADATA.value, video_id=ref.bvid,
                part_index=ref.part_index,
                duration_check=_metadata_media(metadata)["duration_check"],
                transcript_check=None, artifact_paths=artifact_paths,
                sanitized_message=exc.sanitized_message, warnings=warnings,
            ),
        )
        _progress(progress_callback, PipelineStage.METADATA, "failed", exc.sanitized_message)
        raise _pipeline_run_error(
            run, exc.sanitized_message, artifact_paths=artifact_paths, warnings=warnings,
        ) from exc
    return confirmed


def _metadata_media(metadata: dict[str, Any]) -> dict[str, Any]:
    duration = _metadata_duration(metadata)
    return {
        "audio_path": "",
        "audio_source": "not-downloaded",
        "duration_seconds": duration,
        "duration_check": {
            "status": "metadata_only",
            "metadata_seconds": duration,
            "audio_seconds": None,
            "difference_ratio": None,
            "tolerance_ratio": 0.05,
            "attempts": 0,
        },
    }


def _metadata_duration(metadata: dict[str, Any]) -> int | float | None:
    duration = metadata.get("duration")
    if isinstance(duration, bool) or duration is None:
        return None
    if isinstance(duration, int | float):
        return duration
    if isinstance(duration, str):
        try:
            parsed = float(duration)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _requires_audio_before_transcript(request: PipelineRequest) -> bool:
    return request.force_whisper or request.transcriber == "whisper"


def _has_audio(media: dict[str, Any]) -> bool:
    return isinstance(media.get("audio_path"), str) and bool(media.get("audio_path"))


def _media_artifact_paths(media: dict[str, Any]) -> list[str]:
    return [media["audio_path"]] if _has_audio(media) else []


def _metadata_done_message(metadata: dict[str, Any]) -> str:
    estimate = estimate_chunk_plan(metadata.get("duration"))
    if estimate["mode"] == "single_pass":
        return "Metadata saved."
    min_count = estimate["estimated_chunk_count_min"]
    max_count = estimate["estimated_chunk_count_max"]
    if min_count == max_count:
        chunk_label = str(min_count)
    else:
        chunk_label = f"{min_count}-{max_count}"
    message = f"Metadata saved. Estimated summary chunks: {chunk_label}."
    if estimate["requires_allow_long_video"]:
        return f"{message} Videos over 180 minutes require allow long video."
    if estimate["requires_confirmation"]:
        return f"{message} Videos between 90 and 180 minutes require confirmation."
    return message


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
        *_media_artifact_paths(media),
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


def _existing_named_artifacts(run_dir: Path, names: list[str]) -> list[str]:
    return [name for name in names if (run_dir / name).is_file()]


def _append_unique(items: list[str], item: str) -> list[str]:
    return [*items, item] if item not in items else list(items)


def _transcript_pipeline_warnings(transcript: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    quality_check = transcript.get("transcript_quality_check")
    if isinstance(quality_check, dict):
        status = quality_check.get("status")
        if status in {"low_confidence", "suspect_wrong_route", "unusable"}:
            warnings = _append_unique(warnings, f"transcript_quality_{status}")

    attempts = transcript.get("transcription_attempts")
    if isinstance(attempts, list) and len(attempts) > 1:
        selected_index = next(
            (
                index
                for index, attempt in enumerate(attempts)
                if isinstance(attempt, dict) and attempt.get("selected") is True
            ),
            None,
        )
        if selected_index is not None and selected_index > 0:
            warnings = _append_unique(warnings, "transcript_auto_corrected")

    return warnings


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
