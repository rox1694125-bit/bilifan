from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bilifan.diagnostics import redact_text


def read_metadata_title(run_dir: Path) -> str | None:
    data = _read_json_object(run_dir / "metadata.json")
    title = data.get("title") or data.get("part_title")
    return redact_text(title) if isinstance(title, str) and title.strip() else None


def read_transcript_source_label(run_dir: Path) -> str | None:
    label = transcript_source_label(_read_json_object(run_dir / "transcript.json"))
    return label or None


def transcript_source_label(transcript: dict[str, Any]) -> str:
    source = _text(transcript.get("source"))
    model = _text(transcript.get("model"))
    if source == "whisper":
        return f"Whisper {model}".strip()
    if source == "bilibili-subtitle":
        return "B站字幕"
    if source == "youtube-subtitle":
        return "YouTube 字幕"
    if source.endswith("-subtitle"):
        return "平台字幕"
    return source


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
