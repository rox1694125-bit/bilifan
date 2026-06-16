from __future__ import annotations

import copy
import json
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate

from .bilibili import BilibiliPartRef
from .diagnostics import redact_text
from .summarizer import CODEX_EXEC_TIMEOUT_SECONDS, resolve_codex_executable


Runner = Callable[..., subprocess.CompletedProcess[str]]
ARTICLE_SCHEMA_VERSION = 1
ARTICLE_ARTIFACT = "transcript_article.json"
ARTICLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "source", "cleaning_level", "sections", "warnings"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": ARTICLE_SCHEMA_VERSION},
        "source": {"type": "string"},
        "cleaning_level": {"type": "string", "enum": ["strong", "light"]},
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": [
                    "section_index",
                    "title",
                    "start",
                    "end",
                    "source_segment_start_index",
                    "source_segment_end_index",
                    "paragraphs",
                    "key_terms",
                    "warnings",
                ],
                "additionalProperties": False,
                "properties": {
                    "section_index": {"type": "integer", "minimum": 1},
                    "title": {"type": "string", "minLength": 1},
                    "start": {"type": "number", "minimum": 0},
                    "end": {"type": "number", "minimum": 0},
                    "timestamp_url": {"type": "string", "minLength": 1},
                    "cleaning_level": {"type": "string", "enum": ["strong", "light"]},
                    "source_segment_start_index": {"type": "integer", "minimum": 0},
                    "source_segment_end_index": {"type": "integer", "minimum": 0},
                    "paragraphs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["text", "emphasis"],
                            "additionalProperties": False,
                            "properties": {
                                "text": {"type": "string", "minLength": 1},
                                "emphasis": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "required": ["text", "kind"],
                                        "additionalProperties": False,
                                        "properties": {
                                            "text": {"type": "string", "minLength": 1},
                                            "kind": {
                                                "type": "string",
                                                "enum": ["strong", "mark", "list"],
                                            },
                                        },
                                    },
                                },
                            },
                        },
                    },
                    "key_terms": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "warnings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
            },
        },
        "warnings": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


class ArticleError(RuntimeError):
    def __init__(self, message: str) -> None:
        self.sanitized_message = redact_text(message)
        super().__init__(self.sanitized_message)


def build_article_prompt(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunk: dict[str, Any],
) -> str:
    source = _first_text(transcript.get("source")).strip()
    cleaning_level = _cleaning_level_for_source(source)
    cleaning_instruction = (
        "强清洗：这是 Whisper 转写，请修正 Whisper 常见的错别字、同音误识别、"
        "专业术语误写、重复口癖和 ASR 重复问题；保持原意，不补充视频外信息。"
        if cleaning_level == "strong"
        else "轻清洗：这是字幕来源，请主要改善标点、断句和分段；少改词、"
        "少做词语替换，避免改变字幕原意。"
    )
    safe_metadata = {
        "title": _first_text(metadata.get("title")),
        "part_title": _first_text(metadata.get("part_title")),
        "owner_name": _first_text(metadata.get("owner_name")),
        "description": _first_text(metadata.get("description")),
        "tags": metadata.get("tags") if isinstance(metadata.get("tags"), list) else [],
        "duration": metadata.get("duration"),
    }
    payload = {
        "video": {
            "bvid": ref.bvid,
            "part_index": ref.part_index,
            "url": ref.sanitized_url,
        },
        "metadata": safe_metadata,
        "transcript": {
            "source": source,
            "language": _first_text(transcript.get("language")),
            "model": _first_text(transcript.get("model")),
            "transcript_check": transcript.get("transcript_check"),
            "cleaning_level": cleaning_level,
        },
        "chunk": {
            "chunk_index": chunk.get("chunk_index"),
            "start": chunk.get("start"),
            "end": chunk.get("end"),
            "segment_start_index": chunk.get("segment_start_index"),
            "segment_end_index": chunk.get("segment_end_index"),
            "transcript_segments": _prompt_segments(chunk),
            "text": _first_text(chunk.get("text")),
        },
        "output_schema": ARTICLE_SCHEMA,
    }
    return (
        "你是 Bilifan 的逐字稿文章生成器。请只根据输入 transcript 内容，把视频逐字稿"
        "整理成可阅读文章，不要编造视频里没有的信息。输出必须是严格 JSON，且必须匹配"
        " output_schema。\n"
        f"本次清洗等级：{cleaning_level}。{cleaning_instruction}\n"
        "sections 必须按输入片段自然分段；每个 section 的 start/end 必须落在 chunk "
        "时间范围内，source_segment_start_index/source_segment_end_index 必须使用输入"
        " transcript_segments 的 source_index。paragraphs 中每段必须有 text 和 emphasis；"
        "emphasis.kind 只能是 strong、mark、list。\n"
        f"{json.dumps(payload, ensure_ascii=False, allow_nan=False)}"
    )


