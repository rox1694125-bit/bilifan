from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from .bilibili import BilibiliPartRef, parse_bilibili_url
from .metadata import fetch_current_part_metadata


MetadataFetcher = Callable[[BilibiliPartRef, Path], dict[str, Any]]


def preview_bilibili_collection(
    url: str,
    *,
    work_dir: Path,
    metadata_fetcher: MetadataFetcher = fetch_current_part_metadata,
) -> dict[str, Any]:
    ref = parse_bilibili_url(url)
    preview_dir = work_dir / "_collection_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    metadata = metadata_fetcher(ref, preview_dir)
    parts = _preview_parts(ref, metadata)

    return {
        "ok": True,
        "platform": "bilibili",
        "bvid": ref.bvid,
        "title": _text(metadata.get("title")),
        "current_part_index": ref.part_index,
        "current_url": ref.sanitized_url,
        "total_parts": len(parts),
        "parts": parts,
    }


def _preview_parts(ref: BilibiliPartRef, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    raw_parts = metadata.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        return [
            _part_payload(
                ref,
                part_index=ref.part_index,
                title=_text(metadata.get("part_title"), metadata.get("title")),
                duration=_duration(metadata.get("duration")),
            )
        ]

    parts: list[dict[str, Any]] = []
    seen: set[int] = set()
    for fallback_index, raw_part in enumerate(raw_parts, start=1):
        if not isinstance(raw_part, dict):
            continue
        part_index = _positive_int(raw_part.get("part_index")) or fallback_index
        if part_index in seen:
            continue
        seen.add(part_index)
        parts.append(
            _part_payload(
                ref,
                part_index=part_index,
                title=_text(raw_part.get("title")),
                duration=_duration(raw_part.get("duration")),
            )
        )

    if not parts:
        return [
            _part_payload(
                ref,
                part_index=ref.part_index,
                title=_text(metadata.get("part_title"), metadata.get("title")),
                duration=_duration(metadata.get("duration")),
            )
        ]
    return sorted(parts, key=lambda item: int(item["part_index"]))


def _part_payload(
    ref: BilibiliPartRef,
    *,
    part_index: int,
    title: str,
    duration: int | float | None,
) -> dict[str, Any]:
    return {
        "part_index": part_index,
        "title": title,
        "duration": duration,
        "url": f"https://www.bilibili.com/video/{ref.bvid}?p={part_index}",
        "is_current": part_index == ref.part_index,
    }


def _text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _duration(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None
