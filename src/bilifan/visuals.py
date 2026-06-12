from __future__ import annotations

import html
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .diagnostics import redact_text


Runner = Callable[..., subprocess.CompletedProcess[str]]
FRAME_TIMEOUT_SECONDS = 60


class VisualError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


def enrich_chapters_with_visuals(
    *,
    ref: Any,
    chapters: dict[str, Any],
    media: dict[str, Any],
    run_dir: Path,
    with_frames: bool = False,
    with_diagrams: bool = False,
    runner: Runner = subprocess.run,
) -> list[str]:
    warnings: list[str] = []
    chapter_items = _chapter_items(chapters)
    if with_diagrams:
        for chapter in chapter_items:
            chapter["diagram"] = _diagram_for_chapter(chapter)
    if with_frames:
        video_path = _video_path(run_dir, media)
        if video_path is None:
            warnings.append("frames_unavailable")
        else:
            frame_warnings = _extract_chapter_frames(
                ref=ref,
                chapters=chapter_items,
                run_dir=run_dir,
                video_path=video_path,
                runner=runner,
            )
            warnings.extend(frame_warnings)
    return _unique(warnings)


def visual_artifact_paths(chapters: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for chapter in _chapter_items(chapters):
        frame = chapter.get("frame")
        if isinstance(frame, dict):
            path = frame.get("path")
            if isinstance(path, str) and path:
                paths.append(path)
    return _unique(paths)


def _chapter_items(chapters: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chapters = chapters.get("chapters")
    if not isinstance(raw_chapters, list):
        return []
    return [chapter for chapter in raw_chapters if isinstance(chapter, dict)]


def _diagram_for_chapter(chapter: dict[str, Any]) -> dict[str, str]:
    title = _first_text(chapter.get("title")) or "章节"
    key_points = _string_list(chapter.get("key_points"))
    labels = key_points[:4] or [_first_text(chapter.get("summary"))[:18] or title]
    diagram_type = _diagram_type(title, labels)
    svg = _flow_svg(title, labels)
    return {
        "type": diagram_type,
        "caption": f"图解：{title}",
        "svg": svg,
    }


def _diagram_type(title: str, labels: list[str]) -> str:
    normalized = f"{title} {' '.join(labels)}"
    if any(marker in normalized for marker in ("流程", "步骤", "路径")):
        return "flow"
    if any(marker in normalized for marker in ("对比", "区别", "差异", "矩阵")):
        return "comparison"
    if any(marker in normalized for marker in ("风险", "误区", "检查")):
        return "checklist"
    if any(marker in normalized for marker in ("时间", "阶段", "先", "然后", "最后")):
        return "timeline"
    return "flow"


def _flow_svg(title: str, labels: list[str]) -> str:
    width = 760
    height = 150
    safe_title = html.escape(title)
    nodes = []
    arrows = []
    node_width = 150
    gap = 36
    start_x = 32
    y = 58
    for index, label in enumerate(labels):
        x = start_x + index * (node_width + gap)
        safe_label = html.escape(_trim(label, 14))
        nodes.append(
            "\n".join(
                [
                    f'<rect x="{x}" y="{y}" width="{node_width}" height="54" rx="8" fill="#f7f9fc" stroke="#8aa4c2"/>',
                    f'<text x="{x + node_width / 2:.0f}" y="{y + 32}" text-anchor="middle" font-size="16" fill="#1f2933">{safe_label}</text>',
                ]
            )
        )
        if index < len(labels) - 1:
            arrow_x = x + node_width + 8
            arrows.append(
                f'<path d="M{arrow_x} {y + 27} H{arrow_x + gap - 16}" stroke="#0b6bcb" stroke-width="2" marker-end="url(#arrow)"/>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="图解：{safe_title}">'
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" '
        'orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="#0b6bcb"/></marker></defs>'
        f'<text x="32" y="30" font-size="18" font-weight="700" fill="#1f2933">{safe_title}</text>'
        f'{"".join(nodes)}{"".join(arrows)}</svg>'
    )


def _extract_chapter_frames(
    *,
    ref: Any,
    chapters: list[dict[str, Any]],
    run_dir: Path,
    video_path: Path,
    runner: Runner,
) -> list[str]:
    warnings: list[str] = []
    frame_dir = run_dir / "media" / "frames"
    frame_dir.mkdir(parents=True, exist_ok=True)
    for chapter in chapters:
        chapter_index = _int_value(chapter.get("chapter_index")) or len(chapters)
        timestamp = _chapter_frame_timestamp(chapter)
        relative_path = Path("media") / "frames" / f"chapter_{chapter_index:03d}_{int(timestamp):06d}.jpg"
        output_path = run_dir / relative_path
        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "1",
            str(relative_path),
        ]
        try:
            result = runner(
                cmd,
                cwd=run_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=FRAME_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired):
            warnings.append("frame_extract_failed")
            continue
        if result.returncode != 0 or not output_path.is_file():
            warnings.append("frame_extract_failed")
            continue
        chapter["frame"] = {
            "path": str(relative_path),
            "timestamp": timestamp,
            "timestamp_url": ref.timestamp_url(timestamp),
            "caption": f"视频时间戳：{_format_time(timestamp)}",
        }
    return _unique(warnings)


def _video_path(run_dir: Path, media: dict[str, Any]) -> Path | None:
    raw_path = media.get("video_path")
    if not isinstance(raw_path, str) or not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = run_dir / path
    try:
        resolved = path.resolve(strict=False)
        run_root = run_dir.resolve(strict=False)
    except OSError:
        return None
    if not resolved.is_relative_to(run_root) or not resolved.is_file():
        return None
    return resolved


def _chapter_frame_timestamp(chapter: dict[str, Any]) -> float:
    start = _float_value(chapter.get("start")) or 0.0
    end = _float_value(chapter.get("end"))
    if end is None or end <= start:
        return start
    return start + ((end - start) / 2)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_first_text(item) for item in value if _first_text(item)]


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int | float):
        return str(value)
    return ""


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


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _trim(value: str, max_chars: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _unique(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        if value not in unique:
            unique.append(value)
    return unique
