# Bilifan Transcription Routing Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add auditable Whisper routing, deterministic transcript quality checks, and one-shot auto-correction so Bilifan does not silently publish transcripts produced with the wrong language/model route.

**Architecture:** Split routing and quality logic into focused modules, then keep `src/bilifan/transcript.py` as the orchestration layer that chooses a route, builds one or two Whisper attempts, and publishes only the selected transcript. Pipeline, queue, and UI consume structured transcript metadata and warnings instead of re-inferencing the state from a plain label.

**Tech Stack:** Python 3.12, pytest, FastAPI/TestClient, local JavaScript UI harness in `tests/test_web_ui.py`, existing Bilifan pipeline and queue modules.

---

## Design Source

- Spec: `docs/superpowers/specs/2026-06-29-bilifan-transcription-routing-guardrails-design.md`
- Terms: `CONTEXT.md`
- Existing bugfix: `4397122 fix: keep Chinese Whisper selection with reference links`

## File Structure

- Create `src/bilifan/transcription_routing.py`
  - Owns deterministic metadata-to-route decisions.
  - Returns structured `routing_decision` dictionaries.
  - Keeps `zh -> turbo`, `en -> small.en`, and alternate route selection.
- Create `src/bilifan/transcript_quality.py`
  - Owns deterministic post-Whisper quality metrics and status classification.
  - Has no media download, Whisper, UI, queue, or Feishu dependencies.
- Modify `src/bilifan/transcript.py`
  - Keeps subtitle-first behavior.
  - Re-exports `choose_whisper_model()` for existing callers/tests.
  - Stores `routing_decision`, `transcript_quality_check`, and `transcription_attempts` in Whisper transcripts.
  - Performs one alternate Whisper attempt when quality indicates wrong route.
- Modify `src/bilifan/pipeline.py`
  - Propagates transcript quality warnings into diagnostics and `PipelineResult.warnings`.
- Modify `src/bilifan/web/run_info.py`
  - Formats transcript source labels with correction/review suffixes.
- Modify `src/bilifan/web/jobs.py` and `src/bilifan/web/queue.py`
  - Persist and expose warning metadata already produced by `PipelineResult`.
  - Do not create new queue terminal statuses.
- Modify `src/bilifan/web/ui.py`
  - Show corrected/review labels in Task Center/history through `transcript_source_label` and warnings.
- Tests:
  - Add `tests/test_transcription_routing.py`.
  - Add `tests/test_transcript_quality.py`.
  - Extend `tests/test_transcript.py`, `tests/test_pipeline.py`, `tests/test_web_jobs.py`, `tests/test_web_ui.py`, and `tests/test_queue.py`.

## Execution Notes

- Use TDD for each task: write the failing test first, run it, then implement.
- Keep each task as a separate commit.
- Do not change Feishu/Hermes runtime behavior in Tasks 1-3.
- Current Hermes intake plugin only sends the immediate intake acknowledgement. This plan exposes completion-warning data through Bilifan queue/API; a separate Feishu completion-notification worker can consume it later.
- For `language=auto`, auto-correct on `suspect_wrong_route` or `unusable`.
- For explicit `language=zh` or `language=en`, keep the user-selected route for `low_confidence`; retry only when the first attempt is `unusable`.

---

### Task 1: Add Auditable Whisper Routing

**Files:**
- Create: `src/bilifan/transcription_routing.py`
- Modify: `src/bilifan/transcript.py`
- Create: `tests/test_transcription_routing.py`
- Modify: `tests/test_transcript.py`

- [ ] **Step 1: Write failing routing tests**

Create `tests/test_transcription_routing.py`:

```python
import pytest

from bilifan.transcription_routing import (
    alternate_whisper_route,
    choose_whisper_route,
)


def test_choose_route_records_chinese_decision_with_ignored_reference_urls():
    route = choose_whisper_route(
        {
            "title": "给傻子的Git教程",
            "part_title": "给傻子的Git教程",
            "description": (
                "Git官网: https://git-scm.com/\n"
                "Git第一步配置: https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup"
            ),
            "tags": ["软件", "学习", "github", "git"],
            "subtitles": [],
        }
    )

    assert route["selected_model"] == "turbo"
    assert route["selected_language"] == "zh"
    assert route["confidence"] == "high"
    assert route["reason"] == "cjk_title_without_explicit_english_audio"
    assert "title_has_cjk" in route["signals"]
    assert "description_urls_ignored" in route["signals"]
    assert route["alternates"] == [{"model": "small.en", "language": "en"}]


def test_choose_route_records_explicit_english_audio_signal():
    route = choose_whisper_route(
        {
            "title": "Andrew Ng 访谈精华",
            "part_title": "英语原声完整版",
            "description": "课程讨论和创业建议。",
        }
    )

    assert route["selected_model"] == "small.en"
    assert route["selected_language"] == "en"
    assert route["confidence"] == "high"
    assert route["reason"] == "explicit_english_audio_signal"
    assert "explicit_english_audio_signal" in route["signals"]


def test_choose_route_records_manual_language_choice():
    route = choose_whisper_route(
        {"title": "How to build a small app", "description": "A short tutorial"},
        language="zh",
    )

    assert route["selected_model"] == "turbo"
    assert route["selected_language"] == "zh"
    assert route["confidence"] == "manual"
    assert route["reason"] == "manual_language_zh"
    assert route["signals"] == ["manual_language_zh"]


def test_choose_route_rejects_unsupported_language():
    with pytest.raises(ValueError, match="Unsupported Whisper language"):
        choose_whisper_route({"title": "中文标题"}, language="ja")


def test_alternate_whisper_route_switches_supported_routes():
    assert alternate_whisper_route({"selected_model": "small.en", "selected_language": "en"}) == {
        "model": "turbo",
        "language": "zh",
    }
    assert alternate_whisper_route({"selected_model": "turbo", "selected_language": "zh"}) == {
        "model": "small.en",
        "language": "en",
    }
```

