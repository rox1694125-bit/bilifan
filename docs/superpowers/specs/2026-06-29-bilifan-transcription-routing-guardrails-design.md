# Bilifan Transcription Routing Guardrails Design

## Goal

Prevent Bilifan from silently using the wrong Whisper language or model when
metadata is misleading. The immediate motivating case was a Chinese Git tutorial
whose description contained English reference URLs, causing `language=auto` to
choose `Whisper small.en`.

The design keeps the current product boundary: Bilifan remains a local video
knowledge workbench, subtitles remain preferred, and Whisper routing only
applies when fallback transcription is needed or explicitly forced.

## Confirmed Decisions

- Keep subtitle-first behavior. These guardrails apply to Whisper fallback.
- Keep the public language interface as `auto | zh | en`.
- Keep `zh -> Whisper turbo` and `en -> Whisper small.en`.
- `language=auto` should remain convenient, but it must become auditable and
  recoverable.
- Record a structured Routing Decision before Whisper runs.
- Add a Transcript Quality Check after Whisper runs. This is separate from the
  existing completeness check.
- If quality checks indicate likely model misuse, automatically retry one
  alternate Whisper route.
- If the retry is cleaner, use the corrected transcript and record the
  auto-correction.
- If both attempts remain suspicious, do not present the task as an ordinary
  clean success. Surface Succeeded With Warning or a failure diagnostic,
  depending on artifact usability.
- Do not call an LLM for the first version of route selection or quality
  checking.

## Non-Goals

- Do not add more public language options in this slice.
- Do not replace Whisper with a different transcription engine.
- Do not make transcription routing depend on Feishu or Hermes.
- Do not translate transcripts as part of routing.
- Do not attempt unlimited retries.
- Do not block manual `--language zh` or `--language en` choices unless the
  result is clearly unusable.

## Current Failure Mode

The current `auto` path chooses the Whisper model before transcription using
metadata signals such as title, part title, description, tags, and subtitle
language metadata. This is fast, but metadata can describe references rather
than spoken audio.

Examples:

- Chinese title plus English documentation links.
- Chinese translated title for an English lecture.
- English-heavy tags on a Chinese tutorial.
- Bilingual descriptions where only a small phrase indicates the spoken audio.

The existing `transcript_check` validates structural completeness, such as
segment coverage relative to audio duration. It does not answer whether the
chosen language/model produced a plausible transcript.

## Routing Decision

Before Whisper runs, Bilifan should write a structured decision into the run's
diagnostic data and final transcript metadata.

Suggested shape:

```json
{
  "schema_version": 1,
  "selected_model": "turbo",
  "selected_language": "zh",
  "confidence": "high",
  "reason": "cjk_title_without_explicit_english_audio",
  "signals": [
    "title_has_cjk",
    "description_urls_ignored",
    "no_explicit_english_audio_signal"
  ],
  "alternates": [
    {"model": "small.en", "language": "en"}
  ]
}
```

The reason should be deterministic and short enough for diagnostics, tests, and
future UI labels. It should not contain raw secrets or full fetched metadata.

## Transcript Quality Check

After Whisper returns segments, Bilifan should run a deterministic quality check
before generating user-facing artifacts.

The first version should use cheap heuristics:

- Expected Chinese, but transcript has very low CJK ratio.
- Expected English, but transcript has very low ASCII word ratio.
- Very high repeated-fragment ratio.
- Very low useful text density relative to duration.
- Metadata strongly indicates Chinese while transcript is mostly English-like
  filler.
- Metadata strongly indicates English while transcript is mostly CJK or empty.

Suggested shape:

```json
{
  "schema_version": 1,
  "status": "ok",
  "expected_language": "zh",
  "observed_language": "zh",
  "confidence": "high",
  "warnings": [],
  "metrics": {
    "cjk_ratio": 0.72,
    "ascii_word_ratio": 0.18,
    "repeat_fragment_ratio": 0.03,
    "chars_per_second": 4.1
  }
}
```

Statuses:

- `ok`: transcript looks compatible with the selected route.
- `suspect_wrong_route`: transcript likely used the wrong language/model.
- `low_confidence`: transcript may be usable but should be surfaced with a
  warning.
- `unusable`: transcript is too empty, repetitive, or malformed to continue
  normally.

## Auto-Correction Retry

When the first attempt returns `suspect_wrong_route`, Bilifan should retry once
with the alternate route:

- `small.en/en -> turbo/zh`
- `turbo/zh -> small.en/en`

The retry should reuse the already downloaded audio file. It should not
redownload media or restart the whole pipeline.

The final transcript should include attempt metadata:

```json
{
  "source": "whisper",
  "model": "turbo",
  "backend": "mlx-whisper",
  "language": "zh",
  "routing_decision": {...},
  "transcript_quality_check": {...},
  "transcription_attempts": [
    {
      "model": "small.en",
      "language": "en",
      "quality_status": "suspect_wrong_route",
      "selected": false
    },
    {
      "model": "turbo",
      "language": "zh",
      "quality_status": "ok",
      "selected": true
    }
  ]
}
```

Only the selected attempt should feed `transcript_article.json`, `report.html`,
PDFs, exports, and Feishu completion notifications.

## User-Visible Behavior

Task Center should show enough information to explain what happened without
turning the UI into a debug console:

- Clean route: `逐字稿: Whisper turbo`
- Corrected route: `逐字稿: Whisper turbo · 已自动纠偏`
- Suspicious but usable: `逐字稿: Whisper turbo · 需复查`

For Feishu completion notifications, the message should stay short:

- Clean success: report link and artifact status.
- Corrected success: mention that Bilifan automatically retried with the better
  route.
- Succeeded With Warning: include a plain-language warning that the transcript
  may need review.

Queue accounting can keep terminal status `succeeded` for usable artifacts, but
the task item needs a warning field so clean success and Succeeded With Warning
are visually distinct.

## Testing Strategy

Add a small routing fixture set before broad implementation:

- Chinese tutorial with English reference URLs.
- Chinese title for an English audio lecture.
- English title for a Chinese tutorial.
- Mixed Chinese/English tags where tags should not dominate title evidence.
- Subtitle-first video where Whisper routing should not run.
- Forced Whisper with explicit `language=zh`.
- Forced Whisper with explicit `language=en`.

Tests should cover:

- Routing Decision reason and selected route.
- Quality check status for representative transcript snippets.
- Auto-correction retry chooses the cleaner alternate attempt.
- Diagnostics and queue labels expose corrected and warning states.
- Existing transcript completeness checks still run independently.

## Phasing

### P1: Auditable Routing

Add `routing_decision` and regression fixtures around `choose_whisper_model`.
This improves observability without changing pipeline behavior.

### P2: Quality Gate

Add deterministic Transcript Quality Check and warnings. The gate should run
after Whisper and before article/report generation.

### P3: One-Shot Auto-Correction

Use the quality gate to retry once with the alternate route. Preserve both
attempt summaries, but publish only the selected transcript.

### P4: UI and Feishu Warnings

Expose corrected and warning states in Task Center, history, run details, and
Feishu completion notifications.

## Open Implementation Notes

- The first quality gate should stay deterministic. LLM review can be added
  later only if fixture coverage shows rule-based checks cannot handle common
  cases.
- Metrics thresholds should start conservative to avoid false positives that
  double transcription time unnecessarily.
- The retry policy should be isolated from source adapters so Bilibili and
  YouTube can share it.
- The selected attempt should remain the only content source for
  `transcript_article.json` and downstream reports.
