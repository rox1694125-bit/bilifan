from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from .bilibili import BilibiliPartRef
from .diagnostics import redact_text


Runner = Callable[..., subprocess.CompletedProcess[str]]
CODEX_EXEC_TIMEOUT_SECONDS = 60 * 60
CODEX_EXEC_ENV_VAR = "BILIFAN_CODEX_BIN"
CODEX_EXEC_CANDIDATES = (
    Path("/Applications/Codex.app/Contents/Resources/codex"),
    Path.home() / ".codex" / "bin" / "codex",
    Path("/opt/homebrew/bin/codex"),
    Path("/usr/local/bin/codex"),
)
CHAPTER_BOUNDARY_TOLERANCE_SECONDS = 2.0


CHUNK_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["chunk_index", "chapters"],
    "additionalProperties": False,
    "properties": {
        "chunk_index": {"type": "integer", "minimum": 1},
        "chapters": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "title",
                    "start",
                    "end",
                    "summary",
                    "key_points",
                    "quotes",
                    "visual_anchors",
                ],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                    "start": {"type": "number", "minimum": 0},
                    "end": {"type": "number", "minimum": 0},
                    "summary": {"type": "string", "minLength": 1},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "quotes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "visual_anchors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


CHAPTERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["style", "chapters"],
    "additionalProperties": False,
    "properties": {
        "style": {"type": "string"},
        "chapters": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "chapter_index",
                    "title",
                    "start",
                    "end",
                    "timestamp_url",
                    "summary",
                    "key_points",
                    "quotes",
                    "visual_anchors",
                ],
                "additionalProperties": False,
                "properties": {
                    "chapter_index": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1},
                    "start": {"type": "number", "minimum": 0},
                    "end": {"type": "number", "minimum": 0},
                    "timestamp_url": {"type": "string", "minLength": 1},
                    "summary": {"type": "string", "minLength": 1},
                    "key_points": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "quotes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "visual_anchors": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
    },
}


class SummarizationError(RuntimeError):
    """Raised when LLM summarization fails or returns invalid JSON."""

    def __init__(self, message: str) -> None:
        self.sanitized_message = redact_text(message)
        super().__init__(self.sanitized_message)


