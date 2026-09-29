from __future__ import annotations

import json
import os
import shutil
import subprocess
from .execution import cancellable_run
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
    Path("/Applications/ChatGPT.app/Contents/Resources/codex"),
    Path.home() / ".codex" / "bin" / "codex",
    Path("/opt/homebrew/bin/codex"),
    Path("/usr/local/bin/codex"),
)
CHAPTER_BOUNDARY_TOLERANCE_SECONDS = 2.0
CHAPTER_SEGMENT_ANCHOR_TOLERANCE_SECONDS = 2.0
TIMESTAMP_EPSILON_SECONDS = 0.001
TEXT_PREVIEW_MAX_CHARS = 160


SUMMARY_TEMPLATES: dict[str, str] = {
    "AI 自动判断": "根据视频内容自动选择最适合的组织方式：教程类偏步骤，观点类偏论证，会议/访谈类偏议题和结论，通用知识类偏学习笔记。",
    "学习笔记": "输出面向学习复盘，突出概念、问题、陷阱、步骤和结论。",
    "教程步骤": "按可执行步骤组织，突出前提、操作顺序、检查点、常见错误和完成标准。",
    "观点提炼": "按观点和论据组织，突出核心判断、支撑证据、反方风险和适用边界。",
    "会议纪要": "按议题组织，突出讨论结论、决策、待办、负责人线索和风险。",
}


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