Extend `tests/test_transcript.py` with this compatibility test:

```python
def test_choose_whisper_model_wraps_structured_route():
    metadata = {"title": "给傻子的Git教程", "description": "Git官网: https://git-scm.com/"}

    assert choose_whisper_model(metadata) == ("turbo", "zh")
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_transcription_routing.py tests/test_transcript.py::test_choose_whisper_model_wraps_structured_route -q
```

Expected:

```text
ERROR tests/test_transcription_routing.py
```

or failure caused by missing `bilifan.transcription_routing`.

- [ ] **Step 3: Add routing module**

Create `src/bilifan/transcription_routing.py`:

```python
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
        return _route("turbo", "zh", confidence="manual", reason="manual_language_zh", signals=["manual_language_zh"])
    if language == "en":
        return _route("small.en", "en", confidence="manual", reason="manual_language_en", signals=["manual_language_en"])
    if language != "auto":
        raise ValueError(f"Unsupported Whisper language: {language}")

    title_text = _metadata_text(metadata, ("title",))
    descriptive_text = _metadata_text(metadata, ("part_title", "description"))
    tags_text = _metadata_text(metadata, ("tags",))
    subtitle_text = _subtitle_metadata_text(metadata.get("subtitles"))
    descriptive_signal_text = _strip_urls(descriptive_text)
    support_text = " ".join(
        text for text in (descriptive_signal_text, tags_text, subtitle_text) if text
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
    if combined_text and not _contains_cjk(combined_text) and _ascii_letter_ratio(combined_text) >= 0.8:
        return _route(
            "small.en",
            "en",
            confidence="medium",
            reason="ascii_title_and_metadata",
            signals=[*signals, "ascii_metadata_dominant"],
        )
    return _route("turbo", "zh", confidence="low", reason="default_chinese_route", signals=signals)


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
        "alternates": [alternate_whisper_route({"selected_model": model, "selected_language": language})],
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
    if combined_text and not _contains_cjk(combined_text) and _ascii_letter_ratio(combined_text) >= 0.8:
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
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
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
```

- [ ] **Step 4: Wire `choose_whisper_model()` to structured routing**

Modify `src/bilifan/transcript.py` imports:

```python
from .transcription_routing import choose_whisper_route
```

Replace the body of `choose_whisper_model()` with:

```python
def choose_whisper_model(
    metadata: dict[str, Any],
    *,
    language: str = "auto",
) -> tuple[str, str]:
    route = choose_whisper_route(metadata, language=language)
    return str(route["selected_model"]), str(route["selected_language"])
```

Do not remove the old helper functions from `src/bilifan/transcript.py` in this task unless they become unused and tests pass. Removing them can be done mechanically after Task 1 passes.

- [ ] **Step 5: Run routing tests**

Run:

```bash
uv run --extra dev pytest tests/test_transcription_routing.py tests/test_transcript.py -q
```

Expected:

```text
24 passed
```

The exact count may be higher if more transcript tests exist; all selected tests must pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add src/bilifan/transcription_routing.py src/bilifan/transcript.py tests/test_transcription_routing.py tests/test_transcript.py
git commit -m "feat: record auditable whisper routing decisions"
```

---

### Task 2: Add Deterministic Transcript Quality Check

**Files:**
- Create: `src/bilifan/transcript_quality.py`
- Create: `tests/test_transcript_quality.py`

- [ ] **Step 1: Write failing quality tests**

Create `tests/test_transcript_quality.py`:

```python
from bilifan.transcript_quality import check_transcript_quality


