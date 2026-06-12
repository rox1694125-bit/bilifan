from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .diagnostics import redact_text


class ExportError(RuntimeError):
    """Raised when export artifacts cannot be written."""


NABAICHUAN_JSONL = "nabaichuan.jsonl"
NABAICHUAN_MIN_SEGMENT_SECONDS = 30.0
NABAICHUAN_MAX_SEGMENT_SECONDS = 90.0


def write_transcript_exports(
    run_dir: str | Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    overwrite: bool = False,
) -> list[str]:
    artifacts = ["transcript.txt", "transcript.srt"]
    output_dir = Path(run_dir)
    _ensure_output_dir(output_dir)
    _write_if_allowed(
        output_dir / "transcript.txt",
        render_transcript_text(metadata, transcript),
        overwrite=overwrite,
    )
    _write_if_allowed(
        output_dir / "transcript.srt",
        render_transcript_srt(transcript),
        overwrite=overwrite,
    )
    return artifacts


def write_notes_markdown(
    run_dir: str | Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    overwrite: bool = False,
) -> list[str]:
    artifacts = ["notes.md"]
    output_dir = Path(run_dir)
    _ensure_output_dir(output_dir)
    _write_if_allowed(
        output_dir / "notes.md",
        render_notes_markdown(metadata, transcript, chapters),
        overwrite=overwrite,
    )
    return artifacts


def write_nabaichuan_jsonl(
    run_dir: str | Path,
    bundle: dict[str, Any] | None = None,
    overwrite: bool = True,
) -> str:
    output_dir = Path(run_dir)
    _ensure_output_dir(output_dir)
    content_bundle = bundle if bundle is not None else _read_content_bundle(output_dir)
    records = build_nabaichuan_records(content_bundle)
    output_path = output_dir / NABAICHUAN_JSONL
    _write_if_allowed(
        output_path,
        "".join(
            json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
            for record in records
        ),
        overwrite=overwrite,
    )
    return NABAICHUAN_JSONL


def build_nabaichuan_records(
    bundle: dict[str, Any],
    *,
    include_transcript: bool = True,
) -> list[dict[str, Any]]:
    if not isinstance(bundle, dict):
        raise ExportError("content_bundle must be a JSON object.")
    bundle_id = _first_text(bundle.get("bundle_id"))
    if not bundle_id:
        raise ExportError("content_bundle is missing bundle_id.")

    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    source_payload = {
        "platform": _first_text(source.get("platform")),
        "id": _first_text(source.get("id")),
        "part_id": _first_text(source.get("part_id")),
        "canonical_url": _first_text(source.get("canonical_url")),
        "title": _first_text(source.get("title")),
        "author": _first_text(source.get("author")),
        "duration_seconds": _float_value(source.get("duration_seconds")),
        "language": _first_text(source.get("language")),
    }

    video_record = {
        "type": "video",
        "record_id": f"{bundle_id}:video",
        "parent_record_id": None,
        "source": source_payload,
        "title": source_payload["title"],
        "text": source_payload["title"],
    }
    records = [_with_content_hash(video_record)]

    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    chapters = summary.get("chapters") if isinstance(summary.get("chapters"), list) else []
    chapter_records: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        if not isinstance(chapter, dict):
            continue
        chapter_index = chapter.get("chapter_index")
        if not isinstance(chapter_index, int) or isinstance(chapter_index, bool):
            chapter_index = index
        chapter_id = f"{bundle_id}:chapter:{chapter_index}"
        chapter_record = {
            "type": "chapter",
            "record_id": chapter_id,
            "chapter_id": chapter_id,
            "parent_record_id": video_record["record_id"],
            "source": source_payload,
            "chapter_index": chapter_index,
            "title": _first_text(chapter.get("title")),
            "summary": _first_text(chapter.get("summary")),
            "key_points": _string_list(chapter.get("key_points")),
            "start": _float_value(chapter.get("start")),
            "end": _float_value(chapter.get("end")),
            "timestamp_url": _first_text(chapter.get("timestamp_url")),
        }
        chapter_record["text"] = _record_text(
            chapter_record["title"],
            chapter_record["summary"],
            *chapter_record["key_points"],
        )
        chapter_records.append(chapter_record)
        records.append(_with_content_hash(chapter_record))

    if include_transcript:
        for index, segment in enumerate(
            _merged_transcript_segments(bundle),
            start=1,
        ):
            start = _float_value(segment.get("start")) or 0.0
            end = _float_value(segment.get("end")) or start
            chapter_id = _chapter_id_for_time(
                chapter_records,
                (start + end) / 2,
            ) or _chapter_id_for_time(chapter_records, start)
            record = {
                "type": "transcript_segment",
                "record_id": (
                    f"{bundle_id}:transcript_segment:{index}:"
                    f"{_millis(start)}-{_millis(end)}"
                ),
                "parent_record_id": video_record["record_id"],
                "chapter_id": chapter_id,
                "source": source_payload,
                "start": start,
                "end": end,
                "timestamp_url": _timestamp_url(source_payload["canonical_url"], start),
                "text": _first_text(segment.get("text")),
            }
            records.append(_with_content_hash(record))
    return records


