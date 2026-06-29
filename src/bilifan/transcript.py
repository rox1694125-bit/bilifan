from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from .diagnostics import redact_text
from .sources.youtube import parse_youtube_vtt
from .transcript_quality import check_transcript_quality
from .transcription_routing import alternate_whisper_route, choose_whisper_route


SUBTITLE_TIMEOUT_SECONDS = 60
MAX_SUBTITLE_BYTES = 20 * 1024 * 1024
MIN_TRANSCRIPT_TOLERANCE_SECONDS = 10
TRANSCRIPT_TOLERANCE_RATIO = 0.05
MLX_WHISPER_TURBO_MODEL = "mlx-community/whisper-large-v3-turbo"
URL_TEXT_RE = re.compile(r"https?://\S+")


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
    language: str = "auto",
    transcriber: str = "auto",
    subtitle_fetcher=None,
    whisper_transcriber=None,
    mlx_whisper_transcriber=None,
) -> dict[str, Any]:
    if transcriber not in {"auto", "whisper", "subtitles"}:
        raise TranscriptError(f"Unsupported transcriber: {transcriber}")
    if language not in {"auto", "zh", "en"}:
        raise TranscriptError(f"Unsupported language: {language}")

    if not force_whisper and transcriber in {"auto", "subtitles"}:
        subtitle = _first_subtitle(metadata)
        if subtitle is not None:
            try:
                segments = _segments_from_subtitle(
                    subtitle,
                    subtitle_fetcher=subtitle_fetcher,
                )
                subtitle_source = _subtitle_source(metadata, subtitle)
                transcript = _transcript_payload(
                    source=subtitle_source,
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

    routing_decision = choose_whisper_route(metadata, language=language)
    model_name = str(routing_decision["selected_model"])
    whisper_language = str(routing_decision["selected_language"])
    audio_path = run_dir / _first_text(media.get("audio_path"))
    if not audio_path.is_file():
        raise TranscriptError(
            "Audio file for Whisper is missing: "
            f"{_first_text(media.get('audio_path'))}"
        )

    first_attempt = _build_whisper_attempt(
        audio_path,
        model_name=model_name,
        language=whisper_language,
        metadata=metadata,
        media=media,
        whisper_transcriber=whisper_transcriber,
        mlx_whisper_transcriber=mlx_whisper_transcriber,
    )
    attempts = [first_attempt]
    if _should_retry_whisper_attempt(first_attempt, language):
        alternate = alternate_whisper_route(routing_decision)
        attempts.append(
            _build_whisper_attempt(
                audio_path,
                model_name=alternate["model"],
                language=alternate["language"],
                metadata=metadata,
                media=media,
                whisper_transcriber=whisper_transcriber,
                mlx_whisper_transcriber=mlx_whisper_transcriber,
            )
        )

    selected_attempt = _select_whisper_attempt(attempts)
    for attempt in attempts:
        attempt["selected"] = attempt is selected_attempt

    transcript = _transcript_payload(
        source="whisper",
        language=str(selected_attempt["language"]),
        model=str(selected_attempt["model"]),
        backend=str(selected_attempt["backend"]),
        segments=selected_attempt["segments"],
        media=media,
        routing_decision=routing_decision,
        transcript_quality_check=selected_attempt["quality_check"],
        transcription_attempts=[_attempt_summary(attempt) for attempt in attempts],
        segments_are_normalized=True,
    )
    _raise_if_incomplete(transcript)
    return transcript


def choose_whisper_model(
    metadata: dict[str, Any],
    *,
    language: str = "auto",
) -> tuple[str, str]:
    route = choose_whisper_route(metadata, language=language)
    return str(route["selected_model"]), str(route["selected_language"])


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


def transcribe_with_mlx_whisper(
    audio_path: Path,
    *,
    model_name: str,
    language: str,
) -> list[dict[str, Any]]:
    try:
        import mlx_whisper
    except Exception as exc:
        raise TranscriptError("mlx-whisper is not installed or unavailable.") from exc

    try:
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=_mlx_whisper_model_path(model_name),
            language=language,
            verbose=False,
        )
    except Exception as exc:
        raise TranscriptError(f"MLX Whisper transcription failed: {exc}") from exc

    raw_segments = result.get("segments") if isinstance(result, dict) else None
    if not isinstance(raw_segments, list):
        raise TranscriptError("MLX Whisper returned invalid transcript segments.")
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
    if _first_text(subtitle.get("ext")).lower() == "vtt":
        try:
            return parse_youtube_vtt(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise TranscriptError("YouTube subtitle returned invalid VTT.") from exc
    return parse_bilibili_subtitle_json(raw)


def _subtitle_source(metadata: dict[str, Any], subtitle: dict[str, Any]) -> str:
    if (
        _first_text(metadata.get("platform")) == "youtube"
        or _first_text(subtitle.get("ext")).lower() == "vtt"
    ):
        return "youtube-subtitle"
    return "bilibili-subtitle"


def _transcript_payload(
    *,
    source: str,
    language: str,
    model: str | None,
    segments: list[dict[str, Any]],
    media: dict[str, Any],
    backend: str | None = None,
    routing_decision: dict[str, Any] | None = None,
    transcript_quality_check: dict[str, Any] | None = None,
    transcription_attempts: list[dict[str, Any]] | None = None,
    segments_are_normalized: bool = False,
) -> dict[str, Any]:
    if segments_are_normalized:
        normalized_segments = segments
    else:
        normalized_segments = _normalize_segments(
            segments,
            language=language,
            source=source,
        )
    payload = {
        "source": source,
        "language": language,
        "model": model,
        "segments": normalized_segments,
        "transcript_check": check_transcript_complete(
            normalized_segments,
            audio_seconds=_float_value(media.get("duration_seconds")),
        ),
    }
    if backend:
        payload["backend"] = backend
    if routing_decision is not None:
        payload["routing_decision"] = routing_decision
    if transcript_quality_check is not None:
        payload["transcript_quality_check"] = transcript_quality_check
    if transcription_attempts is not None:
        payload["transcription_attempts"] = transcription_attempts
    return payload


def _build_whisper_attempt(
    audio_path: Path,
    *,
    model_name: str,
    language: str,
    metadata: dict[str, Any],
    media: dict[str, Any],
    whisper_transcriber,
    mlx_whisper_transcriber,
) -> dict[str, Any]:
    raw_segments, backend = _transcribe_with_preferred_whisper(
        audio_path,
        model_name=model_name,
        language=language,
        whisper_transcriber=whisper_transcriber,
        mlx_whisper_transcriber=mlx_whisper_transcriber,
    )
    normalized_segments = _normalize_segments(
        raw_segments,
        language=language,
        source="whisper",
    )
    quality_check = check_transcript_quality(
        normalized_segments,
        expected_language=language,
        metadata=metadata,
        audio_seconds=_float_value(media.get("duration_seconds")),
    )
    return {
        "model": model_name,
        "language": language,
        "backend": backend,
        "raw_segments": raw_segments,
        "segments": normalized_segments,
        "quality_check": quality_check,
        "selected": False,
    }


def _should_retry_whisper_attempt(
    attempt: dict[str, Any],
    requested_language: str,
) -> bool:
    status = str(attempt["quality_check"]["status"])
    if requested_language == "auto":
        return status in {"suspect_wrong_route", "unusable"}
    return status == "unusable"


def _quality_rank(status: str) -> int:
    return {
        "unusable": 0,
        "suspect_wrong_route": 1,
        "low_confidence": 2,
        "ok": 3,
    }.get(status, -1)


def _select_whisper_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        attempts,
        key=lambda attempt: _quality_rank(str(attempt["quality_check"]["status"])),
    )


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": attempt["model"],
        "language": attempt["language"],
        "backend": attempt["backend"],
        "quality_status": attempt["quality_check"]["status"],
        "selected": attempt["selected"],
    }


