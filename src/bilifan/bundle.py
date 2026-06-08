from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .diagnostics import redact_text, validate_artifact_paths

BUNDLE_SCHEMA_VERSION = 1


class BundleError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


def build_content_bundle(
    *,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    artifact_paths: list[str],
    platform: str,
    source_id: str,
    part_id: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    return _sanitize_json_value(
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "bundle_id": f"{platform}:{source_id}:{part_id}",
            "source": {
                "platform": platform,
                "id": source_id,
                "part_id": part_id,
                "canonical_url": _nullable_text(metadata.get("input_url_sanitized")),
                "title": _first_text(metadata.get("title"), metadata.get("part_title")),
                "author": _nullable_text(metadata.get("owner_name"), metadata.get("uploader")),
                "published_at": _nullable_text(
                    metadata.get("published_at"),
                    metadata.get("upload_date"),
                ),
                "duration_seconds": _float_or_none(metadata.get("duration")),
                "language": _first_text(transcript.get("language")) or "unknown",
            },
            "artifacts": _artifact_map(artifact_paths),
            "summary": {
                "style": _first_text(chapters.get("style")) or "学习笔记",
                "chapters": _chapter_items(chapters),
            },
            "transcript": {
                "source": _nullable_text(transcript.get("source")),
                "language": _nullable_text(transcript.get("language")),
                "segments": _segment_items(transcript),
            },
            "provenance": {
                "bilifan_version": _nullable_text(metadata.get("bilifan_version")),
                "generated_at": _nullable_text(metadata.get("generated_at")),
                "llm_provider": _nullable_text(
                    llm_provider,
                    chapters.get("llm_provider"),
                    metadata.get("llm_provider"),
                ),
                "llm_model": _nullable_text(
                    llm_model,
                    chapters.get("llm_model"),
                    metadata.get("llm_model"),
                ),
                "transcript_source": _nullable_text(transcript.get("source")),
                "metadata_source": _nullable_text(metadata.get("metadata_source")),
            },
        }
    )


def write_content_bundle(
    *,
    run_dir: Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    artifact_paths: list[str],
    platform: str,
    source_id: str,
    part_id: str,
    llm_provider: str | None = None,
    llm_model: str | None = None,
) -> Path:
    bundle = build_content_bundle(
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        artifact_paths=artifact_paths,
        platform=platform,
        source_id=source_id,
        part_id=part_id,
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    path = run_dir / "content_bundle.json"
    path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _artifact_map(artifact_paths: list[str]) -> dict[str, Any]:
    try:
        validated_paths = validate_artifact_paths(
            _append_unique(artifact_paths, "content_bundle.json")
        )
    except ValueError as exc:
        raise BundleError("Bundle artifact paths must be relative to the run directory.") from exc

    artifacts: dict[str, Any] = {"all": validated_paths}
    known_names = {
        "report.html": "report_html",
        "report.pdf": "report_pdf",
        "notes.md": "notes_markdown",
        "transcript.txt": "transcript_text",
        "transcript.srt": "transcript_srt",
        "metadata.json": "metadata_json",
        "transcript.json": "transcript_json",
        "chunks.json": "chunks_json",
        "chapters.json": "chapters_json",
        "diagnostics.json": "diagnostics_json",
        "content_bundle.json": "content_bundle_json",
    }
    for artifact_path in validated_paths:
        key = known_names.get(artifact_path)
        if key is not None:
            artifacts[key] = artifact_path
    return artifacts


def _append_unique(paths: list[str], path: str) -> list[str]:
    return [*paths, path] if path not in paths else list(paths)


def _chapter_items(chapters: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chapters = chapters.get("chapters")
    if not isinstance(raw_chapters, list):
        return []

    chapter_items: list[dict[str, Any]] = []
    for raw_chapter in raw_chapters:
        if isinstance(raw_chapter, dict):
            chapter_items.append(
                {
                    "chapter_index": raw_chapter.get("chapter_index"),
                    "title": _nullable_text(raw_chapter.get("title")),
                    "start": _float_or_none(raw_chapter.get("start")),
                    "end": _float_or_none(raw_chapter.get("end")),
                    "timestamp_url": _nullable_text(raw_chapter.get("timestamp_url")),
                    "summary": _nullable_text(raw_chapter.get("summary")),
                    "key_points": _text_list(raw_chapter.get("key_points")),
                    "quotes": _text_list(raw_chapter.get("quotes")),
                    "visual_anchors": _text_list(raw_chapter.get("visual_anchors")),
                }
            )
    return chapter_items


def _segment_items(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = transcript.get("segments")
    if not isinstance(raw_segments, list):
        return []

    segment_items: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if isinstance(raw_segment, dict):
            segment_items.append(
                {
                    "start": _float_or_none(raw_segment.get("start")),
                    "end": _float_or_none(raw_segment.get("end")),
                    "text": _nullable_text(raw_segment.get("text")),
                }
            )
    return segment_items


def _first_text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _nullable_text(*values: object) -> str | None:
    value = _first_text(*values)
    return value or None


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (_first_text(raw_item) for raw_item in value) if item]


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _sanitize_json_value(value: object) -> Any:
    if isinstance(value, str):
        return redact_text(value, max_length=None)
    if isinstance(value, dict):
        return {
            redact_text(str(key), max_length=None): _sanitize_json_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list | tuple):
        return [_sanitize_json_value(item) for item in value]
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return redact_text(str(value), max_length=None)
