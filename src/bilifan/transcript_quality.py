from __future__ import annotations

import re
from collections import Counter
from typing import Any

from .transcription_routing import metadata_language_conflict


WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")


def check_transcript_quality(
    segments: list[dict[str, Any]],
    *,
    expected_language: str,
    metadata: dict[str, Any] | None = None,
    audio_seconds: int | float | None = None,
) -> dict[str, Any]:
    text = " ".join(_segment_text(segment) for segment in segments).strip()
    metrics = _metrics(text, segments=segments, audio_seconds=audio_seconds)
    observed_language = _observed_language(metrics)
    warnings = _warnings(
        expected_language=expected_language,
        observed_language=observed_language,
        metrics=metrics,
        metadata=metadata or {},
    )
    status = _status(warnings)
    return {
        "schema_version": 1,
        "status": status,
        "expected_language": expected_language,
        "observed_language": observed_language,
        "confidence": _confidence(status),
        "warnings": warnings,
        "metrics": metrics,
    }


def _metrics(
    text: str,
    *,
    segments: list[dict[str, Any]],
    audio_seconds: int | float | None,
) -> dict[str, Any]:
    compact = "".join(char for char in text if not char.isspace())
    cjk_count = sum(1 for char in compact if "\u4e00" <= char <= "\u9fff")
    ascii_words = WORD_RE.findall(text)
    ascii_word_chars = sum(len(word) for word in ascii_words)
    char_count = len(compact)
    duration = float(audio_seconds or 0)
    return {
        "char_count": char_count,
        "audio_seconds": duration if duration > 0 else None,
        "cjk_ratio": round(cjk_count / char_count, 4) if char_count else 0,
        "ascii_word_ratio": round(ascii_word_chars / char_count, 4)
        if char_count
        else 0,
        "repeat_fragment_ratio": round(_repeat_fragment_ratio(segments), 4),
        "chars_per_second": round(char_count / duration, 4) if duration > 0 else None,
    }


def _observed_language(metrics: dict[str, Any]) -> str:
    cjk_ratio = float(metrics.get("cjk_ratio") or 0)
    ascii_word_ratio = float(metrics.get("ascii_word_ratio") or 0)
    if cjk_ratio >= 0.2 and cjk_ratio >= ascii_word_ratio:
        return "zh"
    if ascii_word_ratio >= 0.45:
        return "en"
    return "unknown"


def _warnings(
    *,
    expected_language: str,
    observed_language: str,
    metrics: dict[str, Any],
    metadata: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    char_count = int(metrics.get("char_count") or 0)
    cjk_ratio = float(metrics.get("cjk_ratio") or 0)
    ascii_word_ratio = float(metrics.get("ascii_word_ratio") or 0)
    repeat_fragment_ratio = float(metrics.get("repeat_fragment_ratio") or 0)
    chars_per_second = metrics.get("chars_per_second")

    duration = metrics.get("audio_seconds")
    if char_count == 0 or (char_count < 12 and isinstance(duration, (int, float)) and duration > 15):
        warnings.append("too_little_text")
    if repeat_fragment_ratio >= 0.55:
        warnings.append("high_repetition")
    if isinstance(chars_per_second, (int, float)) and chars_per_second < 0.08:
        warnings.append("very_low_text_density")

    metadata_has_cjk = _contains_cjk(_metadata_text(metadata))
    if expected_language == "zh":
        if cjk_ratio < 0.08 and ascii_word_ratio >= 0.45:
            warnings.append("expected_zh_but_low_cjk")
        elif metadata_has_cjk and cjk_ratio < 0.18:
            warnings.append("expected_zh_low_confidence")
    elif expected_language == "en":
        if ascii_word_ratio < 0.35 and cjk_ratio >= 0.2:
            warnings.append("expected_en_but_low_ascii_words")
        elif ascii_word_ratio < 0.45:
            warnings.append("expected_en_low_confidence")

    if metadata_language_conflict(metadata, observed_language):
        warnings.append("metadata_language_conflict")

    return _unique(warnings)


def _status(warnings: list[str]) -> str:
    if (
        "high_repetition" in warnings
        or "too_little_text" in warnings
        or "very_low_text_density" in warnings
    ):
        return "unusable"
    if (
        "expected_zh_but_low_cjk" in warnings
        or "expected_en_but_low_ascii_words" in warnings
    ):
        return "suspect_wrong_route"
    if warnings:
        return "low_confidence"
    return "ok"


def _confidence(status: str) -> str:
    if status == "ok":
        return "high"
    if status == "low_confidence":
        return "medium"
    return "low"


def _repeat_fragment_ratio(segments: list[dict[str, Any]]) -> float:
    normalized = [_normalize_fragment(_segment_text(segment)) for segment in segments]
    normalized = [fragment for fragment in normalized if fragment]
    if len(normalized) < 4:
        return 0
    counts = Counter(normalized)
    repeated = sum(count for fragment, count in counts.items() if count > 1)
    return repeated / len(normalized)


def _normalize_fragment(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _segment_text(segment: dict[str, Any]) -> str:
    text = segment.get("text")
    return text if isinstance(text, str) else ""


def _metadata_text(metadata: dict[str, Any]) -> str:
    values: list[str] = []
    for value in metadata.values():
        values.extend(_text_values(value))
    return " ".join(values)


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_text_values(item))
        return values
    if isinstance(value, dict):
        values: list[str] = []
        for item in value.values():
            values.extend(_text_values(item))
        return values
    return []


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