def summarize_chunks(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    chunks: dict[str, Any],
    run_dir: Path,
    provider: str = "codex-exec",
    model: str = "gpt-5.5",
    style: str = "学习笔记",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if provider != "codex-exec":
        raise SummarizationError(f"Unsupported LLM provider: {provider}")

    partial_dir = run_dir / "partial_summaries"
    partial_dir.mkdir(parents=True, exist_ok=True)
    partials: list[dict[str, Any]] = []
    for chunk in _chunk_items(chunks):
        chunk_index = _chunk_index(chunk)
        partial = run_codex_chunk_summary(
            metadata=metadata,
            chunk=chunk,
            run_dir=run_dir,
            model=model,
            style=style,
            runner=runner,
        )
        partial_path = partial_dir / f"chunk_{chunk_index:03d}.json"
        _write_json(partial_path, partial)
        _validate_json(partial, CHUNK_SUMMARY_SCHEMA, "chunk summary")
        _normalize_partial_chunk_boundaries(partial, chunk)
        _validate_partial_matches_chunk(partial, chunk)
        partial["chunk_index"] = chunk_index
        _write_json(partial_path, partial)
        partials.append(partial)

    chapters = merge_partial_summaries(
        ref=ref,
        partials=partials,
        style=style,
    )
    _validate_json(chapters, CHAPTERS_SCHEMA, "chapters")
    return chapters


def run_codex_chunk_summary(
    *,
    metadata: dict[str, Any],
    chunk: dict[str, Any],
    run_dir: Path,
    model: str,
    style: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    prompt = build_chunk_prompt(metadata=metadata, chunk=chunk, style=style)
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "chunk_summary.schema.json"
        output_path = tmp_path / "chunk_summary.json"
        _write_json(schema_path, CHUNK_SUMMARY_SCHEMA)
        cmd = [
            resolve_codex_executable(),
            "exec",
            "--ephemeral",
            "--json",
            "--skip-git-repo-check",
            "--model",
            model,
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        try:
            result = runner(
                cmd,
                input=prompt,
                check=False,
                capture_output=True,
                text=True,
                timeout=CODEX_EXEC_TIMEOUT_SECONDS,
                cwd=run_dir,
            )
        except subprocess.TimeoutExpired as exc:
            raise SummarizationError(
                f"codex exec timed out after {CODEX_EXEC_TIMEOUT_SECONDS} seconds."
            ) from exc
        except OSError as exc:
            raise SummarizationError(f"codex exec failed to start: {exc}") from exc

        if result.returncode != 0:
            detail = result.stderr or result.stdout or "codex exec returned no output."
            raise SummarizationError(
                f"codex exec failed with exit code {result.returncode}: {detail}"
            )
        if not output_path.is_file():
            raise SummarizationError("codex exec did not write a final JSON message.")
        return _read_json(output_path, "codex exec final message")


def resolve_codex_executable() -> str:
    configured = os.environ.get(CODEX_EXEC_ENV_VAR)
    if configured:
        configured_path = Path(configured).expanduser()
        if _is_executable_file(configured_path):
            return str(configured_path)
        raise SummarizationError(
            f"{CODEX_EXEC_ENV_VAR} points to a missing or non-executable Codex CLI: "
            f"{configured_path}"
        )

    found = shutil.which("codex")
    if found:
        return found

    for candidate in CODEX_EXEC_CANDIDATES:
        if _is_executable_file(candidate.expanduser()):
            return str(candidate)

    raise SummarizationError(
        "Codex CLI executable not found. Start Bilifan from a shell where `codex` "
        "works, install Codex CLI, or set BILIFAN_CODEX_BIN=/path/to/codex."
    )


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def build_chunk_prompt(
    *,
    metadata: dict[str, Any],
    chunk: dict[str, Any],
    style: str,
) -> str:
    safe_metadata = {
        "title": _first_text(metadata.get("title")),
        "part_title": _first_text(metadata.get("part_title")),
        "owner_name": _first_text(metadata.get("owner_name")),
        "description": _first_text(metadata.get("description")),
        "tags": metadata.get("tags") if isinstance(metadata.get("tags"), list) else [],
        "duration": metadata.get("duration"),
    }
    payload = {
        "style": style,
        "metadata": safe_metadata,
        "chunk": {
            "chunk_index": chunk["chunk_index"],
            "start": chunk["start"],
            "end": chunk["end"],
            "transcript_segments": _prompt_segments(chunk),
            "text": chunk["text"],
        },
        "output_schema": CHUNK_SUMMARY_SCHEMA,
    }
    return (
        "你是 Bilifan 的视频学习笔记生成器。请只根据输入 transcript 内容总结，"
        "不要编造视频里没有的信息。输出必须是严格 JSON，且必须匹配 schema。\n"
        "章节按视频自然结构组织，不要机械套模板。每章用白话短句提炼问题、陷阱、"
        "步骤和结论。每章 start/end 必须落在输入 transcript_segments 的真实时间范围内，"
        "优先使用某个 segment 的 start 作为章节 start，保证能回跳到视频。quotes 只放 "
        "transcript 中真实出现的短句，visual_anchors 记录画面或操作线索；没有就给空数组。\n"
        f"{json.dumps(payload, ensure_ascii=False, allow_nan=False)}"
    )


def merge_partial_summaries(
    *,
    ref: BilibiliPartRef,
    partials: list[dict[str, Any]],
    style: str,
) -> dict[str, Any]:
    chapters: list[dict[str, Any]] = []
    for partial in sorted(partials, key=lambda item: int(item["chunk_index"])):
        for chapter in partial.get("chapters", []):
            normalized = _normalized_chapter(ref, len(chapters) + 1, chapter)
            chapters.append(normalized)
    return {"style": style, "chapters": chapters}


def _normalized_chapter(
    ref: BilibiliPartRef,
    chapter_index: int,
    chapter: dict[str, Any],
) -> dict[str, Any]:
    start = _float_value(chapter.get("start"))
    end = _float_value(chapter.get("end"))
    if start is None or end is None or end < start:
        raise SummarizationError("chunk summary contained invalid chapter timestamps.")
    return {
        "chapter_index": chapter_index,
        "title": redact_text(_first_text(chapter.get("title")).strip(), max_length=None),
        "start": start,
        "end": end,
        "timestamp_url": ref.timestamp_url(start),
        "summary": redact_text(
            _first_text(chapter.get("summary")).strip(),
            max_length=None,
        ),
        "key_points": _string_list(chapter.get("key_points")),
        "quotes": _string_list(chapter.get("quotes")),
        "visual_anchors": _string_list(chapter.get("visual_anchors")),
    }


def _chunk_items(chunks: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chunks = chunks.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise SummarizationError("chunks.json contains no chunks.")
    return [chunk for chunk in raw_chunks if isinstance(chunk, dict)]


def _chunk_index(chunk: dict[str, Any]) -> int:
    chunk_index = _int_value(chunk.get("chunk_index"))
    if chunk_index is None or chunk_index < 1:
        raise SummarizationError("chunks.json contained invalid chunk_index.")
    return chunk_index


def _normalize_partial_chunk_boundaries(
    partial: dict[str, Any],
    chunk: dict[str, Any],
) -> None:
    chunk_start = _float_value(chunk.get("start"))
    chunk_end = _float_value(chunk.get("end"))
    if chunk_start is None or chunk_end is None or chunk_end < chunk_start:
        return

    for chapter in partial.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        start = _float_value(chapter.get("start"))
        end = _float_value(chapter.get("end"))
        if start is None or end is None:
            continue
        if start < chunk_start and chunk_start - start <= CHAPTER_BOUNDARY_TOLERANCE_SECONDS:
            chapter["start"] = chunk_start
            start = chunk_start
        if end > chunk_end and end - chunk_end <= CHAPTER_BOUNDARY_TOLERANCE_SECONDS:
            chapter["end"] = chunk_end


def _validate_partial_matches_chunk(
    partial: dict[str, Any],
    chunk: dict[str, Any],
) -> None:
    expected_chunk_index = _int_value(chunk.get("chunk_index"))
    actual_chunk_index = _int_value(partial.get("chunk_index"))
    if expected_chunk_index is None or actual_chunk_index != expected_chunk_index:
        raise SummarizationError("chunk summary returned mismatched chunk_index.")

    chunk_start = _float_value(chunk.get("start"))
    chunk_end = _float_value(chunk.get("end"))
    if chunk_start is None or chunk_end is None or chunk_end < chunk_start:
        raise SummarizationError("chunks.json contained invalid chunk timestamps.")

    transcript_segments = _prompt_segments(chunk)
    for chapter in partial.get("chapters", []):
        if not isinstance(chapter, dict):
            continue
        start = _float_value(chapter.get("start"))
        end = _float_value(chapter.get("end"))
        if (
            start is None
            or end is None
            or end < start
            or start < chunk_start
            or end > chunk_end
        ):
            raise SummarizationError(
                "chunk summary contained chapter timestamps outside the input chunk."
            )
        if transcript_segments and not _timestamp_in_segments(start, transcript_segments):
            raise SummarizationError(
                "chunk summary chapter start was not anchored to a transcript segment."
            )


def _prompt_segments(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = chunk.get("segments")
    if not isinstance(raw_segments, list):
        return []

    segments: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        start = _float_value(raw_segment.get("start"))
        end = _float_value(raw_segment.get("end"))
        text = redact_text(_first_text(raw_segment.get("text")).strip(), max_length=None)
        if start is None or end is None or end <= start or not text:
            continue
        segments.append({"start": start, "end": end, "text": text})
    return segments


def _timestamp_in_segments(
    timestamp: float,
    transcript_segments: list[dict[str, Any]],
) -> bool:
    return any(
        segment["start"] <= timestamp <= segment["end"]
        for segment in transcript_segments
    )


def _validate_json(payload: dict[str, Any], schema: dict[str, Any], label: str) -> None:
    try:
        validate(instance=payload, schema=schema)
    except ValidationError as exc:
        raise SummarizationError(f"Invalid {label} JSON: {exc.message}") from exc


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SummarizationError(f"{label} was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise SummarizationError(f"{label} was not a JSON object.")
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        redact_text(_first_text(item).strip(), max_length=None)
        for item in value
        if _first_text(item).strip()
    ]


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return ""