ARTICLE_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["chapters"],
    "additionalProperties": False,
    "properties": {
        "chapters": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "section_index",
                    "summary",
                    "key_points",
                    "quotes",
                    "visual_anchors",
                ],
                "additionalProperties": False,
                "properties": {
                    "section_index": {"type": "integer", "minimum": 1},
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
    "required": ["style", "summary_validation", "chapters"],
    "additionalProperties": False,
    "properties": {
        "style": {"type": "string"},
        "summary_validation": {
            "type": "object",
            "required": ["status", "checks", "warnings"],
            "additionalProperties": False,
            "properties": {
                "status": {"type": "string", "enum": ["passed", "warning"]},
                "checks": {
                    "type": "object",
                    "required": [
                        "required_fields_present",
                        "timestamps_anchored",
                        "chapter_timestamps_within_chunk",
                        "evidence_anchors_present",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "required_fields_present": {"type": "boolean"},
                        "timestamps_anchored": {"type": "boolean"},
                        "chapter_timestamps_within_chunk": {"type": "boolean"},
                        "evidence_anchors_present": {"type": "boolean"},
                    },
                },
                "warnings": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
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
                    "evidence",
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
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": [
                                "segment_start_index",
                                "segment_end_index",
                                "start",
                                "end",
                                "timestamp_url",
                                "text_preview",
                            ],
                            "additionalProperties": False,
                            "properties": {
                                "segment_start_index": {"type": "integer", "minimum": 0},
                                "segment_end_index": {"type": "integer", "minimum": 0},
                                "start": {"type": "number", "minimum": 0},
                                "end": {"type": "number", "minimum": 0},
                                "timestamp_url": {"type": "string", "minLength": 1},
                                "text_preview": {"type": "string"},
                            },
                        },
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
    runner: Runner = cancellable_run,
) -> dict[str, Any]:
    if provider != "codex-exec":
        raise SummarizationError(f"Unsupported LLM provider: {provider}")
    style = validate_summary_style(style)

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
        _normalize_partial_chapter_timestamps(partial, chunk)
        _validate_partial_matches_chunk(partial, chunk)
        partial["chunk_index"] = chunk_index
        _write_json(partial_path, partial)
        partials.append(partial)

    chapters = merge_partial_summaries(
        ref=ref,
        partials=partials,
        style=style,
    )
    _add_evidence_and_validation(chapters, chunks, ref)
    _validate_json(chapters, CHAPTERS_SCHEMA, "chapters")
    return chapters


def build_article_report_prompt(
    *,
    metadata: dict[str, Any],
    article: dict[str, Any],
    style: str,
) -> str:
    style = validate_summary_style(style)
    safe_metadata = {
        "title": _first_text(metadata.get("title")),
        "part_title": _first_text(metadata.get("part_title")),
    }
    payload = {
        "style": style,
        "metadata": safe_metadata,
        "article": {
            "schema_version": article.get("schema_version"),
            "source": _first_text(article.get("source")),
            "cleaning_level": _first_text(article.get("cleaning_level")),
            "sections": _article_prompt_sections(article),
            "warnings": _string_list(article.get("warnings")),
        },
        "output_schema": ARTICLE_REPORT_SCHEMA,
    }
    return (
        "你是 Bilifan 的视频学习报告摘要器。请只根据输入中的清洗后的逐字稿文章"
        "生成章节摘要，不要使用未清洗的原始转写内容，不要编造文章里没有的信息。"
        "输出必须是严格 JSON，且必须匹配 output_schema。\n"
        f"本次输出模板：{style}。模板要求：{SUMMARY_TEMPLATES[style]}\n"
        "metadata 只可作为标题展示上下文，不能作为事实依据；所有观点、事实和引用"
        "必须来自 article.sections.paragraphs 的清洗后正文。\n"
        "chapters 必须通过 section_index 引用输入 article.sections；summary 用白话"
        "概括该 section，key_points 提炼可复习要点，quotes 只能摘自清洗后的逐字稿文章，"
        "visual_anchors 记录画面或操作线索；没有就给空数组。\n"
        f"{json.dumps(payload, ensure_ascii=False, allow_nan=False)}"
    )


def run_codex_article_report(
    *,
    metadata: dict[str, Any],
    article: dict[str, Any],
    run_dir: Path,
    model: str,
    style: str,
    runner: Runner = cancellable_run,
) -> dict[str, Any]:
    prompt = build_article_report_prompt(
        metadata=metadata,
        article=article,
        style=style,
    )
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "article_report.schema.json"
        output_path = tmp_path / "article_report.json"
        _write_json(schema_path, ARTICLE_REPORT_SCHEMA)
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
        report = _read_json(output_path, "codex exec final message")
        _validate_json(report, ARTICLE_REPORT_SCHEMA, "article report")
        return report


def summarize_article_sections(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    article: dict[str, Any],
    run_dir: Path,
    provider: str = "codex-exec",
    model: str = "gpt-5.5",
    style: str = "学习笔记",
    runner: Runner = cancellable_run,
) -> dict[str, Any]:
    if provider != "codex-exec":
        raise SummarizationError(f"Unsupported LLM provider: {provider}")
    style = validate_summary_style(style)
    report = run_codex_article_report(
        metadata=metadata,
        article=article,
        run_dir=run_dir,
        model=model,
        style=style,
        runner=runner,
    )
    chapters = _article_report_to_chapters(
        ref=ref,
        article=article,
        report=report,
        style=style,
    )
    _add_article_summary_validation(chapters)
    _validate_json(chapters, CHAPTERS_SCHEMA, "chapters")
    return chapters


def validate_summary_style(style: str) -> str:
    normalized = _first_text(style).strip() or "学习笔记"
    if normalized not in SUMMARY_TEMPLATES:
        supported = "、".join(SUMMARY_TEMPLATES)
        raise SummarizationError(
            f"Unsupported summary template: {normalized}. Supported: {supported}."
        )
    return normalized


def run_codex_chunk_summary(
    *,
    metadata: dict[str, Any],
    chunk: dict[str, Any],
    run_dir: Path,
    model: str,
    style: str,
    runner: Runner = cancellable_run,
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
    style = validate_summary_style(style)
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
        f"本次输出模板：{style}。模板要求：{SUMMARY_TEMPLATES[style]}\n"
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


def _normalize_partial_chapter_timestamps(
    partial: dict[str, Any],
    chunk: dict[str, Any],
) -> None:
    chunk_start = _float_value(chunk.get("start"))
    chunk_end = _float_value(chunk.get("end"))
    if chunk_start is None or chunk_end is None or chunk_end < chunk_start:
        return
    transcript_segments = _prompt_segments(chunk)

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
        if transcript_segments:
            chapter["start"] = _normalized_segment_anchor(start, transcript_segments)


def _normalized_segment_anchor(
    timestamp: float,
    transcript_segments: list[dict[str, Any]],
) -> float:
    containing_segment = _segment_containing_timestamp(timestamp, transcript_segments)
    if containing_segment is not None:
        if (
            abs(containing_segment["start"] - timestamp)
            <= CHAPTER_SEGMENT_ANCHOR_TOLERANCE_SECONDS
        ):
            return containing_segment["start"]
        return timestamp

    nearest_segment = min(
        transcript_segments,
        key=lambda segment: abs(segment["start"] - timestamp),
    )
    if (
        abs(nearest_segment["start"] - timestamp)
        <= CHAPTER_SEGMENT_ANCHOR_TOLERANCE_SECONDS
    ):
        return nearest_segment["start"]
    return timestamp


def _segment_containing_timestamp(
    timestamp: float,
    transcript_segments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for segment in transcript_segments:
        if (
            segment["start"] - TIMESTAMP_EPSILON_SECONDS
            <= timestamp
            <= segment["end"] + TIMESTAMP_EPSILON_SECONDS
        ):
            return segment
    return None


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
        source_index = _int_value(raw_segment.get("source_index"))
        segment: dict[str, Any] = {"start": start, "end": end, "text": text}
        if source_index is not None and source_index >= 0:
            segment["source_index"] = source_index
        segments.append(segment)
    return segments


def _article_prompt_sections(article: dict[str, Any]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section in _validated_article_sections(article):
        section_index = section["section_index"]
        start, end = _article_section_timestamps(section)
        if section_index is None or start is None or end is None:
            continue
        paragraph_texts = _require_article_section_paragraph_texts(section)
        sections.append(
            {
                "section_index": section_index,
                "title": redact_text(
                    _first_text(section.get("title")).strip(),
                    max_length=None,
                ),
                "start": start,
                "end": end,
                "timestamp_url": _first_text(section.get("timestamp_url")).strip(),
                "source_segment_start_index": _int_value(
                    section.get("source_segment_start_index")
                ),
                "source_segment_end_index": _int_value(
                    section.get("source_segment_end_index")
                ),
                "paragraphs": [{"text": text} for text in paragraph_texts],
                "key_terms": _string_list(section.get("key_terms")),
                "warnings": _string_list(section.get("warnings")),
            }
        )
    if not sections:
        raise SummarizationError("transcript_article.json contains no sections.")
    return sections


def _article_report_to_chapters(
    *,
    ref: BilibiliPartRef,
    article: dict[str, Any],
    report: dict[str, Any],
    style: str,
) -> dict[str, Any]:
    sections_by_index = _article_sections_by_index(article)
    expected_section_indexes = set(sections_by_index)
    chapters: list[dict[str, Any]] = []
    seen_section_indexes: set[int] = set()

    raw_chapters = report.get("chapters")
    if not isinstance(raw_chapters, list) or not raw_chapters:
        raise SummarizationError("article report contained no chapters.")

    for report_chapter in raw_chapters:
        if not isinstance(report_chapter, dict):
            raise SummarizationError("article report chapter was not a JSON object.")
        section_index = _int_value(report_chapter.get("section_index"))
        if section_index is None:
            raise SummarizationError("article report chapter omitted section_index.")
        if section_index in seen_section_indexes:
            raise SummarizationError("article report referenced duplicate section_index.")
        seen_section_indexes.add(section_index)

        section = sections_by_index.get(section_index)
        if section is None:
            raise SummarizationError("article report referenced unknown section_index.")
        start, end = _article_section_timestamps(section)
        if start is None or end is None or end < start:
            raise SummarizationError("transcript article contained invalid section timestamps.")

        timestamp_url = _first_text(section.get("timestamp_url")).strip() or ref.timestamp_url(
            start
        )
        chapters.append(
            {
                "chapter_index": len(chapters) + 1,
                "title": redact_text(
                    _first_text(section.get("title")).strip(),
                    max_length=None,
                ),
                "start": start,
                "end": end,
                "timestamp_url": timestamp_url,
                "summary": redact_text(
                    _first_text(report_chapter.get("summary")).strip(),
                    max_length=None,
                ),
                "key_points": _string_list(report_chapter.get("key_points")),
                "quotes": _string_list(report_chapter.get("quotes")),
                "visual_anchors": _string_list(report_chapter.get("visual_anchors")),
                "evidence": _article_section_evidence(section, ref),
            }
        )

    missing_section_indexes = sorted(expected_section_indexes - seen_section_indexes)
    if missing_section_indexes:
        raise SummarizationError(
            "article report missing article section(s): "
            f"{', '.join(str(index) for index in missing_section_indexes)}"
        )

    return {"style": style, "chapters": chapters}


def _article_sections_by_index(article: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {
        section["section_index"]: section
        for section in _validated_article_sections(article)
    }


def _validated_article_sections(article: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sections = article.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise SummarizationError("transcript_article.json contains no sections.")

    sections: list[dict[str, Any]] = []
    seen_section_indexes: set[int] = set()
    for position, section in enumerate(raw_sections, start=1):
        if not isinstance(section, dict):
            raise SummarizationError(
                f"transcript article section {position} was not a JSON object."
            )
        raw_section_index = section.get("section_index")
        if (
            isinstance(raw_section_index, bool)
            or not isinstance(raw_section_index, int)
            or raw_section_index < 1
        ):
            raise SummarizationError(
                f"transcript article section {position} contained invalid section_index."
            )
        if raw_section_index in seen_section_indexes:
            raise SummarizationError(
                f"transcript article contained duplicate section_index: {raw_section_index}."
            )
        seen_section_indexes.add(raw_section_index)
        _require_article_section_paragraph_texts(section)
        sections.append(section)
    return sections


def _article_section_timestamps(section: dict[str, Any]) -> tuple[float | None, float | None]:
    return _float_value(section.get("start")), _float_value(section.get("end"))


def _article_section_paragraph_texts(section: dict[str, Any]) -> list[str]:
    raw_paragraphs = section.get("paragraphs")
    if not isinstance(raw_paragraphs, list):
        return []
    texts: list[str] = []
    for paragraph in raw_paragraphs:
        if not isinstance(paragraph, dict):
            continue
        text = redact_text(_first_text(paragraph.get("text")).strip(), max_length=None)
        if text:
            texts.append(text)
    return texts


def _require_article_section_paragraph_texts(section: dict[str, Any]) -> list[str]:
    texts = _article_section_paragraph_texts(section)
    if texts:
        return texts
    section_index = _first_text(section.get("section_index")).strip() or "?"
    raise SummarizationError(
        f"transcript article section {section_index} missing article section text."
    )


def _article_section_evidence(
    section: dict[str, Any],
    ref: BilibiliPartRef,
) -> list[dict[str, Any]]:
    start, end = _article_section_timestamps(section)
    segment_start_index = _int_value(section.get("source_segment_start_index"))
    segment_end_index = _int_value(section.get("source_segment_end_index"))
    if (
        start is None
        or end is None
        or end < start
        or segment_start_index is None
        or segment_end_index is None
        or segment_end_index < segment_start_index
    ):
        return []

    timestamp_url = _first_text(section.get("timestamp_url")).strip() or ref.timestamp_url(
        start
    )
    paragraph_texts = _require_article_section_paragraph_texts(section)
    text_preview = _preview_text(paragraph_texts[0])
    return [
        {
            "segment_start_index": segment_start_index,
            "segment_end_index": segment_end_index,
            "start": start,
            "end": end,
            "timestamp_url": timestamp_url,
            "text_preview": text_preview,
        }
    ]


def _add_article_summary_validation(chapters: dict[str, Any]) -> None:
    warnings: list[str] = []
    checks = {
        "required_fields_present": True,
        "timestamps_anchored": True,
        "chapter_timestamps_within_chunk": True,
        "evidence_anchors_present": True,
    }

    raw_chapters = chapters.get("chapters")
    if not isinstance(raw_chapters, list):
        raw_chapters = []

    for chapter in raw_chapters:
        if not isinstance(chapter, dict):
            checks["required_fields_present"] = False
            continue
        if not _chapter_required_fields_present(chapter):
            checks["required_fields_present"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_missing_required_fields")

        start = _float_value(chapter.get("start"))
        end = _float_value(chapter.get("end"))
        if start is None or end is None or end < start:
            checks["required_fields_present"] = False
            checks["chapter_timestamps_within_chunk"] = False
            checks["timestamps_anchored"] = False
            checks["evidence_anchors_present"] = False
            chapter["evidence"] = []
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_invalid_timestamps")
            continue

        evidence = chapter.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            checks["evidence_anchors_present"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_missing_evidence")
            continue
        for item in evidence:
            if not isinstance(item, dict) or not _article_evidence_required_fields_present(item):
                checks["evidence_anchors_present"] = False
                warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_missing_evidence")
                continue
            evidence_start = _float_value(item.get("start"))
            evidence_end = _float_value(item.get("end"))
            if evidence_start is None or evidence_end is None or evidence_end < evidence_start:
                checks["timestamps_anchored"] = False
                checks["evidence_anchors_present"] = False
                warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_invalid_evidence")

    chapters["summary_validation"] = {
        "status": "passed" if all(checks.values()) else "warning",
        "checks": checks,
        "warnings": _unique_strings(warnings),
    }


def _article_evidence_required_fields_present(evidence: dict[str, Any]) -> bool:
    return bool(
        _int_value(evidence.get("segment_start_index")) is not None
        and _int_value(evidence.get("segment_end_index")) is not None
        and _float_value(evidence.get("start")) is not None
        and _float_value(evidence.get("end")) is not None
        and _first_text(evidence.get("timestamp_url")).strip()
        and "text_preview" in evidence
    )


def _add_evidence_and_validation(
    chapters: dict[str, Any],
    chunks: dict[str, Any],
    ref: BilibiliPartRef,
) -> None:
    chunk_items = _chunk_items(chunks)
    segments = _all_chunk_segments(chunk_items)
    warnings: list[str] = []
    checks = {
        "required_fields_present": True,
        "timestamps_anchored": True,
        "chapter_timestamps_within_chunk": True,
        "evidence_anchors_present": True,
    }

    raw_chapters = chapters.get("chapters")
    if not isinstance(raw_chapters, list):
        raw_chapters = []

    for chapter in raw_chapters:
        if not isinstance(chapter, dict):
            checks["required_fields_present"] = False
            continue
        if not _chapter_required_fields_present(chapter):
            checks["required_fields_present"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_missing_required_fields")

        start = _float_value(chapter.get("start"))
        end = _float_value(chapter.get("end"))
        if start is None or end is None or end < start:
            checks["required_fields_present"] = False
            checks["chapter_timestamps_within_chunk"] = False
            checks["timestamps_anchored"] = False
            checks["evidence_anchors_present"] = False
            chapter["evidence"] = []
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_invalid_timestamps")
            continue

        if not _chapter_within_any_chunk(start, end, chunk_items):
            checks["chapter_timestamps_within_chunk"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_outside_chunk")
        if not _timestamp_in_segments(start, segments):
            checks["timestamps_anchored"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_start_unanchored")

        evidence = _evidence_for_chapter(start, end, segments, ref)
        chapter["evidence"] = evidence
        if not evidence:
            checks["evidence_anchors_present"] = False
            warnings.append(f"chapter_{chapter.get('chapter_index', '?')}_missing_evidence")

    chapters["summary_validation"] = {
        "status": "passed" if all(checks.values()) else "warning",
        "checks": checks,
        "warnings": _unique_strings(warnings),
    }


def _all_chunk_segments(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    seen: set[tuple[int, float, float, str]] = set()
    for chunk in chunks:
        for segment in _prompt_segments(chunk):
            source_index = _int_value(segment.get("source_index"))
            if source_index is None:
                source_index = len(segments)
            normalized = {
                "source_index": source_index,
                "start": segment["start"],
                "end": segment["end"],
                "text": segment["text"],
            }
            key = (
                normalized["source_index"],
                normalized["start"],
                normalized["end"],
                normalized["text"],
            )
            if key in seen:
                continue
            seen.add(key)
            segments.append(normalized)
    return sorted(segments, key=lambda item: (item["start"], item["end"], item["source_index"]))


def _chapter_required_fields_present(chapter: dict[str, Any]) -> bool:
    return bool(
        _first_text(chapter.get("title")).strip()
        and _first_text(chapter.get("summary")).strip()
        and _first_text(chapter.get("timestamp_url")).strip()
        and isinstance(chapter.get("key_points"), list)
        and isinstance(chapter.get("quotes"), list)
        and isinstance(chapter.get("visual_anchors"), list)
    )


def _chapter_within_any_chunk(
    start: float,
    end: float,
    chunks: list[dict[str, Any]],
) -> bool:
    for chunk in chunks:
        chunk_start = _float_value(chunk.get("start"))
        chunk_end = _float_value(chunk.get("end"))
        if chunk_start is None or chunk_end is None:
            continue
        if (
            chunk_start - TIMESTAMP_EPSILON_SECONDS
            <= start
            <= end
            <= chunk_end + TIMESTAMP_EPSILON_SECONDS
        ):
            return True
    return False


def _evidence_for_chapter(
    start: float,
    end: float,
    segments: list[dict[str, Any]],
    ref: BilibiliPartRef,
) -> list[dict[str, Any]]:
    overlapping = [
        segment
        for segment in segments
        if segment["start"] < end + TIMESTAMP_EPSILON_SECONDS
        and segment["end"] > start - TIMESTAMP_EPSILON_SECONDS
    ]
    if not overlapping and segments:
        containing = _segment_containing_timestamp(start, segments)
        overlapping = [containing] if containing is not None else []
    if not overlapping:
        return []

    evidence_start = min(segment["start"] for segment in overlapping)
    evidence_end = max(segment["end"] for segment in overlapping)
    text_preview = _preview_text(" ".join(segment["text"] for segment in overlapping))
    return [
        {
            "segment_start_index": min(segment["source_index"] for segment in overlapping),
            "segment_end_index": max(segment["source_index"] for segment in overlapping),
            "start": evidence_start,
            "end": evidence_end,
            "timestamp_url": ref.timestamp_url(evidence_start),
            "text_preview": text_preview,
        }
    ]


def _preview_text(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= TEXT_PREVIEW_MAX_CHARS:
        return normalized
    return normalized[: TEXT_PREVIEW_MAX_CHARS - 1].rstrip() + "…"


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique


def _timestamp_in_segments(
    timestamp: float,
    transcript_segments: list[dict[str, Any]],
) -> bool:
    return _segment_containing_timestamp(timestamp, transcript_segments) is not None


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
