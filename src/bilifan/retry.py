from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bilibili import parse_bilibili_url
from .bundle import write_content_bundle
from .diagnostics import (
    Diagnostics,
    redact_text,
    validate_artifact_paths,
    write_diagnostics,
)
from .exports import ExportError, write_notes_markdown
from .renderer import PdfExportError, RenderError, export_report_pdf, render_report_html
from .runs import RUN_OUTPUT_ID_PATTERN
from .summarizer import SummarizationError, summarize_chunks

RETRY_STAGES = {"summarization", "render", "bundle"}
RUN_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}")


@dataclass(frozen=True)
class RetryResult:
    run_key: str
    run_dir: Path
    diagnostics_path: Path
    artifact_paths: list[str]
    warnings: list[str]


class RetryError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


def retry_run(
    run_dir: Path,
    *,
    from_stage: str,
    output_format: str = "html,pdf",
    llm_provider: str = "codex-exec",
    llm_model: str = "gpt-5.5",
    require_pdf: bool = False,
) -> RetryResult:
    stage = from_stage.strip().lower()
    if stage not in RETRY_STAGES:
        raise RetryError("--from must be summarization, render, or bundle.")
    requested_formats = _parse_output_formats(output_format)

    run_dir = run_dir.resolve(strict=False)
    if not run_dir.is_dir():
        raise RetryError(f"Run directory does not exist: {run_dir}")
    run_key = _run_key(run_dir)

    metadata = _read_required_json(run_dir, "metadata.json")
    transcript = _read_required_json(run_dir, "transcript.json")
    ref = _ref_from_metadata(metadata)

    if stage == "summarization":
        chunks = _read_required_json(run_dir, "chunks.json")
        try:
            chapters = summarize_chunks(
                ref=ref,
                metadata=metadata,
                chunks=chunks,
                run_dir=run_dir,
                provider=llm_provider,
                model=llm_model,
                style="学习笔记",
            )
        except SummarizationError as exc:
            _write_failure_diagnostics(
                run_dir,
                stage="summarization",
                error_type="SummarizationError",
                ref=ref,
                transcript=transcript,
                message=str(exc),
            )
            raise RetryError(str(exc)) from exc
        _write_json(run_dir / "chapters.json", chapters)
        return _render_and_bundle(
            run_dir=run_dir,
            run_key=run_key,
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            requested_formats=requested_formats,
            llm_provider=llm_provider,
            llm_model=llm_model,
            require_pdf=require_pdf,
        )

    chapters = _read_required_json(run_dir, "chapters.json")
    if stage == "render":
        return _render_and_bundle(
            run_dir=run_dir,
            run_key=run_key,
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            requested_formats=requested_formats,
            llm_provider=llm_provider,
            llm_model=llm_model,
            require_pdf=require_pdf,
        )

    return _bundle_only(
        run_dir=run_dir,
        run_key=run_key,
        ref=ref,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )


