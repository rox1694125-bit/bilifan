from __future__ import annotations

from pathlib import Path
from typing import Any


class ExportError(RuntimeError):
    """Raised when export artifacts cannot be written."""


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
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
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