def test_quality_check_accepts_chinese_transcript_for_chinese_route():
    result = check_transcript_quality(
        [{"start": 0, "end": 8, "text": "嗨 这里是 Alex 今天我们讲 Git 的基本概念和常用命令"}],
        expected_language="zh",
        metadata={"title": "给傻子的Git教程"},
        audio_seconds=8,
    )

    assert result["status"] == "ok"
    assert result["observed_language"] == "zh"
    assert result["metrics"]["cjk_ratio"] > 0.3


def test_quality_check_flags_english_output_for_expected_chinese():
    result = check_transcript_quality(
        [
            {"start": 0, "end": 4, "text": "Now I do Ay Ari's text."},
            {"start": 4, "end": 8, "text": "This is not a coherent transcript for the tutorial."},
        ],
        expected_language="zh",
        metadata={"title": "给傻子的Git教程"},
        audio_seconds=8,
    )

    assert result["status"] == "suspect_wrong_route"
    assert result["observed_language"] == "en"
    assert "expected_zh_but_low_cjk" in result["warnings"]


def test_quality_check_accepts_english_transcript_for_english_route():
    result = check_transcript_quality(
        [{"start": 0, "end": 6, "text": "Today we are going to talk about evaluation pipelines."}],
        expected_language="en",
        metadata={"title": "Evaluation pipelines"},
        audio_seconds=6,
    )

    assert result["status"] == "ok"
    assert result["observed_language"] == "en"


def test_quality_check_flags_chinese_output_for_expected_english():
    result = check_transcript_quality(
        [{"start": 0, "end": 6, "text": "今天我们来聊一下评估流程和自动化测试。"}],
        expected_language="en",
        metadata={"title": "English audio interview"},
        audio_seconds=6,
    )

    assert result["status"] == "suspect_wrong_route"
    assert result["observed_language"] == "zh"
    assert "expected_en_but_low_ascii_words" in result["warnings"]


def test_quality_check_marks_repetitive_transcript_unusable():
    result = check_transcript_quality(
        [{"start": index, "end": index + 1, "text": "thank you"} for index in range(20)],
        expected_language="en",
        metadata={"title": "English talk"},
        audio_seconds=20,
    )

    assert result["status"] == "unusable"
    assert "high_repetition" in result["warnings"]
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_transcript_quality.py -q
```

Expected:

```text
ERROR tests/test_transcript_quality.py
```

or failure caused by missing `bilifan.transcript_quality`.

- [ ] **Step 3: Implement quality module**

Create `src/bilifan/transcript_quality.py`:

```python
from __future__ import annotations

import re
from collections import Counter
from typing import Any

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
        "cjk_ratio": round(cjk_count / char_count, 4) if char_count else 0,
        "ascii_word_ratio": round(ascii_word_chars / char_count, 4) if char_count else 0,
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

    if char_count < 12:
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

    return _unique(warnings)


def _status(warnings: list[str]) -> str:
    if "high_repetition" in warnings or "too_little_text" in warnings or "very_low_text_density" in warnings:
        return "unusable"
    if "expected_zh_but_low_cjk" in warnings or "expected_en_but_low_ascii_words" in warnings:
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
```

- [ ] **Step 4: Run quality tests**

Run:

```bash
uv run --extra dev pytest tests/test_transcript_quality.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit Task 2**

```bash
git add src/bilifan/transcript_quality.py tests/test_transcript_quality.py
git commit -m "feat: add transcript quality guardrails"
```

---

### Task 3: Store Routing and Quality Metadata in Whisper Transcripts

**Files:**
- Modify: `src/bilifan/transcript.py`
- Modify: `tests/test_transcript.py`

- [ ] **Step 1: Write failing transcript metadata tests**

Add to `tests/test_transcript.py`:

```python
def test_build_transcript_adds_routing_and_quality_metadata_for_whisper(tmp_path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    metadata = {"title": "中文教程", "description": "", "subtitles": []}
    media = {"duration_seconds": 4, "audio_path": "audio.mp3"}

    def fake_whisper(audio_file, *, model_name, language):
        return [{"start": 0, "end": 4, "text": "嗨 这里是中文教程 今天讲 Git"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        whisper_transcriber=fake_whisper,
        mlx_whisper_transcriber=None,
    )

    assert transcript["routing_decision"]["selected_model"] == "turbo"
    assert transcript["routing_decision"]["selected_language"] == "zh"
    assert transcript["transcript_quality_check"]["status"] == "ok"
    assert transcript["transcription_attempts"] == [
        {
            "model": "turbo",
            "language": "zh",
            "backend": "openai-whisper",
            "quality_status": "ok",
            "selected": True,
        }
    ]


def test_subtitle_transcript_does_not_add_whisper_routing_metadata(tmp_path):
    metadata = {
        "subtitles": [
            {
                "language": "zh-Hans",
                "name": "中文",
                "url": "https://example.test/subtitle.json",
                "ext": "json",
            }
        ]
    }
    media = {"duration_seconds": 3, "audio_path": "audio.mp3"}

    def fake_fetcher(url):
        return json.dumps({"body": [{"from": 0, "to": 3, "content": "字幕内容"}]}).encode("utf-8")

    transcript = build_transcript(metadata, media, tmp_path, subtitle_fetcher=fake_fetcher)

    assert "routing_decision" not in transcript
    assert "transcript_quality_check" not in transcript
    assert "transcription_attempts" not in transcript
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_transcript.py::test_build_transcript_adds_routing_and_quality_metadata_for_whisper tests/test_transcript.py::test_subtitle_transcript_does_not_add_whisper_routing_metadata -q
```

