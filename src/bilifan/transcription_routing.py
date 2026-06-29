from __future__ import annotations

import re
from typing import Any


URL_TEXT_RE = re.compile(r"https?://\S+")


def choose_whisper_route(
    metadata: dict[str, Any],
    *,
    language: str = "auto",
) -> dict[str, Any]:
    if language == "zh":
        return _route(
            "turbo",
            "zh",
            confidence="manual",
            reason="manual_language_zh",
            signals=["manual_language_zh"],
        )
    if language == "en":
        return _route(
            "small.en",
            "en",
            confidence="manual",
            reason="manual_language_en",
            signals=["manual_language_en"],
        )
    if language != "auto":
        raise ValueError(f"Unsupported Whisper language: {language}")

    title_text = _metadata_text(metadata, ("title",))
    descriptive_text = _metadata_text(metadata, ("part_title", "description"))
    tags_text = _metadata_text(metadata, ("tags",))
    subtitle_text = _subtitle_metadata_text(metadata.get("subtitles"))
    descriptive_signal_text = _strip_urls(descriptive_text)
    support_text = " ".join(
        text
        for text in (
            descriptive_signal_text,
            tags_text,
            subtitle_text,
        )
        if text
    )
    combined_text = " ".join(text for text in (title_text, support_text) if text)
    signals = _signals(
        title_text=title_text,
        descriptive_text=descriptive_text,
        descriptive_signal_text=descriptive_signal_text,
        support_text=support_text,
        combined_text=combined_text,
    )

    if _explicit_english_audio_signal(combined_text):
        return _route(
            "small.en",
            "en",
            confidence="high",
            reason="explicit_english_audio_signal",
            signals=[*signals, "explicit_english_audio_signal"],
        )
    if _contains_cjk(title_text):
        if descriptive_signal_text and _english_signal(descriptive_signal_text):
            return _route(
                "small.en",
                "en",
                confidence="medium",
                reason="cjk_title_with_english_heavy_description",
                signals=[*signals, "description_english_heavy"],
            )
        return _route(
            "turbo",
            "zh",
            confidence="high",
            reason="cjk_title_without_explicit_english_audio",
            signals=signals,
        )
    if support_text and _english_signal(support_text):
        return _route(
            "small.en",
            "en",
            confidence="medium",
            reason="english_heavy_metadata",
            signals=[*signals, "metadata_english_heavy"],
        )
    if (
        combined_text
        and not _contains_cjk(combined_text)
        and _ascii_letter_ratio(combined_text) >= 0.8
    ):
        return _route(
            "small.en",
            "en",
            confidence="medium",
            reason="ascii_title_and_metadata",
            signals=[*signals, "ascii_metadata_dominant"],
        )
    return _route(
        "turbo",
        "zh",
        confidence="low",
        reason="default_chinese_route",
        signals=signals,
    )


def alternate_whisper_route(route: dict[str, Any]) -> dict[str, str]:
    selected_language = _first_text(route.get("selected_language"))
    selected_model = _first_text(route.get("selected_model"))
    if selected_language == "en" or selected_model == "small.en":
        return {"model": "turbo", "language": "zh"}
    return {"model": "small.en", "language": "en"}


def _route(
    model: str,
    language: str,
    *,
    confidence: str,
    reason: str,
    signals: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "selected_model": model,
        "selected_language": language,
        "confidence": confidence,
        "reason": reason,
        "signals": _unique(signals),
        "alternates": [
            alternate_whisper_route(
                {"selected_model": model, "selected_language": language}
            )
        ],
    }


def _signals(
    *,
    title_text: str,
    descriptive_text: str,
    descriptive_signal_text: str,
    support_text: str,
    combined_text: str,
) -> list[str]:
    signals: list[str] = []
    if _contains_cjk(title_text):
        signals.append("title_has_cjk")
    if descriptive_text != descriptive_signal_text:
        signals.append("description_urls_ignored")
    if support_text and _english_signal(support_text):
        signals.append("support_text_english_heavy")
    if (
        combined_text
        and not _contains_cjk(combined_text)
        and _ascii_letter_ratio(combined_text) >= 0.8
    ):
        signals.append("combined_text_ascii_dominant")
    if not signals:
        signals.append("metadata_low_signal")
    return signals


def _metadata_text(metadata: dict[str, Any], keys: tuple[str, ...]) -> str:
    parts: list[str] = []
    for key in keys:
        parts.extend(_text_values(metadata.get(key)))
    return " ".join(part for part in parts if part)


def _subtitle_metadata_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for subtitle in value:
        if not isinstance(subtitle, dict):
            continue
        for key in ("language", "name", "lan", "lan_doc", "ext"):
            parts.extend(_text_values(subtitle.get(key)))
    return " ".join(part for part in parts if part)


def _text_values(value: Any) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (int, float)):
        return [str(value)]
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


def _first_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_values: list[str] = []
    for value in values:
        if value and value not in seen:
            unique_values.append(value)
            seen.add(value)
    return unique_values