def render_transcript_text(metadata: dict[str, Any], transcript: dict[str, Any]) -> str:
    check = transcript.get("transcript_check") if isinstance(transcript, dict) else None
    lines = [
        f"Title: {_first_text(metadata.get('title'), metadata.get('part_title'))}",
        f"Part: {_first_text(metadata.get('part_title'))}",
        f"UP: {_first_text(metadata.get('owner_name'), metadata.get('owner'))}",
        f"Duration: {_duration_label(metadata.get('duration'))}",
        f"Metadata Source: {_first_text(metadata.get('metadata_source'))}",
        f"Original URL: {_first_text(metadata.get('input_url_sanitized'), metadata.get('url'))}",
        f"Source: {_first_text(transcript.get('source'))}",
        f"Model: {_first_text(transcript.get('model'))}",
        f"Language: {_first_text(transcript.get('language'))}",
        f"Check: {_first_text(check.get('status')) if isinstance(check, dict) else ''}",
        "",
        "Transcript:",
    ]
    for segment in _segments(transcript):
        lines.append(f"[{_short_timestamp(segment['start'])}] {segment['text']}")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_transcript_srt(transcript: dict[str, Any]) -> str:
    blocks: list[str] = []
    for index, segment in enumerate(_segments(transcript), start=1):
        end = segment["end"] if segment["end"] >= segment["start"] else segment["start"]
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(end)}",
                    segment["text"],
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def render_notes_markdown(
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
) -> str:
    title = _first_text(metadata.get("title"), metadata.get("part_title")) or "Untitled"
    chapter_items = _chapter_items(chapters)
    lines = [
        f"# {title}",
        "",
        f"- UP: {_first_text(metadata.get('owner_name'), metadata.get('owner'))}",
        f"- 当前 P: {_first_text(metadata.get('part_title'))}",
        f"- 时长: {_duration_label(metadata.get('duration'))}",
        f"- 转写来源: {_first_text(transcript.get('source'))}",
        f"- 模型: {_first_text(transcript.get('model'))}",
        f"- 语言: {_first_text(transcript.get('language'))}",
        f"- 原视频: {_first_text(metadata.get('input_url_sanitized'), metadata.get('url'))}",
        "",
        "## 总摘要",
        "",
        _notes_summary(chapter_items),
        "",
        "## 目录",
        "",
    ]

    if chapter_items:
        for chapter in chapter_items:
            lines.append(
                f"- [{chapter['start_label']} {chapter['title']}]({chapter['timestamp_url']})"
                if chapter["timestamp_url"]
                else f"- {chapter['start_label']} {chapter['title']}"
            )
    else:
        lines.append("No chapters available.")

    lines.extend(["", "## 章节", ""])
    if chapter_items:
        for chapter in chapter_items:
            heading = f"## {chapter['chapter_index']}. {chapter['title']}"
            lines.extend(
                [
                    heading,
                    "",
                    f"时间戳: {chapter['start_label']}",
                    f"链接: {chapter['timestamp_url']}" if chapter["timestamp_url"] else "链接: ",
                    "",
                    "### 摘要",
                    "",
                    chapter["summary"] or "-",
                    "",
                    "### 要点",
                    "",
                ]
            )
            lines.extend(_bullet_lines(chapter["key_points"]))
            lines.extend(["", "### 关键引用", ""])
            lines.extend(_quote_lines(chapter["quotes"]))
            lines.extend(["", "### 视觉锚点", ""])
            lines.extend(_bullet_lines(chapter["visual_anchors"]))
            lines.append("")
    else:
        lines.append("No chapters available.")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