def run_codex_article_generation(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunk: dict[str, Any],
    run_dir: Path,
    model: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    prompt = build_article_prompt(
        ref=ref,
        metadata=metadata,
        transcript=transcript,
        chunk=chunk,
    )
    with tempfile.TemporaryDirectory(dir=run_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        schema_path = tmp_path / "transcript_article.schema.json"
        output_path = tmp_path / "transcript_article.json"
        _write_json(schema_path, ARTICLE_SCHEMA)
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
            raise ArticleError(
                f"codex exec timed out after {CODEX_EXEC_TIMEOUT_SECONDS} seconds."
            ) from exc
        except OSError as exc:
            raise ArticleError(f"codex exec failed to start: {exc}") from exc

        if result.returncode != 0:
            detail = result.stderr or result.stdout or "codex exec returned no output."
            raise ArticleError(
                f"codex exec failed with exit code {result.returncode}: {detail}"
            )
        if not output_path.is_file():
            raise ArticleError("codex exec did not write a final JSON message.")

        article = _read_json(output_path, "codex exec final message")
        return normalize_transcript_article(
            article,
            ref=ref,
            transcript=transcript,
            chunks={"chunks": [chunk]},
        )


def normalize_transcript_article(
    article: dict[str, Any],
    *,
    ref: BilibiliPartRef,
    transcript: dict[str, Any],
    chunks: dict[str, Any],
) -> dict[str, Any]:
    normalized = copy.deepcopy(article)
    if not isinstance(normalized, dict):
        raise ArticleError("transcript article was not a JSON object.")

    source = _first_text(transcript.get("source")).strip()
    cleaning_level = _cleaning_level_for_source(source)
    normalized["source"] = source
    normalized["cleaning_level"] = cleaning_level
    normalized["warnings"] = _string_list(normalized.get("warnings"))

    raw_sections = normalized.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ArticleError("transcript article contained no sections.")

    transcript_segment_count = _transcript_segment_count(transcript)
    covered_source_indices = _chunk_source_indices(chunks)
    sections: list[dict[str, Any]] = []
    for index, raw_section in enumerate(raw_sections, start=1):
        if not isinstance(raw_section, dict):
            raise ArticleError("transcript article section was not an object.")

        start = _nonnegative_float(raw_section.get("start"), "section start")
        end = _nonnegative_float(raw_section.get("end"), "section end")
        if end < start:
            raise ArticleError("transcript article section timestamp range was invalid.")

        source_start = _int_value(raw_section.get("source_segment_start_index"))
        source_end = _int_value(raw_section.get("source_segment_end_index"))
        _validate_source_segment_range(
            source_start,
            source_end,
            transcript_segment_count=transcript_segment_count,
            covered_source_indices=covered_source_indices,
        )

        section = {
            "section_index": index,
            "title": redact_text(
                _first_text(raw_section.get("title")).strip(),
                max_length=None,
            ),
            "start": start,
            "end": end,
            "timestamp_url": ref.timestamp_url(start),
            "cleaning_level": cleaning_level,
            "source_segment_start_index": source_start,
            "source_segment_end_index": source_end,
            "paragraphs": _normalized_paragraphs(raw_section.get("paragraphs")),
            "key_terms": _string_list(raw_section.get("key_terms")),
            "warnings": _string_list(raw_section.get("warnings")),
        }
        sections.append(section)

    normalized["sections"] = sections
    _validate_json(normalized, ARTICLE_SCHEMA, "transcript article")
    return normalized


def generate_transcript_article(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunks: dict[str, Any],
    run_dir: Path,
    provider: str = "codex-exec",
    model: str = "gpt-5.5",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if provider != "codex-exec":
        raise ArticleError(f"Unsupported LLM provider: {provider}")

    chunk_items = _chunk_items(chunks)
    partials = [
        run_codex_article_generation(
            ref=ref,
            metadata=metadata,
            transcript=transcript,
            chunk=chunk,
            run_dir=run_dir,
            model=model,
            runner=runner,
        )
        for chunk in chunk_items
    ]

    source = _first_text(transcript.get("source")).strip()
    article = {
        "schema_version": ARTICLE_SCHEMA_VERSION,
        "source": source,
        "cleaning_level": _cleaning_level_for_source(source),
        "sections": [
            section
            for partial in partials
            for section in partial.get("sections", [])
            if isinstance(section, dict)
        ],
        "warnings": [
            warning
            for partial in partials
            for warning in _string_list(partial.get("warnings"))
        ],
    }
    normalized = normalize_transcript_article(
        article,
        ref=ref,
        transcript=transcript,
        chunks=chunks,
    )
    _write_json(run_dir / ARTICLE_ARTIFACT, normalized)
    return normalized


def _cleaning_level_for_source(source: str) -> str:
    return "strong" if source == "whisper" else "light"


def _chunk_items(chunks: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chunks = chunks.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ArticleError("chunks.json contains no chunks.")
    return [chunk for chunk in raw_chunks if isinstance(chunk, dict)]


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


def _transcript_segment_count(transcript: dict[str, Any]) -> int:
    raw_segments = transcript.get("segments")
    return len(raw_segments) if isinstance(raw_segments, list) else 0


def _chunk_source_indices(chunks: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    for chunk in _chunk_items(chunks):
        for segment in _prompt_segments(chunk):
            source_index = _int_value(segment.get("source_index"))
            if source_index is not None and source_index >= 0:
                indices.add(source_index)
    return indices


def _validate_source_segment_range(
    source_start: int | None,
    source_end: int | None,
    *,
    transcript_segment_count: int,
    covered_source_indices: set[int],
) -> None:
    if (
        source_start is None
        or source_end is None
        or source_start < 0
        or source_end < source_start
        or source_end >= transcript_segment_count
    ):
        raise ArticleError("transcript article section source segment range was invalid.")
    if covered_source_indices and (
        source_start not in covered_source_indices or source_end not in covered_source_indices
    ):
        raise ArticleError("transcript article section source segment range was unanchored.")


def _normalized_paragraphs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ArticleError("transcript article section contained no paragraphs.")

    paragraphs: list[dict[str, Any]] = []
    for raw_paragraph in value:
        if not isinstance(raw_paragraph, dict):
            raise ArticleError("transcript article paragraph was not an object.")
        text = redact_text(_first_text(raw_paragraph.get("text")).strip(), max_length=None)
        if not text:
            raise ArticleError("transcript article paragraph text was empty.")
        paragraphs.append(
            {
                "text": text,
                "emphasis": _normalized_emphasis(raw_paragraph.get("emphasis")),
            }
        )
    return paragraphs


def _normalized_emphasis(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ArticleError("transcript article paragraph emphasis was not a list.")

    emphasis: list[dict[str, str]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            raise ArticleError("transcript article emphasis item was not an object.")
        text = redact_text(_first_text(raw_item.get("text")).strip(), max_length=None)
        kind = _first_text(raw_item.get("kind")).strip()
        if not text:
            raise ArticleError("transcript article emphasis text was empty.")
        if kind not in {"strong", "mark", "list"}:
            raise ArticleError("transcript article emphasis kind was invalid.")
        emphasis.append({"text": text, "kind": kind})
    return emphasis


def _validate_json(payload: dict[str, Any], schema: dict[str, Any], label: str) -> None:
    try:
        validate(instance=payload, schema=schema)
    except ValidationError as exc:
        raise ArticleError(f"Invalid {label} JSON: {exc.message}") from exc


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArticleError(f"{label} was not valid JSON.") from exc
    if not isinstance(payload, dict):
        raise ArticleError(f"{label} was not a JSON object.")
    return payload


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        redact_text(_first_text(item).strip(), max_length=None)
        for item in value
        if _first_text(item).strip()
    ]


def _nonnegative_float(value: Any, label: str) -> float:
    parsed = _float_value(value)
    if parsed is None:
        raise ArticleError(f"transcript article {label} was invalid.")
    return max(0.0, parsed)


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