def _render_and_bundle(
    *,
    run_dir: Path,
    run_key: str,
    ref,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    requested_formats: set[str],
    llm_provider: str,
    llm_model: str,
    require_pdf: bool,
) -> RetryResult:
    warnings: list[str] = []

    try:
        write_notes_markdown(
            run_dir=run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            overwrite=True,
        )
    except ExportError:
        warnings.append("notes_export_failed")

    try:
        report_html = render_report_html(
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            run_dir=run_dir,
        )
    except (RenderError, OSError, ValueError) as exc:
        _write_failure_diagnostics(
            run_dir,
            stage="render",
            error_type=exc.__class__.__name__,
            ref=ref,
            transcript=transcript,
            message=str(exc),
        )
        raise RetryError(str(exc)) from exc

    pdf_path: Path | None = None
    if "pdf" in requested_formats or require_pdf:
        try:
            pdf_path = export_report_pdf(html_path=report_html, pdf_path=run_dir / "report.pdf")
        except PdfExportError as exc:
            if require_pdf:
                _write_failure_diagnostics(
                    run_dir,
                    stage="render",
                    error_type="PdfExportError",
                    ref=ref,
                    transcript=transcript,
                    message=str(exc),
                    artifact_paths=_base_artifact_paths(run_dir)
                    + ["chapters.json", "notes.md", report_html.name],
                )
                raise RetryError(str(exc)) from exc
            warnings.append("pdf_failed")

    artifact_paths = _base_artifact_paths(run_dir)
    artifact_paths.extend(["chapters.json", "notes.md", report_html.name])
    if pdf_path is not None:
        artifact_paths.append(pdf_path.name)
    try:
        bundle_path = write_content_bundle(
            run_dir=run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            artifact_paths=artifact_paths,
            platform="bilibili",
            source_id=ref.bvid,
            part_id=f"p{ref.part_index}",
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except Exception as exc:
        _write_failure_diagnostics(
            run_dir,
            stage="bundle",
            error_type=exc.__class__.__name__,
            ref=ref,
            transcript=transcript,
            message=str(exc),
            artifact_paths=artifact_paths,
        )
        raise RetryError(str(exc)) from exc
    artifact_paths = _append_unique(artifact_paths, bundle_path.name)
    _write_success_diagnostics(
        run_dir,
        stage="render",
        ref=ref,
        transcript=transcript,
        artifact_paths=artifact_paths,
        warnings=warnings,
    )
    return RetryResult(
        run_key=run_key,
        run_dir=run_dir,
        diagnostics_path=run_dir / "diagnostics.json",
        artifact_paths=artifact_paths,
        warnings=warnings,
    )


def _bundle_only(
    *,
    run_dir: Path,
    run_key: str,
    ref,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    llm_provider: str,
    llm_model: str,
) -> RetryResult:
    artifact_paths = _existing_artifact_paths(run_dir)
    try:
        bundle_path = write_content_bundle(
            run_dir=run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            artifact_paths=artifact_paths,
            platform="bilibili",
            source_id=ref.bvid,
            part_id=f"p{ref.part_index}",
            llm_provider=llm_provider,
            llm_model=llm_model,
        )
    except Exception as exc:
        _write_failure_diagnostics(
            run_dir,
            stage="bundle",
            error_type=exc.__class__.__name__,
            ref=ref,
            transcript=transcript,
            message=str(exc),
            artifact_paths=artifact_paths,
        )
        raise RetryError(str(exc)) from exc
    artifact_paths = _append_unique(artifact_paths, bundle_path.name)
    _write_success_diagnostics(
        run_dir,
        stage="bundle",
        ref=ref,
        transcript=transcript,
        artifact_paths=artifact_paths,
        warnings=[],
    )
    return RetryResult(
        run_key=run_key,
        run_dir=run_dir,
        diagnostics_path=run_dir / "diagnostics.json",
        artifact_paths=artifact_paths,
        warnings=[],
    )


def _write_success_diagnostics(
    run_dir: Path,
    *,
    stage: str,
    ref,
    transcript: dict[str, Any],
    artifact_paths: list[str],
    warnings: list[str],
) -> None:
    previous_diagnostics = _read_optional_json(run_dir, "diagnostics.json")
    duration_check = previous_diagnostics.get("duration_check")
    if not isinstance(duration_check, dict):
        duration_check = None
    transcript_check = transcript.get("transcript_check")
    if not isinstance(transcript_check, dict):
        previous_transcript_check = previous_diagnostics.get("transcript_check")
        transcript_check = (
            previous_transcript_check
            if isinstance(previous_transcript_check, dict)
            else None
        )

    write_diagnostics(
        run_dir / "diagnostics.json",
        Diagnostics(
            error_type=None,
            exit_code=0,
            stage=stage,
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=duration_check,
            transcript_check=transcript_check,
            artifact_paths=artifact_paths,
            sanitized_message=f"Retry from {stage} completed.",
            warnings=warnings,
        ),
    )


def _write_failure_diagnostics(
    run_dir: Path,
    *,
    stage: str,
    error_type: str,
    ref,
    transcript: dict[str, Any],
    message: str,
    artifact_paths: list[str] | None = None,
) -> None:
    existing_artifacts = artifact_paths if artifact_paths is not None else _existing_artifact_paths(run_dir)
    write_diagnostics(
        run_dir / "diagnostics.json",
        Diagnostics(
            error_type=error_type,
            exit_code=1,
            stage=stage,
            video_id=ref.bvid,
            part_index=ref.part_index,
            duration_check=_duration_check(run_dir),
            transcript_check=_transcript_check(run_dir, transcript),
            artifact_paths=existing_artifacts,
            sanitized_message=message,
            warnings=[f"{stage}_retry_failed"],
        ),
    )


def _existing_artifact_paths(run_dir: Path) -> list[str]:
    paths: list[str] = []
    for relative_path in [
        "diagnostics.json",
        "metadata.json",
        *_cache_audio_paths(run_dir),
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
        "chapters.json",
        "notes.md",
        "report.html",
        "report.pdf",
        "content_bundle.json",
    ]:
        if (run_dir / relative_path).is_file():
            paths.append(relative_path)
    return validate_artifact_paths(paths)


def _base_artifact_paths(run_dir: Path) -> list[str]:
    paths: list[str] = []
    for relative_path in [
        "diagnostics.json",
        "metadata.json",
        *_cache_audio_paths(run_dir),
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
    ]:
        if (run_dir / relative_path).is_file():
            paths.append(relative_path)
    return validate_artifact_paths(paths)


def _duration_check(run_dir: Path) -> dict[str, Any] | None:
    previous_diagnostics = _read_optional_json(run_dir, "diagnostics.json")
    duration_check = previous_diagnostics.get("duration_check")
    return duration_check if isinstance(duration_check, dict) else None


def _transcript_check(
    run_dir: Path,
    transcript: dict[str, Any],
) -> dict[str, Any] | None:
    transcript_check = transcript.get("transcript_check")
    if isinstance(transcript_check, dict):
        return transcript_check
    previous_diagnostics = _read_optional_json(run_dir, "diagnostics.json")
    previous_transcript_check = previous_diagnostics.get("transcript_check")
    return previous_transcript_check if isinstance(previous_transcript_check, dict) else None


def _cache_audio_paths(run_dir: Path) -> list[str]:
    cache_dir = run_dir / ".bilifan" / "cache"
    if not cache_dir.is_dir():
        return []
    return [
        f".bilifan/cache/{path.name}"
        for path in sorted(cache_dir.iterdir())
        if path.is_file()
        and path.suffix.lower() in {".mp3", ".m4a", ".webm", ".aac", ".opus"}
    ]


def _read_required_json(run_dir: Path, file_name: str) -> dict[str, Any]:
    path = run_dir / file_name
    if not path.is_file():
        raise RetryError(f"Cannot retry without {file_name}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetryError(f"Invalid {file_name}.") from exc
    if not isinstance(data, dict):
        raise RetryError(f"Invalid {file_name}.")
    return data


def _read_optional_json(run_dir: Path, file_name: str) -> dict[str, Any]:
    path = run_dir / file_name
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _ref_from_metadata(metadata: dict[str, Any]):
    video_id = metadata.get("video_id")
    part_index = metadata.get("part_index")
    if isinstance(video_id, str) and isinstance(part_index, int):
        return parse_bilibili_url(
            f"https://www.bilibili.com/video/{video_id}?p={part_index}"
        )
    sanitized_url = metadata.get("input_url_sanitized")
    if isinstance(sanitized_url, str) and sanitized_url:
        try:
            return parse_bilibili_url(sanitized_url)
        except ValueError as exc:
            raise RetryError("Cannot retry without valid Bilibili metadata.") from exc
    raise RetryError("Cannot retry without Bilibili video_id and part_index metadata.")


def _run_key(run_dir: Path) -> str:
    if run_dir.parent.name != "runs" or RUN_ID_PATTERN.fullmatch(run_dir.name) is None:
        raise RetryError("Expected run directory shaped like <output_id>/runs/<run_id>.")
    output_id = run_dir.parent.parent.name
    if RUN_OUTPUT_ID_PATTERN.fullmatch(output_id) is None:
        raise RetryError("Expected run directory shaped like <output_id>/runs/<run_id>.")
    return f"{output_id}/runs/{run_dir.name}"


def _parse_output_formats(raw_format: str) -> set[str]:
    formats = {item.strip().lower() for item in raw_format.split(",") if item.strip()}
    if not formats:
        raise RetryError("--format must include html, pdf, or both.")
    invalid = formats - {"html", "pdf"}
    if invalid:
        raise RetryError("--format must include only html and pdf.")
    return formats


def _append_unique(paths: list[str], path: str) -> list[str]:
    return [*paths, path] if path not in paths else list(paths)
