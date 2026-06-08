from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .diagnostics import redact_text


SUBTITLE_TIMEOUT_SECONDS = 60
MAX_SUBTITLE_BYTES = 20 * 1024 * 1024
MIN_TRANSCRIPT_TOLERANCE_SECONDS = 10
TRANSCRIPT_TOLERANCE_RATIO = 0.05


class TranscriptError(RuntimeError):
    """Raised when transcript generation cannot produce a complete transcript."""

    def __init__(
        self,
        message: str,
        *,
        transcript_check: dict[str, Any] | None = None,
    ) -> None:
        self.sanitized_message = redact_text(message)
        self.transcript_check = transcript_check
        super().__init__(self.sanitized_message)


def build_transcript(
    metadata: dict[str, Any],
    media: dict[str, Any],
    run_dir: Path,
    *,
    force_whisper: bool = False,
    transcriber: str = "auto",
    subtitle_fetcher=None,
    whisper_transcriber=None,
) -> dict[str, Any]:
    if transcriber not in {"auto", "whisper", "subtitles"}:
        raise TranscriptError(f"Unsupported transcriber: {transcriber}")

    if not force_whisper and transcriber in {"auto", "subtitles"}:
        subtitle = _first_subtitle(metadata)
        if subtitle is not None:
            try:
                segments = _segments_from_subtitle(
                    subtitle,
                    subtitle_fetcher=subtitle_fetcher,
                )
                transcript = _transcript_payload(
                    source="bilibili-subtitle",
                    language=_first_text(subtitle.get("language"), "unknown"),
                    model=None,
                    segments=segments,
                    media=media,
                )
                _raise_if_incomplete(transcript)
                return transcript
            except TranscriptError:
                if transcriber == "subtitles":
                    raise
        if transcriber == "subtitles":
            raise TranscriptError("No usable Bilibili subtitle was found.")

    model_name, language = choose_whisper_model(metadata)
    audio_path = run_dir / _first_text(media.get("audio_path"))
    if not audio_path.is_file():
        raise TranscriptError(
            "Audio file for Whisper is missing: "
            f"{_first_text(media.get('audio_path'))}"
        )

    transcribe = whisper_transcriber or transcribe_with_whisper
    segments = transcribe(audio_path, model_name=model_name, language=language)
    transcript = _transcript_payload(
        source="whisper",
        language=language,
        model=model_name,
        segments=segments,
        media=media,
    )
    _raise_if_incomplete(transcript)
    return transcript


def choose_whisper_model(metadata: dict[str, Any]) -> tuple[str, str]:
    text = " ".join(
        _first_text(metadata.get(key)) for key in ("title", "part_title", "description")
    )
    if text and not _contains_cjk(text) and _ascii_letter_ratio(text) >= 0.8:
        return "small.en", "en"
    return "turbo", "zh"


def transcribe_with_whisper(
    audio_path: Path,
    *,
    model_name: str,
    language: str,
) -> list[dict[str, Any]]:
    try:
        import whisper
    except Exception as exc:
        raise TranscriptError("openai-whisper is not installed.") from exc

    try:
        model = whisper.load_model(model_name)
        result = model.transcribe(str(audio_path), language=language)
    except Exception as exc:
        raise TranscriptError(f"Whisper transcription failed: {exc}") from exc

    raw_segments = result.get("segments") if isinstance(result, dict) else None
    if not isinstance(raw_segments, list):
        raise TranscriptError("Whisper returned invalid transcript segments.")
    return raw_segments


def fetch_subtitle_bytes(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=SUBTITLE_TIMEOUT_SECONDS) as response:
            data = response.read(MAX_SUBTITLE_BYTES + 1)
    except (OSError, URLError, ValueError) as exc:
        raise TranscriptError(f"Bilibili subtitle download failed: {exc}") from exc

    if len(data) > MAX_SUBTITLE_BYTES:
        raise TranscriptError("Bilibili subtitle response was too large.")
    return data


