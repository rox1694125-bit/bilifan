from __future__ import annotations

from typing import Any

from .diagnostics import redact_text


SINGLE_PASS_MAX_SECONDS = 45 * 60
LONG_VIDEO_CONFIRM_SECONDS = 90 * 60
DEFAULT_LONG_VIDEO_LIMIT_SECONDS = 180 * 60
MIN_CHUNK_SECONDS = 30 * 60
MAX_CHUNK_SECONDS = 45 * 60
SUMMARY_INPUT_TOKEN_BUDGET = 24_000


class ChunkingError(RuntimeError):
    """Raised when transcript chunks cannot be produced."""

    def __init__(self, message: str) -> None:
        self.sanitized_message = redact_text(message)
        super().__init__(self.sanitized_message)


class LongVideoConfirmationRequired(ChunkingError):
    """Raised when a 90-180 minute video needs explicit user confirmation."""


def build_chunks(
    transcript: dict[str, Any],
    media: dict[str, Any],
    *,
    allow_long_video: bool = False,
    long_video_confirmed: bool = False,
    token_budget: int = SUMMARY_INPUT_TOKEN_BUDGET,
) -> dict[str, Any]:
    segments = _normalized_segments(transcript)
    if not segments:
        raise ChunkingError("Transcript contains no usable segments for chunking.")

    media_duration = _positive_float(media.get("duration_seconds"))
    transcript_duration = max(segment["end"] for segment in segments)
    planning_duration = media_duration or transcript_duration

    if planning_duration > DEFAULT_LONG_VIDEO_LIMIT_SECONDS and not allow_long_video:
        raise ChunkingError(
            "Videos longer than 180 minutes require --allow-long-video."
        )
    if (
        LONG_VIDEO_CONFIRM_SECONDS <= planning_duration <= DEFAULT_LONG_VIDEO_LIMIT_SECONDS
        and not long_video_confirmed
    ):
        raise LongVideoConfirmationRequired(
            "Videos between 90 and 180 minutes require confirmation."
        )

    target_chunk_seconds = _target_chunk_seconds(
        segments,
        transcript_duration=transcript_duration,
        token_budget=token_budget,
    )
    mode = "single_pass" if planning_duration <= SINGLE_PASS_MAX_SECONDS else "dynamic"
    chunks = (
        [_chunk_payload(1, 0, len(segments), segments)]
        if mode == "single_pass"
        else _dynamic_chunks(segments, target_chunk_seconds=target_chunk_seconds)
    )

    return {
        "strategy": {
            "mode": mode,
            "single_pass_max_seconds": SINGLE_PASS_MAX_SECONDS,
            "min_chunk_seconds": MIN_CHUNK_SECONDS,
            "max_chunk_seconds": MAX_CHUNK_SECONDS,
            "target_chunk_seconds": (
                None if mode == "single_pass" else target_chunk_seconds
            ),
            "token_budget": token_budget,
            "long_video_confirmed": long_video_confirmed or allow_long_video,
            "allow_long_video": allow_long_video,
        },
        "media_duration_seconds": media_duration,
        "transcript_duration_seconds": transcript_duration,
        "chunk_count": len(chunks),
        "chunks": chunks,
    }


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    non_space = sum(1 for char in text if not char.isspace())
    ascii_like = max(0, non_space - cjk)
    return max(1, cjk + (ascii_like + 3) // 4)


def _normalized_segments(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = transcript.get("segments")
    if not isinstance(raw_segments, list):
        return []

    segments: list[dict[str, Any]] = []
    for index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, dict):
            continue
        start = _positive_or_zero_float(raw_segment.get("start"))
        end = _positive_float(raw_segment.get("end"))
        text = redact_text(
            _first_text(raw_segment.get("text")).strip(),
            max_length=None,
        )
        if start is None or end is None or end <= start or not text:
            continue
        segments.append(
            {
                "source_index": index,
                "start": start,
                "end": end,
                "text": text,
                "language": _first_text(raw_segment.get("language")),
                "source": _first_text(raw_segment.get("source")),
            }
        )
    return sorted(segments, key=lambda segment: (segment["start"], segment["end"]))


def _target_chunk_seconds(
    segments: list[dict[str, Any]],
    *,
    transcript_duration: float,
    token_budget: int,
) -> int:
    estimated_tokens = sum(estimate_text_tokens(segment["text"]) for segment in segments)
    if transcript_duration <= 0 or estimated_tokens <= 0:
        return MAX_CHUNK_SECONDS

    tokens_per_second = estimated_tokens / transcript_duration
    target = int(token_budget / tokens_per_second) if tokens_per_second > 0 else MAX_CHUNK_SECONDS
    return max(MIN_CHUNK_SECONDS, min(MAX_CHUNK_SECONDS, target))


def _dynamic_chunks(
    segments: list[dict[str, Any]],
    *,
    target_chunk_seconds: int,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    start_index = 0
    chunk_start = segments[0]["start"]

    for index, segment in enumerate(segments):
        if index == start_index:
            continue
        if segment["end"] - chunk_start <= target_chunk_seconds:
            continue
        chunks.append(_chunk_payload(len(chunks) + 1, start_index, index, segments))
        start_index = index
        chunk_start = segment["start"]

    chunks.append(_chunk_payload(len(chunks) + 1, start_index, len(segments), segments))
    return chunks


def _chunk_payload(
    chunk_index: int,
    start_index: int,
    end_index: int,
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = segments[start_index:end_index]
    text = "\n".join(segment["text"] for segment in selected)
    return {
        "chunk_index": chunk_index,
        "start": selected[0]["start"],
        "end": selected[-1]["end"],
        "duration_seconds": selected[-1]["end"] - selected[0]["start"],
        "segment_start_index": selected[0]["source_index"],
        "segment_end_index": selected[-1]["source_index"],
        "segment_count": len(selected),
        "estimated_tokens": estimate_text_tokens(text),
        "text": text,
    }


def _positive_float(value: Any) -> float | None:
    parsed = _float_value(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def _positive_or_zero_float(value: Any) -> float | None:
    parsed = _float_value(value)
    if parsed is None or parsed < 0:
        return None
    return parsed


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


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return ""