def format_srt_timestamp(seconds: Any) -> str:
    value = max(0.0, _float_value(seconds) or 0.0)
    total_milliseconds = int(round(value * 1000))
    total_seconds, milliseconds = divmod(total_milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"


def _ensure_output_dir(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ExportError(f"Failed to create export directory: {exc}") from exc


def _write_if_allowed(path: Path, content: str, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        return
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ExportError(f"Failed to write export artifact {path.name}: {exc}") from exc


def _read_content_bundle(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "content_bundle.json"
    if not path.is_file():
        raise ExportError("Cannot write nabaichuan.jsonl without content_bundle.json.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExportError("Invalid content_bundle.json.") from exc
    if not isinstance(data, dict):
        raise ExportError("Invalid content_bundle.json.")
    return data


def _with_content_hash(record: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_nabaichuan_record(record)
    normalized = {
        key: value
        for key, value in sanitized.items()
        if key not in {"content_hash"}
    }
    digest = hashlib.sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {**sanitized, "content_hash": digest}


def _sanitize_nabaichuan_record(value: Any, *, key: str = "") -> Any:
    if isinstance(value, str):
        if key in {"canonical_url", "timestamp_url"}:
            return value
        return redact_text(value, max_length=None)
    if isinstance(value, dict):
        return {
            str(nested_key): _sanitize_nabaichuan_record(
                nested_value,
                key=str(nested_key),
            )
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_nabaichuan_record(item, key=key) for item in value]
    return value


def _merged_transcript_segments(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = bundle.get("transcript") if isinstance(bundle.get("transcript"), dict) else {}
    raw_segments = transcript.get("segments") if isinstance(transcript.get("segments"), list) else []
    segments: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        text = _first_text(raw_segment.get("text"))
        if not text:
            continue
        start = max(0.0, _float_value(raw_segment.get("start")) or 0.0)
        end = _float_value(raw_segment.get("end"))
        segments.append(
            {
                "start": start,
                "end": max(start, end if end is not None else start),
                "text": text,
            }
        )
    segments.sort(key=lambda item: (item["start"], item["end"]))
    if not segments:
        return []

    transcript_start = min(segment["start"] for segment in segments)
    transcript_end = max(segment["end"] for segment in segments)
    total_duration = max(0.0, transcript_end - transcript_start)
    if total_duration <= NABAICHUAN_MAX_SEGMENT_SECONDS:
        return [
            {
                "start": transcript_start,
                "end": transcript_end,
                "text": "\n".join(segment["text"] for segment in segments),
            }
        ]

    window_count = max(1, math.ceil(total_duration / NABAICHUAN_MAX_SEGMENT_SECONDS))
    window_duration = total_duration / window_count
    windows = [
        {
            "start": transcript_start + index * window_duration,
            "end": (
                transcript_end
                if index == window_count - 1
                else transcript_start + (index + 1) * window_duration
            ),
            "texts": [],
        }
        for index in range(window_count)
    ]

    for segment in segments:
        midpoint = (segment["start"] + segment["end"]) / 2
        closest = min(
            range(len(windows)),
            key=lambda index: abs(
                midpoint - ((windows[index]["start"] + windows[index]["end"]) / 2)
            ),
        )
        if segment["end"] - segment["start"] <= NABAICHUAN_MAX_SEGMENT_SECONDS:
            overlaps = [closest]
        else:
            overlaps = [
                index
                for index, window in enumerate(windows)
                if segment["start"] < window["end"] and segment["end"] > window["start"]
            ] or [closest]
        text_parts = _split_text_evenly(segment["text"], len(overlaps))
        for index, text_part in zip(overlaps, text_parts, strict=False):
            if text_part:
                windows[index]["texts"].append(text_part)

    merged = []
    for window in windows:
        if not window["texts"]:
            continue
        merged.append(
            {
                "start": window["start"],
                "end": window["end"],
                "text": "\n".join(window["texts"]),
            }
        )
    return merged


def _split_text_evenly(text: str, part_count: int) -> list[str]:
    if part_count <= 1:
        return [text]
    normalized = text.strip()
    if not normalized:
        return [""] * part_count
    return [
        normalized[
            round(index * len(normalized) / part_count) : round(
                (index + 1) * len(normalized) / part_count
            )
        ].strip()
        for index in range(part_count)
    ]


def _chapter_id_for_time(chapters: list[dict[str, Any]], seconds: float) -> str | None:
    for chapter in chapters:
        start = _float_value(chapter.get("start"))
        end = _float_value(chapter.get("end"))
        if start is None:
            continue
        if end is None:
            if seconds >= start:
                return _first_text(chapter.get("chapter_id")) or None
            continue
        if start <= seconds < end or seconds == start == end:
            return _first_text(chapter.get("chapter_id")) or None
    return None


def _timestamp_url(canonical_url: str, seconds: float) -> str:
    if not canonical_url:
        return ""
    timestamp = str(max(0, int(seconds)))
    parsed = urlparse(canonical_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if "youtube.com" in parsed.netloc or "youtu.be" in parsed.netloc:
        query["t"] = f"{timestamp}s"
    else:
        query["t"] = timestamp
    return urlunparse(parsed._replace(query=urlencode(query)))


def _millis(seconds: float) -> int:
    return int(round(max(0.0, seconds) * 1000))


def _record_text(*parts: str) -> str:
    return "\n".join(part for part in parts if part)


def _segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = transcript.get("segments") if isinstance(transcript, dict) else None
    if not isinstance(raw_segments, list):
        return []

    segments: list[dict[str, Any]] = []
    for raw_segment in raw_segments:
        if not isinstance(raw_segment, dict):
            continue
        start = _float_value(raw_segment.get("start")) or 0.0
        end = _float_value(raw_segment.get("end"))
        segments.append(
            {
                "start": max(0.0, start),
                "end": max(0.0, end if end is not None else start),
                "text": _first_text(raw_segment.get("text")),
            }
        )
    return segments


def _chapter_items(chapters: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chapters = chapters.get("chapters") if isinstance(chapters, dict) else chapters
    if not isinstance(raw_chapters, list):
        return []

    items: list[dict[str, Any]] = []
    for index, raw_chapter in enumerate(raw_chapters, start=1):
        if not isinstance(raw_chapter, dict):
            continue
        start = max(0.0, _float_value(raw_chapter.get("start")) or 0.0)
        title = _first_text(raw_chapter.get("title")) or f"Chapter {index}"
        chapter_index = raw_chapter.get("chapter_index")
        if not isinstance(chapter_index, int) or isinstance(chapter_index, bool):
            chapter_index = index
        items.append(
            {
                "chapter_index": chapter_index,
                "title": title,
                "start_label": _short_timestamp(start),
                "timestamp_url": _first_text(raw_chapter.get("timestamp_url")),
                "summary": _first_text(raw_chapter.get("summary")),
                "key_points": _string_list(raw_chapter.get("key_points")),
                "quotes": _string_list(raw_chapter.get("quotes")),
                "visual_anchors": _string_list(raw_chapter.get("visual_anchors")),
            }
        )
    return items


def _notes_summary(chapters: list[dict[str, Any]]) -> str:
    for chapter in chapters:
        if chapter["summary"]:
            return chapter["summary"]
    return "No summary available."


def _bullet_lines(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] if items else ["-"]


def _quote_lines(items: list[str]) -> list[str]:
    return [f"> {item}" for item in items] if items else ["> -"]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_first_text(item) for item in value if _first_text(item)]


def _short_timestamp(seconds: Any) -> str:
    value = max(0, int(_float_value(seconds) or 0))
    hours, remainder = divmod(value, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _duration_label(value: Any) -> str:
    seconds = _float_value(value)
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _float_value(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
    return ""