def parse_bilibili_subtitle_json(raw: bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TranscriptError("Bilibili subtitle returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise TranscriptError("Bilibili subtitle returned invalid JSON object.")

    body = payload.get("body")
    if not isinstance(body, list):
        raise TranscriptError("Bilibili subtitle JSON did not contain body segments.")

    segments: list[dict[str, Any]] = []
    for item in body:
        if not isinstance(item, dict):
            continue
        text = _first_text(item.get("content"))
        if not text:
            continue
        start = _float_value(item.get("from"))
        end = _float_value(item.get("to"))
        if start is None or end is None or end <= start:
            continue
        segments.append({"start": start, "end": end, "text": text})
    if not segments:
        raise TranscriptError("Bilibili subtitle JSON contained no usable segments.")
    return segments


def check_transcript_complete(
    segments: list[dict[str, Any]],
    *,
    audio_seconds: int | float | None,
) -> dict[str, Any]:
    if not segments:
        return {
            "status": "empty",
            "audio_seconds": audio_seconds,
            "last_segment_end": None,
            "difference_seconds": None,
            "tolerance_seconds": MIN_TRANSCRIPT_TOLERANCE_SECONDS,
            "segment_count": 0,
        }

    last_segment_end = max(float(segment["end"]) for segment in segments)
    if audio_seconds is None or audio_seconds <= 0:
        return {
            "status": "skipped",
            "audio_seconds": audio_seconds,
            "last_segment_end": last_segment_end,
            "difference_seconds": None,
            "tolerance_seconds": MIN_TRANSCRIPT_TOLERANCE_SECONDS,
            "segment_count": len(segments),
        }

    tolerance = max(
        MIN_TRANSCRIPT_TOLERANCE_SECONDS,
        float(audio_seconds) * TRANSCRIPT_TOLERANCE_RATIO,
    )
    difference = abs(float(audio_seconds) - last_segment_end)
    return {
        "status": "ok" if difference <= tolerance else "transcript_incomplete",
        "audio_seconds": audio_seconds,
        "last_segment_end": last_segment_end,
        "difference_seconds": difference,
        "tolerance_seconds": tolerance,
        "segment_count": len(segments),
    }


def _segments_from_subtitle(
    subtitle: dict[str, Any],
    *,
    subtitle_fetcher,
) -> list[dict[str, Any]]:
    url = _first_text(subtitle.get("url"))
    if not url:
        raise TranscriptError("Bilibili subtitle did not include a URL.")
    fetcher = subtitle_fetcher or fetch_subtitle_bytes
    raw = fetcher(url)
    return parse_bilibili_subtitle_json(raw)


def _transcript_payload(
    *,
    source: str,
    language: str,
    model: str | None,
    segments: list[dict[str, Any]],
    media: dict[str, Any],
) -> dict[str, Any]:
    normalized_segments = _normalize_segments(
        segments,
        language=language,
        source=source,
    )
    return {
        "source": source,
        "language": language,
        "model": model,
        "segments": normalized_segments,
        "transcript_check": check_transcript_complete(
            normalized_segments,
            audio_seconds=_float_value(media.get("duration_seconds")),
        ),
    }


def _raise_if_incomplete(transcript: dict[str, Any]) -> None:
    transcript_check = transcript["transcript_check"]
    if transcript_check["status"] == "empty":
        raise TranscriptError(
            "transcript appears incomplete.",
            transcript_check=transcript_check,
        )


def _first_subtitle(metadata: dict[str, Any]) -> dict[str, Any] | None:
    subtitles = metadata.get("subtitles")
    if not isinstance(subtitles, list):
        return None
    for subtitle in subtitles:
        if isinstance(subtitle, dict) and _first_text(subtitle.get("url")):
            return subtitle
    return None


def _normalize_segments(
    segments: list[dict[str, Any]],
    *,
    language: str,
    source: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        start = _float_value(segment.get("start"))
        end = _float_value(segment.get("end"))
        text = redact_text(_first_text(segment.get("text")).strip(), max_length=None)
        if start is None or end is None or end <= start or not text:
            continue
        normalized.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "language": language,
                "source": source,
            }
        )
    return normalized


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _ascii_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0
    ascii_letters = [char for char in letters if char.isascii()]
    return len(ascii_letters) / len(letters)


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
