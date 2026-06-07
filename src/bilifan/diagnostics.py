from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse


MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class Diagnostics:
    error_type: str | None
    exit_code: int
    stage: str
    video_id: str
    part_index: int
    duration_check: dict | None
    transcript_check: dict | None
    artifact_paths: list[str]
    sanitized_message: str
    warnings: list[str]


def redact_text(text: str, *, home_markers: list[Path] | None = None) -> str:
    redacted = str(text)
    redacted = _canonicalize_bilibili_urls(redacted)
    redacted = _redact_cookie_paths(redacted)
    redacted = _redact_bare_cookie_files(redacted)
    redacted = _redact_named_secrets(redacted)
    redacted = _redact_default_paths(redacted)
    redacted = _redact_home_markers(redacted, home_markers)
    return redacted[:MAX_MESSAGE_LENGTH]


def validate_artifact_paths(paths: list[str]) -> list[str]:
    if not isinstance(paths, list):
        raise ValueError("Invalid artifact paths: expected a list of strings.")

    validated: list[str] = []
    for raw_path in paths:
        if not isinstance(raw_path, str):
            raise ValueError("Invalid artifact path: expected a string.")
        if not raw_path or raw_path == ".":
            raise ValueError("Invalid artifact path: empty path.")
        if re.match(r"^[A-Za-z]:/", raw_path):
            raise ValueError(f"Invalid artifact path: {raw_path!r}.")
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
        "error_type": (
            None if diagnostics.error_type is None else redact_text(diagnostics.error_type)
        ),
        "exit_code": diagnostics.exit_code,
        "stage": redact_text(diagnostics.stage),
        "video_id": redact_text(diagnostics.video_id),
        "part_index": diagnostics.part_index,
        "duration_check": _sanitize_json_value(diagnostics.duration_check),
        "transcript_check": _sanitize_json_value(diagnostics.transcript_check),
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
    r"(?i)(?<!\S)((?:--)?cookies?(?:[_-]file|[_-]path)|cookies?\s+(?:file|path)|"
    r"cookie(?:[_-]file|[_-]path|\s+file|\s+path))(\s*[:=]\s*|\s+)[^\s;]+"
)
_BARE_COOKIE_FILE_PATTERN = re.compile(r"(?i)(?<!\S)\S*cookies?\S*\.txt(?!\S)")
_ENV_SECRET_PATTERN = re.compile(
    r"\b((?:CODEX_ACCESS_TOKEN|OPENAI_API_KEY|CODEX_API_KEY)\s*[:=]\s*)[^\s;&]+"
)
_AUTH_BEARER_PATTERN = re.compile(
    r"\b(Authorization\s*:\s*Bearer\s+)[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)
_OPENAI_TOKEN_PATTERN = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9._-]*")
_JWT_PATTERN = re.compile(r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+\b")
_COOKIE_HEADER_PATTERN = re.compile(r"\b(Cookie\s*:\s*)([^\r\n]*)", re.IGNORECASE)
_COOKIE_PAIR_PATTERN = re.compile(r"([^=;\s]+)=([^;\s]+)")
_BILIBILI_COOKIE_PATTERN = re.compile(
    r"\b(SESSDATA|bili_jct|DedeUserID|buvid\w*|sid)=([^;\s]+)"
)
_DEFAULT_PATH_PATTERN = re.compile(r"(?<![\w:/])(?:/Users|/Volumes)/[^\s;\"'<>)]*")
_TILDE_PATH_PATTERN = re.compile(r"(?<![\w])~/[^\s;\"'<>)]*")


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
    return _COOKIE_PATH_PATTERN.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        text,
    )


def _redact_bare_cookie_files(text: str) -> str:
    return _BARE_COOKIE_FILE_PATTERN.sub("<redacted-cookie-file>", text)


def _redact_named_secrets(text: str) -> str:
    redacted = _ENV_SECRET_PATTERN.sub(r"\1<redacted>", text)
    redacted = _AUTH_BEARER_PATTERN.sub(r"\1<redacted>", redacted)
    redacted = _redact_cookie_headers(redacted)
    redacted = _BILIBILI_COOKIE_PATTERN.sub(r"\1=<redacted>", redacted)
    redacted = _OPENAI_TOKEN_PATTERN.sub("<redacted>", redacted)
    return _JWT_PATTERN.sub("<redacted-jwt>", redacted)


def _redact_cookie_headers(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        redacted_cookie_values = _COOKIE_PAIR_PATTERN.sub(
            lambda cookie_match: f"{cookie_match.group(1)}=<redacted>",
            match.group(2),
        )
        return f"{match.group(1)}{redacted_cookie_values}"

    return _COOKIE_HEADER_PATTERN.sub(replace, text)


def _redact_default_paths(text: str) -> str:
    redacted = _DEFAULT_PATH_PATTERN.sub("<redacted-path>", text)
    return _TILDE_PATH_PATTERN.sub("<redacted-path>", redacted)


def _redact_home_markers(text: str, home_markers: list[Path] | None) -> str:
    extra_markers = [] if home_markers is None else home_markers
    markers = _unique_markers([*extra_markers, *_default_home_markers()])
    redacted = text
    for marker in markers:
        marker_text = str(marker)
        if marker_text and marker_text != "/":
            redacted = re.sub(
                rf"{re.escape(marker_text)}[^\s;\"'<>)]*",
                "<redacted-path>",
                redacted,
            )
    return redacted


def _default_home_markers() -> list[Path]:
    return _unique_markers([Path.home(), Path("/Users/jack"), Path("/Volumes/mySSD")])


def _unique_markers(markers: list[Path]) -> list[Path]:
    unique_markers: list[Path] = []
    seen: set[str] = set()
    for marker in markers:
        marker_text = str(marker)
        if marker_text not in seen:
            unique_markers.append(marker)
            seen.add(marker_text)
    return unique_markers


def _sanitize_json_value(value: object) -> object:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            redact_text(str(key)): _sanitize_json_value(nested_value)
            for key, nested_value in value.items()
        }
    if isinstance(value, list | tuple | set):
        return [_sanitize_json_value(item) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value
    return redact_text(str(value))