Expected:

```text
FAILED tests/test_transcript.py::test_build_transcript_adds_routing_and_quality_metadata_for_whisper
```

- [ ] **Step 3: Add quality metadata to `build_transcript()`**

Modify imports in `src/bilifan/transcript.py`:

```python
from .transcript_quality import check_transcript_quality
from .transcription_routing import choose_whisper_route
```

Replace this line:

```python
    model_name, whisper_language = choose_whisper_model(metadata, language=language)
```

with:

```python
    routing_decision = choose_whisper_route(metadata, language=language)
    model_name = str(routing_decision["selected_model"])
    whisper_language = str(routing_decision["selected_language"])
```

After `_transcribe_with_preferred_whisper(...)`, add:

```python
    quality_check = check_transcript_quality(
        _normalize_segments(segments, language=whisper_language, source="whisper"),
        expected_language=whisper_language,
        metadata=metadata,
        audio_seconds=_float_value(media.get("duration_seconds")),
    )
```

Change the `_transcript_payload(...)` call to:

```python
    transcript = _transcript_payload(
        source="whisper",
        language=whisper_language,
        model=model_name,
        backend=backend,
        segments=segments,
        media=media,
        routing_decision=routing_decision,
        transcript_quality_check=quality_check,
        transcription_attempts=[
            {
                "model": model_name,
                "language": whisper_language,
                "backend": backend,
                "quality_status": quality_check["status"],
                "selected": True,
            }
        ],
    )
```

Update `_transcript_payload()` signature:

```python
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
) -> dict[str, Any]:
```

Before `return payload`, add:

```python
    if routing_decision is not None:
        payload["routing_decision"] = routing_decision
    if transcript_quality_check is not None:
        payload["transcript_quality_check"] = transcript_quality_check
    if transcription_attempts is not None:
        payload["transcription_attempts"] = transcription_attempts
```

- [ ] **Step 4: Run transcript tests**

Run:

```bash
uv run --extra dev pytest tests/test_transcript.py tests/test_transcription_routing.py tests/test_transcript_quality.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit Task 3**

```bash
git add src/bilifan/transcript.py tests/test_transcript.py
git commit -m "feat: store whisper routing quality metadata"
```

---

### Task 4: Add One-Shot Auto-Correction Retry

**Files:**
- Modify: `src/bilifan/transcript.py`
- Modify: `tests/test_transcript.py`

- [ ] **Step 1: Write failing auto-correction tests**

Add to `tests/test_transcript.py`:

```python
def test_build_transcript_auto_retries_alternate_route_when_first_route_is_suspect(tmp_path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    metadata = {
        "title": "给傻子的Git教程",
        "description": "Git官网: https://git-scm.com/book/en/v2",
        "subtitles": [],
    }
    media = {"duration_seconds": 8, "audio_path": "audio.mp3"}
    calls = []

    def fake_whisper(audio_file, *, model_name, language):
        calls.append((model_name, language))
        if language == "zh":
            return [
                {"start": 0, "end": 4, "text": "Now I do Ay Ari's text."},
                {"start": 4, "end": 8, "text": "This is not coherent for the Chinese tutorial."},
            ]
        return [{"start": 0, "end": 8, "text": "Today we explain the core Git commands in a clean tutorial."}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        whisper_transcriber=fake_whisper,
        mlx_whisper_transcriber=None,
    )

    assert calls == [("turbo", "zh"), ("small.en", "en")]
    assert transcript["language"] == "en"
    assert transcript["model"] == "small.en"
    assert transcript["transcript_quality_check"]["status"] == "ok"
    assert transcript["transcription_attempts"] == [
        {
            "model": "turbo",
            "language": "zh",
            "backend": "openai-whisper",
            "quality_status": "suspect_wrong_route",
            "selected": False,
        },
        {
            "model": "small.en",
            "language": "en",
            "backend": "openai-whisper",
            "quality_status": "ok",
            "selected": True,
        },
    ]


def test_build_transcript_keeps_first_attempt_when_alternate_is_not_better(tmp_path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    metadata = {"title": "中文教程", "description": "", "subtitles": []}
    media = {"duration_seconds": 8, "audio_path": "audio.mp3"}

    def fake_whisper(audio_file, *, model_name, language):
        if language == "zh":
            return [{"start": 0, "end": 8, "text": "Now I do Ay Ari's text."}]
        return [{"start": 0, "end": 8, "text": "thank you"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        whisper_transcriber=fake_whisper,
        mlx_whisper_transcriber=None,
    )

    assert transcript["language"] == "zh"
    assert transcript["model"] == "turbo"
    assert transcript["transcript_quality_check"]["status"] == "suspect_wrong_route"
    assert [attempt["selected"] for attempt in transcript["transcription_attempts"]] == [True, False]


def test_build_transcript_explicit_language_retries_only_when_unusable(tmp_path):
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"fake audio")
    metadata = {"title": "Manual English", "description": "", "subtitles": []}
    media = {"duration_seconds": 20, "audio_path": "audio.mp3"}
    calls = []

    def fake_whisper(audio_file, *, model_name, language):
        calls.append((model_name, language))
        if language == "en":
            return [{"start": index, "end": index + 1, "text": "thank you"} for index in range(20)]
        return [{"start": 0, "end": 20, "text": "今天我们讲一个中文内容 并且继续解释核心概念和操作步骤"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        language="en",
        whisper_transcriber=fake_whisper,
        mlx_whisper_transcriber=None,
    )

    assert calls == [("small.en", "en"), ("turbo", "zh")]
    assert transcript["language"] == "zh"
    assert transcript["transcription_attempts"][0]["quality_status"] == "unusable"
    assert transcript["transcription_attempts"][1]["selected"] is True
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_transcript.py::test_build_transcript_auto_retries_alternate_route_when_first_route_is_suspect tests/test_transcript.py::test_build_transcript_keeps_first_attempt_when_alternate_is_not_better tests/test_transcript.py::test_build_transcript_explicit_language_retries_only_when_unusable -q
```

Expected:

```text
FAILED tests/test_transcript.py::test_build_transcript_auto_retries_alternate_route_when_first_route_is_suspect
```

- [ ] **Step 3: Add attempt helpers**

In `src/bilifan/transcript.py`, import alternate route:

```python
from .transcription_routing import alternate_whisper_route, choose_whisper_route
```

Add helper functions near `_transcribe_with_preferred_whisper()`:

```python
def _build_whisper_attempt(
    *,
    audio_path: Path,
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
    normalized_segments = _normalize_segments(raw_segments, language=language, source="whisper")
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
        "segments": raw_segments,
        "quality_check": quality_check,
        "quality_status": quality_check["status"],
        "selected": False,
    }


def _should_retry_whisper_attempt(
    attempt: dict[str, Any],
    *,
    requested_language: str,
) -> bool:
    status = str(attempt.get("quality_status") or "")
    if requested_language == "auto":
        return status in {"suspect_wrong_route", "unusable"}
    return status == "unusable"


def _quality_rank(status: str) -> int:
    return {
        "ok": 3,
        "low_confidence": 2,
        "suspect_wrong_route": 1,
        "unusable": 0,
    }.get(status, 0)


def _select_whisper_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    selected = max(attempts, key=lambda attempt: _quality_rank(str(attempt.get("quality_status") or "")))
    for attempt in attempts:
        attempt["selected"] = attempt is selected
    return selected


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": str(attempt["model"]),
        "language": str(attempt["language"]),
        "backend": str(attempt["backend"]),
        "quality_status": str(attempt["quality_status"]),
        "selected": bool(attempt["selected"]),
    }
```

- [ ] **Step 4: Use helpers in `build_transcript()`**

Replace the single Whisper transcription block in `build_transcript()` with:

```python
    attempts: list[dict[str, Any]] = []
    first_attempt = _build_whisper_attempt(
        audio_path=audio_path,
        model_name=model_name,
        language=whisper_language,
        metadata=metadata,
        media=media,
        whisper_transcriber=whisper_transcriber,
        mlx_whisper_transcriber=mlx_whisper_transcriber,
    )
    attempts.append(first_attempt)

    if _should_retry_whisper_attempt(first_attempt, requested_language=language):
        alternate = alternate_whisper_route(routing_decision)
        alternate_attempt = _build_whisper_attempt(
            audio_path=audio_path,
            model_name=alternate["model"],
            language=alternate["language"],
            metadata=metadata,
            media=media,
            whisper_transcriber=whisper_transcriber,
            mlx_whisper_transcriber=mlx_whisper_transcriber,
        )
        attempts.append(alternate_attempt)

    selected_attempt = _select_whisper_attempt(attempts)
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
    )
```

Remove the now-redundant local `segments, backend = ...` and direct quality calculation from Task 3.

- [ ] **Step 5: Run transcript retry tests**

Run:

```bash
uv run --extra dev pytest tests/test_transcript.py tests/test_transcript_quality.py tests/test_transcription_routing.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 6: Commit Task 4**

```bash
git add src/bilifan/transcript.py tests/test_transcript.py
git commit -m "feat: auto-correct suspicious whisper routes"
```

---

### Task 5: Propagate Transcript Warnings Through Pipeline and Diagnostics

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Write failing pipeline warning test**

Add to `tests/test_pipeline.py`:

```python
def test_pipeline_result_warns_when_transcript_quality_is_low_confidence(tmp_path, monkeypatch):
    def fake_build_transcript(metadata, media, run_dir, **kwargs):
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "backend": "openai-whisper",
            "segments": [{"start": 0, "end": 120, "text": "Now I do Ay Ari's text.", "language": "zh", "source": "whisper"}],
            "transcript_check": {
                "status": "ok",
                "audio_seconds": 120,
                "last_segment_end": 120,
                "difference_seconds": 0,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
            "transcript_quality_check": {
                "schema_version": 1,
                "status": "suspect_wrong_route",
                "expected_language": "zh",
                "observed_language": "en",
                "confidence": "low",
                "warnings": ["expected_zh_but_low_cjk"],
                "metrics": {},
            },
            "transcription_attempts": [
                {
                    "model": "turbo",
                    "language": "zh",
                    "backend": "openai-whisper",
                    "quality_status": "suspect_wrong_route",
                    "selected": True,
                }
            ],
        }

    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            yes_i_understand=True,
        )
    )

    diagnostics = json.loads(result.diagnostics_path.read_text(encoding="utf-8"))
    assert "transcript_quality_suspect_wrong_route" in result.warnings
    assert "transcript_quality_suspect_wrong_route" in diagnostics["warnings"]
    assert diagnostics["transcript_check"]["status"] == "ok"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_pipeline.py::test_pipeline_result_warns_when_transcript_quality_is_low_confidence -q
```

Expected:

```text
FAILED tests/test_pipeline.py::test_pipeline_result_warns_when_transcript_quality_is_low_confidence
```

- [ ] **Step 3: Add transcript warning helper**

In `src/bilifan/pipeline.py`, add near `_append_unique()` helpers:

```python
def _transcript_quality_warnings(transcript: dict[str, Any]) -> list[str]:
    quality = transcript.get("transcript_quality_check")
    if not isinstance(quality, dict):
        return []
    status = quality.get("status")
    if status not in {"low_confidence", "suspect_wrong_route", "unusable"}:
        return []
    warnings = [f"transcript_quality_{status}"]
    attempts = transcript.get("transcription_attempts")
    if isinstance(attempts, list) and len(attempts) > 1:
        selected_index = next(
            (index for index, attempt in enumerate(attempts) if isinstance(attempt, dict) and attempt.get("selected")),
            0,
        )
        if selected_index > 0:
            warnings.append("transcript_auto_corrected")
    return warnings
```

Immediately after:

```python
    _write_json(run.run_dir / "transcript.json", transcript)
    export_warnings: list[str] = []
```

replace with:

```python
    _write_json(run.run_dir / "transcript.json", transcript)
    export_warnings: list[str] = _transcript_quality_warnings(transcript)
```

- [ ] **Step 4: Run pipeline tests**

Run:

```bash
uv run --extra dev pytest tests/test_pipeline.py tests/test_transcript.py tests/test_transcript_quality.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit Task 5**

```bash
git add src/bilifan/pipeline.py tests/test_pipeline.py
git commit -m "feat: surface transcript quality warnings"
```

---

### Task 6: Show Corrected and Review Labels in Web State

**Files:**
- Modify: `src/bilifan/web/run_info.py`
- Modify: `src/bilifan/web/ui.py`
- Modify: `tests/test_web_ui.py`
- Modify: `tests/test_queue.py`

- [ ] **Step 1: Write failing label tests**

Add to `tests/test_queue.py`:

```python
def test_batch_queue_refreshes_corrected_transcript_source_label(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    run_dir = tmp_path / "outputs" / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "transcript.json").write_text(
        json.dumps(
            {
                "source": "whisper",
                "model": "turbo",
                "transcription_attempts": [
                    {"model": "small.en", "language": "en", "quality_status": "suspect_wrong_route", "selected": False},
                    {"model": "turbo", "language": "zh", "quality_status": "ok", "selected": True},
                ],
                "transcript_quality_check": {"status": "ok"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": False,
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "succeeded",
                        "request": {"url": "https://www.bilibili.com/video/BV1abcDEF12G"},
                        "run_key": run_key,
                        "stage": "render",
                        "progress": [],
                        "artifacts": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        run_jobs_inline=True,
    )

    assert manager.state()["items"][0]["transcript_source_label"] == "Whisper turbo · 已自动纠偏"
```

Extend `tests/test_web_ui.py::test_render_app_script_shows_transcript_source_labels` queue fixture:

```javascript
transcript_source_label: "Whisper turbo · 已自动纠偏",
warnings: ["transcript_auto_corrected"],
```

and change assertion:

```javascript
assert(elements["queue-list"].innerHTML.includes("逐字稿：Whisper turbo · 已自动纠偏"));
```

Add a second queue item in that test or a new UI test for review-needed:

```javascript
assert(elements["queue-list"].innerHTML.includes("逐字稿：Whisper turbo · 需复查"));
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run --extra dev pytest tests/test_queue.py::test_batch_queue_refreshes_corrected_transcript_source_label tests/test_web_ui.py::test_render_app_script_shows_transcript_source_labels -q
```

Expected:

```text
FAILED tests/test_queue.py::test_batch_queue_refreshes_corrected_transcript_source_label
```

- [ ] **Step 3: Format richer transcript source labels**

Modify `src/bilifan/web/run_info.py`:

```python
def transcript_source_label(transcript: dict[str, Any]) -> str:
    source = _text(transcript.get("source"))
    model = _text(transcript.get("model"))
    suffix = _transcript_label_suffix(transcript)
    if source == "whisper":
        return f"{f'Whisper {model}'.strip()}{suffix}".strip()
    if source == "bilibili-subtitle":
        return f"B站字幕{suffix}"
    if source == "youtube-subtitle":
        return f"YouTube 字幕{suffix}"
    if source.endswith("-subtitle"):
        return f"平台字幕{suffix}"
    return f"{source}{suffix}".strip()


def _transcript_label_suffix(transcript: dict[str, Any]) -> str:
    if _was_auto_corrected(transcript):
        return " · 已自动纠偏"
    quality = transcript.get("transcript_quality_check")
    if isinstance(quality, dict) and quality.get("status") in {"low_confidence", "suspect_wrong_route", "unusable"}:
        return " · 需复查"
    return ""


def _was_auto_corrected(transcript: dict[str, Any]) -> bool:
    attempts = transcript.get("transcription_attempts")
    if not isinstance(attempts, list) or len(attempts) < 2:
        return False
    selected_index = next(
        (
            index
            for index, attempt in enumerate(attempts)
            if isinstance(attempt, dict) and attempt.get("selected") is True
        ),
        0,
    )
    return selected_index > 0
```

No UI code should need special parsing if labels come from API state. If the UI review test fails only because fixtures were not updated, update the fixture data without adding branching UI logic.

- [ ] **Step 4: Run queue and UI tests**

Run:

```bash
uv run --extra dev pytest tests/test_queue.py tests/test_web_ui.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 5: Commit Task 6**

```bash
git add src/bilifan/web/run_info.py src/bilifan/web/ui.py tests/test_queue.py tests/test_web_ui.py
git commit -m "feat: label corrected transcript routes"
```

---

### Task 7: API State and Integration Regression

**Files:**
- Modify: `tests/test_web_jobs.py`
- Modify: `tests/test_pipeline.py`
- No production code unless tests reveal a missing propagation path.

- [ ] **Step 1: Add API-level regression tests**

Add to `tests/test_web_jobs.py`:

```python
def test_queue_endpoint_exposes_transcript_quality_warnings(tmp_path, monkeypatch):
    def fake_runner(request, *, progress_callback):
        run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
        run_dir = request.out / run_key
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps({"title": "给傻子的Git教程"}, ensure_ascii=False),
            encoding="utf-8",
        )
        (run_dir / "transcript.json").write_text(
            json.dumps(
                {
                    "source": "whisper",
                    "model": "turbo",
                    "transcript_quality_check": {"status": "suspect_wrong_route"},
                    "transcription_attempts": [
                        {"model": "turbo", "language": "zh", "quality_status": "suspect_wrong_route", "selected": True}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return PipelineResult(
            run_key=run_key,
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["diagnostics.json", "transcript.json", "report.html"],
            warnings=["transcript_quality_suspect_wrong_route"],
        )

    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G", "yes_i_understand": True},
    )
    assert response.status_code == 200

    state = client.get("/api/jobs/queue", headers=_headers()).json()
    item = state["items"][0]
    assert item["warnings"] == ["transcript_quality_suspect_wrong_route"]
    assert item["transcript_source_label"] == "Whisper turbo · 需复查"
```

- [ ] **Step 2: Run API regression**

Run:

```bash
uv run --extra dev pytest tests/test_web_jobs.py::test_queue_endpoint_exposes_transcript_quality_warnings -q
```

Expected:

```text
PASS
```

- [ ] **Step 3: Run full focused regression**

Run:

```bash
uv run --extra dev pytest tests/test_transcription_routing.py tests/test_transcript_quality.py tests/test_transcript.py tests/test_pipeline.py tests/test_queue.py tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected:

```text
all selected tests pass
```

- [ ] **Step 4: Commit Task 7**

```bash
git add tests/test_web_jobs.py tests/test_pipeline.py
git commit -m "test: cover transcript routing warnings in web state"
```

---

### Task 8: Manual Verification on Existing Bad Run

**Files:**
- No production code changes expected.
- Runtime artifacts under `outputs/BV1Hkr7YYEh8_p1/runs/2026-06-29_145519` may change during local verification. Do not commit runtime outputs.

- [ ] **Step 1: Verify current code does not regress the repaired run**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path
run = Path("outputs/BV1Hkr7YYEh8_p1/runs/2026-06-29_145519")
transcript = json.loads((run / "transcript.json").read_text(encoding="utf-8"))
print({
    "model": transcript.get("model"),
    "backend": transcript.get("backend"),
    "language": transcript.get("language"),
    "segments": len(transcript.get("segments") or []),
    "quality": transcript.get("transcript_quality_check", {}).get("status"),
    "attempts": len(transcript.get("transcription_attempts") or []),
})
PY
```

Expected before rerun:

```text
{'model': 'turbo', 'backend': 'mlx-whisper', 'language': 'zh', 'segments': 1251, 'quality': None, 'attempts': 0}
```

The old run will not have new metadata until re-transcribed.

- [ ] **Step 2: Re-run one controlled transcription after implementation**

Use the existing audio and repaired metadata to call `build_transcript()` with the current run's `metadata.json`, `media/audio.mp3`, and `language=auto`:

```bash
uv run --extra dev python - <<'PY'
import json
from pathlib import Path
from bilifan.transcript import build_transcript

run = Path("outputs/BV1Hkr7YYEh8_p1/runs/2026-06-29_145519")
metadata = json.loads((run / "metadata.json").read_text(encoding="utf-8"))
media = {
    "duration_seconds": 2372,
    "audio_path": "media/audio.mp3",
}
transcript = build_transcript(metadata, media, run, language="auto", transcriber="whisper")
print({
    "model": transcript.get("model"),
    "language": transcript.get("language"),
    "quality": transcript.get("transcript_quality_check", {}).get("status"),
    "attempts": transcript.get("transcription_attempts"),
})
PY
```

Expected:

```text
model is turbo
language is zh
quality is ok or low_confidence
attempts contains one selected turbo/zh attempt unless the quality gate intentionally retries
```

- [ ] **Step 3: Run final validation**

Run:

```bash
git diff --check
uv run --extra dev pytest tests/test_transcription_routing.py tests/test_transcript_quality.py tests/test_transcript.py tests/test_pipeline.py tests/test_queue.py tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected:

```text
git diff --check has no output
all selected tests pass
```

- [ ] **Step 4: Restart local Bilifan Web only after implementation is merged into the active branch**

This affects only the local Bilifan Web/tunnel service and should not send Feishu messages:

```bash
/bin/zsh -lc 'set -a; source /Users/jack/.hermes/profiles/bilifan/.env; set +a; scripts/bilifan-remote.sh restart'
```

Expected:

```text
Web UI tmux:   bilifan-web (running)
Tunnel tmux:   bilifan-tunnel (running)
Local API:     reachable, token required
```

- [ ] **Step 5: Commit verification-only docs update if needed**

Runtime outputs under `outputs/` are not committed. Commit only a documentation clarification when verification reveals one:

```bash
git add docs/superpowers/specs/2026-06-29-bilifan-transcription-routing-guardrails-design.md
git commit -m "docs: clarify transcript routing verification"
```

---

## Self-Review

### Spec Coverage

- Routing Decision: Task 1 and Task 3.
- Transcript Quality Check: Task 2 and Task 3.
- One alternate retry: Task 4.
- Selected attempt feeds downstream: Task 4 keeps only selected transcript in `transcript.json`; existing pipeline consumes that one transcript.
- Succeeded With Warning: Task 5 and Task 6 surface warning state through diagnostics, queue warnings, and labels while preserving `succeeded`.
- Task Center labels: Task 6 and Task 7.
- Feishu completion warnings: current code has intake acknowledgement but no completion sender. This plan exposes the warning state in Bilifan queue/API; a later completion-notification worker must consume `warnings` and `transcript_source_label`.

### Placeholder Scan

This plan uses concrete file paths, code snippets, commands, and expected outcomes for every task.

### Type Consistency

- `routing_decision`: `dict[str, Any]` with `selected_model`, `selected_language`, `confidence`, `reason`, `signals`, `alternates`.
- `transcript_quality_check`: `dict[str, Any]` with `status`, `expected_language`, `observed_language`, `confidence`, `warnings`, `metrics`.
- `transcription_attempts`: `list[dict[str, Any]]` with `model`, `language`, `backend`, `quality_status`, `selected`.
- Warnings propagated through existing `PipelineResult.warnings`, `JobState.warnings`, and queue `QueueJob.warnings`.