def _transcribe_with_preferred_whisper(
    audio_path: Path,
    *,
    model_name: str,
    language: str,
    whisper_transcriber,
    mlx_whisper_transcriber,
) -> tuple[list[dict[str, Any]], str]:
    openai_transcriber = whisper_transcriber or transcribe_with_whisper
    if whisper_transcriber is not None and mlx_whisper_transcriber is None:
        return (
            openai_transcriber(audio_path, model_name=model_name, language=language),
            "openai-whisper",
        )

    if _prefers_mlx_whisper(model_name):
        mlx_transcriber = mlx_whisper_transcriber or transcribe_with_mlx_whisper
        try:
            return (
                mlx_transcriber(audio_path, model_name=model_name, language=language),
                "mlx-whisper",
            )
        except TranscriptError:
            pass

    return (
        openai_transcriber(audio_path, model_name=model_name, language=language),
        "openai-whisper",
    )


def _prefers_mlx_whisper(model_name: str) -> bool:
    return model_name in {"turbo", "large-v3-turbo"}


def _mlx_whisper_model_path(model_name: str) -> str:
    if _prefers_mlx_whisper(model_name):
        return MLX_WHISPER_TURBO_MODEL
    return model_name


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
    if _first_text(metadata.get("platform")) == "youtube":
        for subtitle in subtitles:
            if (
                isinstance(subtitle, dict)
                and _first_text(subtitle.get("url"))
                and _first_text(subtitle.get("ext")).lower() == "vtt"
            ):
                return subtitle
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


def _english_signal(text: str) -> bool:
    return _ascii_letter_count(text) >= 20 and _ascii_letter_ratio(text) >= 0.75


def _strip_urls(text: str) -> str:
    return URL_TEXT_RE.sub(" ", text)


def _explicit_english_audio_signal(text: str) -> bool:
    lowered = text.lower()
    return any(
        signal in lowered
        for signal in (
            "英语原声",
            "英文原声",
            "英文演讲",
            "英文访谈",
            "english audio",
            "spoken in english",
            "andrew ng",
            "吴恩达",
        )
    )


def _ascii_letter_ratio(text: str) -> float:
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0
    ascii_letters = [char for char in letters if char.isascii()]
    return len(ascii_letters) / len(letters)


def _ascii_letter_count(text: str) -> int:
    return sum(1 for char in text if char.isascii() and char.isalpha())


def _metadata_text(metadata: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts: list[str] = []
    for key in keys:
        parts.extend(_text_values(metadata.get(key)))
    return " ".join(parts)


def _subtitle_metadata_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for subtitle in value:
        if not isinstance(subtitle, dict):
            continue
        for key in ("language", "name", "lan", "lan_doc", "ext"):
            parts.extend(_text_values(subtitle.get(key)))
    return " ".join(parts)


def _text_values(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, int | float):
        return [str(value)]
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            parts.extend(_text_values(item))
        return parts
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_text_values(item))
        return parts
    return []


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
