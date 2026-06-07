from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse


MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class Diagnostics:
    error_type: str
    exit_code: int
    stage: str
    video_id: str
    part_index: int
    duration_check: str
    transcript_check: str
    artifact_paths: list[str]
    sanitized_message: str
    warnings: list[str]


def redact_text(text: str, *, home_markers: list[Path] | None = None) -> str:
    redacted = str(text)
    redacted = _canonicalize_bilibili_urls(redacted)
    redacted = _redact_cookie_paths(redacted)
    redacted = _redact_named_secrets(redacted)
    redacted = _redact_home_markers(redacted, home_markers)
    return redacted[:MAX_MESSAGE_LENGTH]


def validate_artifact_paths(paths: list[str]) -> list[str]:
    validated: list[str] = []
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise ValueError("Invalid artifact path: expected a string.")
        if not raw_path or raw_path == ".":
            raise ValueError("Invalid artifact path: empty path.")
        if "\\" in raw_path or raw_path.startswith("~"):
            raise ValueError(f"Invalid artifact path: {raw_path!r}.")

        path = PurePosixPath(raw_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"Invalid artifact path: {raw_path!r}.")

        validated.append(raw_path)
    return validated


def write_diagnostics(path: Path, diagnostics: Diagnostics) -> None:
    artifact_paths = validate_artifact_paths(diagnostics.artifact_paths)
    data = {
        "error_type": redact_text(diagnostics.error_type),
        "exit_code": diagnostics.exit_code,
        "stage": redact_text(diagnostics.stage),
        "video_id": redact_text(diagnostics.video_id),
        "part_index": diagnostics.part_index,
        "duration_check": redact_text(diagnostics.duration_check),
        "transcript_check": redact_text(diagnostics.transcript_check),
        "artifact_paths": artifact_paths,
        "sanitized_message": redact_text(diagnostics.sanitized_message),
        "warnings": [redact_text(warning) for warning in diagnostics.warnings],
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


_BILIBILI_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?bilibili\.com/video/BV[0-9A-Za-z]{10}/?(?:\?[^\s\"'<>)]*)?"
)
_COOKIE_PATH_PATTERN = re.compile(
    r"(?i)(cookie(?:_file|-file|\s+file|_path|-path|\s+path)\s*[:=]\s*)[^\s;]+"
)
_CODEX_ACCESS_TOKEN_PATTERN = re.compile(r"\b(CODEX_ACCESS_TOKEN\s*[:=]\s*)[^\s;&]+")
_AUTH_BEARER_PATTERN = re.compile(
    r"\b(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_OPENAI_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]*")
_BILIBILI_COOKIE_PATTERN = re.compile(r"\b(SESSDATA|bili_jct|DedeUserID)=([^;\s]+)")


def _canonicalize_bilibili_urls(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw_url = match.group(0)
        parsed = urlparse(raw_url)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 2 or parts[0] != "video":
            return raw_url

        bvid = parts[1]
        query = parse_qs(parsed.query, keep_blank_values=True)
        raw_part = query.get("p", ["1"])[0]
        try:
            part_index = int(raw_part)
        except ValueError:
            part_index = 1
        if part_index < 1:
            part_index = 1

        return f"https://www.bilibili.com/video/{bvid}?p={part_index}"

    return _BILIBILI_URL_PATTERN.sub(replace, text)


def _redact_cookie_paths(text: str) -> str:
    return _COOKIE_PATH_PATTERN.sub(lambda match: f"{match.group(1)}<redacted>", text)


def _redact_named_secrets(text: str) -> str:
    redacted = _CODEX_ACCESS_TOKEN_PATTERN.sub(r"\1<redacted>", text)
    redacted = _AUTH_BEARER_PATTERN.sub(r"\1<redacted>", redacted)
    redacted = _BILIBILI_COOKIE_PATTERN.sub(r"\1=<redacted>", redacted)
    return _OPENAI_TOKEN_PATTERN.sub("<redacted>", redacted)


def _redact_home_markers(text: str, home_markers: list[Path] | None) -> str:
    markers = _default_home_markers() if home_markers is None else home_markers
    redacted = text
    for marker in markers:
        marker_text = str(marker)
        if marker_text and marker_text != "/":
            redacted = redacted.replace(marker_text, "<redacted-path>")
    return redacted


def _default_home_markers() -> list[Path]:
    markers = [Path.home(), Path("/Users/jack"), Path("/Volumes/mySSD")]
    unique_markers: list[Path] = []
    seen: set[str] = set()
    for marker in markers:
        marker_text = str(marker)
        if marker_text not in seen:
            unique_markers.append(marker)
            seen.add(marker_text)
    return unique_markers
