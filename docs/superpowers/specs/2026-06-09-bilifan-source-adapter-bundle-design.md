# Bilifan Source Adapter, Bundle, and Nabaichuan Integration Design

## Goal

Upgrade Bilifan from a Bilibili-only learning-note generator into a reusable local video knowledge extraction layer.

The priority for this phase is not a polished YouTube product. The priority is to produce a stable `content_bundle.json` contract that Nabaichuan can consume, while keeping the existing Bilibili workflow working and adding a first YouTube public-video adapter.

## Confirmed Decisions

- Nabaichuan integration is contract-first in this phase.
- Bilifan will not directly modify the Nabaichuan repository in this phase.
- Bilifan will output `content_bundle.json` and provide an example ingest script plus mapping documentation.
- YouTube first version supports public ordinary watch URLs only.
- YouTube first version is subtitle-first. Whisper fallback is allowed when subtitles are unavailable or explicitly forced.
- YouTube first version does not support playlists, private videos, members-only videos, age-restricted videos, cookies, live streams, or Shorts-specific UX.
- Retry support is stage-level, not a general DAG scheduler.
- Retry support covers `summarization`, `render`, and `bundle`.
- Web UI retry buttons are not required in the first implementation slice.
- Existing Bilibili CLI and Web UI behavior must not regress.

## Non-Goals

- Hosted service.
- Platform login or account management.
- Circumventing platform access controls.
- Batch queue or parallel job orchestration.
- Full arbitrary pipeline graph scheduling.
- Editing generated reports in Web UI.
- Direct writes into Nabaichuan's production database.
- YouTube playlist ingestion.
- YouTube cookies flow.
- SVG diagrams, real frame screenshots, or visual QA.

## Architecture

The phase introduces two boundaries:

1. `SourceAdapter`: normalizes platform-specific extraction.
2. `content_bundle.json`: normalizes downstream knowledge ingestion.

High-level flow:

```text
URL
  -> SourceAdapter.resolve_ref
  -> SourceAdapter.fetch_metadata
  -> SourceAdapter.fetch_subtitles or download_audio + Whisper
  -> transcript.json
  -> chunks.json
  -> chapters.json
  -> report.html / report.pdf / notes.md
  -> content_bundle.json
  -> Nabaichuan ingest example
```

The pipeline should depend on source-neutral data structures wherever practical. Platform-specific code owns URL parsing, metadata mapping, subtitle extraction, media download options, and timestamp URL generation.

## Task 1: Retry Pipeline and Content Bundle

### Purpose

Reduce real-test cost after failures and create the stable Nabaichuan contract.

### Public Interface

Add:

```bash
bilifan retry <run_dir> --from summarization
bilifan retry <run_dir> --from render
bilifan retry <run_dir> --from bundle
```

Stage behavior:

- `--from summarization`: require `metadata.json`, `transcript.json`, and `chunks.json`; regenerate `partial_summaries`, `chapters.json`, `notes.md`, reports, diagnostics, and bundle.
- `--from render`: require `metadata.json`, `transcript.json`, `chunks.json`, and `chapters.json`; regenerate `notes.md`, reports, diagnostics, and bundle.
- `--from bundle`: require `metadata.json`, `transcript.json`, and `chapters.json`; regenerate `content_bundle.json`.

The retry command should never redownload media or rerun Whisper unless a later design explicitly adds that mode.

### `content_bundle.json`

Bundle schema version starts at `1`.

Required top-level shape:

```json
{
  "schema_version": 1,
  "bundle_id": "bilibili:BV1xx:p1",
  "source": {
    "platform": "bilibili",
    "id": "BV1xx",
    "part_id": "p1",
    "canonical_url": "https://www.bilibili.com/video/BV1xx?p=1",
    "title": "Video title",
    "author": "UP name",
    "published_at": null,
    "duration_seconds": 123.4,
    "language": "zh"
  },
  "artifacts": {
    "report_html": "report.html",
    "report_pdf": "report.pdf",
    "notes_md": "notes.md",
    "transcript_txt": "transcript.txt",
    "transcript_srt": "transcript.srt"
  },
  "summary": {
    "style": "学习笔记",
    "chapters": []
  },
  "transcript": {
    "source": "whisper",
    "language": "zh",
    "segments": []
  },
  "provenance": {
    "bilifan_version": "0.1.0",
    "generated_at": "2026-06-09T00:00:00+00:00",
    "llm_provider": "codex-exec",
    "llm_model": "gpt-5.5",
    "transcript_source": "whisper"
  }
}
```

Constraints:

- Paths in `artifacts` are relative to the run directory.
- No cookies, tokens, raw browser profile paths, or local absolute paths.
- `chapters[].timestamp_url` remains platform-specific and clickable.
- Bundle should be strict JSON and deterministic enough for tests.

### Diagnostics

Retry writes a fresh `diagnostics.json`. If bundle generation fails, earlier artifacts should remain untouched and diagnostics should include `bundle_failed`.

### Tests

- Bundle writer produces strict sanitized JSON.
- Bundle writer rejects absolute artifact paths.
- Retry from `summarization` reuses existing transcript and chunks.
- Retry from `render` does not rerun summarization.
- Retry from `bundle` writes only bundle and diagnostics.
- Existing Bilibili successful pipeline includes `content_bundle.json`.

## Task 2: SourceAdapter Base

### Purpose

Separate platform extraction from the core summarization pipeline.

### Proposed Types

Add `src/bilifan/sources/base.py`.

Conceptual interfaces:

```python
class SourceAdapter(Protocol):
    platform: str

    def parse_url(self, url: str) -> VideoRef: ...
    def timestamp_url(self, ref: VideoRef, seconds: float) -> str: ...
    def output_id(self, ref: VideoRef) -> str: ...
    def fetch_metadata(self, ref: VideoRef, run_dir: Path, options: SourceOptions) -> dict: ...
    def download_audio(self, ref: VideoRef, metadata: dict, run_dir: Path, options: SourceOptions) -> dict: ...
    def fetch_subtitles(self, ref: VideoRef, metadata: dict, run_dir: Path, options: SourceOptions) -> dict | None: ...
```

Use plain dictionaries at the pipeline boundary initially if that keeps the migration small. Typed dataclasses can be introduced gradually once both Bilibili and YouTube adapters are stable.

### Adapter Registry

Add a small resolver:

```python
resolve_source_adapter(url) -> SourceAdapter
```

First supported platforms:

- `bilibili`
- `youtube`

Unknown URLs should fail at preflight with an actionable error.

### Tests

- Adapter resolver returns Bilibili adapter for Bilibili URLs.
- Adapter resolver returns YouTube adapter for ordinary YouTube watch URLs.
- Unknown URL fails before creating expensive artifacts.
- Pipeline can call source-neutral timestamp URL generation.

## Task 3: BilibiliAdapter Migration

### Purpose

Move existing Bilibili behavior behind the adapter without changing user-visible behavior.

### Migration Strategy

Keep current modules working during migration:

- `bilibili.py`: URL parsing and Bilibili-specific reference compatibility.
- `metadata.py`: Bilibili metadata implementation.
- `media.py`: Bilibili audio implementation.
- `transcript.py`: subtitle and Whisper strategy.

Add `src/bilifan/sources/bilibili.py` as a wrapper first. It can delegate to existing functions. Do not rewrite all Bilibili logic in one pass.

### Compatibility Requirements

- CLI command remains:

```bash
bilifan summarize <bilibili-url>
```

- Web UI still accepts Bilibili URLs.
- Output directory names remain `BV..._pN`.
- Timestamp URLs remain Bilibili `?p=N&t=seconds`.
- Current P only behavior remains unchanged.

### Tests

- Existing Bilibili unit tests pass unchanged where possible.
- One new adapter test verifies current P URL parsing through the adapter.
- Existing metadata smoke continues to use the three public Bilibili URLs.
- Existing report and export tests include `content_bundle.json`.

## Task 4: YouTubeAdapter First Version

### Purpose

Support public YouTube videos through the same normalized pipeline.

### Scope

Supported:

- `https://www.youtube.com/watch?v=...`
- `https://youtu.be/...`
- Public ordinary videos.
- Metadata through `yt-dlp`.
- Manual subtitles and automatic subtitles through `yt-dlp`.
- Whisper fallback when no usable subtitle exists or `--force-whisper` is used.

Not supported:

- Playlists.
- Channels.
- Private videos.
- Members-only videos.
- Age-restricted videos.
- Cookies.
- Live streams.
- Shorts-specific UX.

### Metadata Mapping

Map at least:

- `id`
- `title`
- `channel` or `uploader`
- `duration`
- `description`
- `tags`
- `thumbnail`
- subtitle tracks
- source provenance

### Subtitle Strategy

Order:

1. Prefer manual subtitles in requested language.
2. Then automatic subtitles.
3. Then Whisper fallback.

Default language behavior mirrors existing Bilifan behavior:

- `language=auto`: use available transcript language where possible.
- `language=zh`: prefer Chinese subtitle or Whisper Chinese.
- `language=en`: prefer English subtitle or Whisper English.

### Timestamp URLs

Use:

```text
https://www.youtube.com/watch?v=<id>&t=<seconds>s
```

### Tests

- URL parser accepts watch and youtu.be URLs.
- URL parser rejects playlist-only URLs.
- Metadata mapping handles representative `yt-dlp` JSON fixtures.
- Subtitle parser handles VTT/JSON-derived segments.
- Timestamp URL generation is correct.
- YouTube adapter can run a mocked subtitle-only pipeline to bundle.

Live YouTube smoke is optional and gated behind an environment variable, similar to Bilibili metadata smoke.

## Task 5: Nabaichuan Ingest Example

### Purpose

Provide a stable integration path without coupling Bilifan to the Nabaichuan repository.

### Files

Add:

```text
docs/nabaichuan-integration.md
examples/content_bundle_to_nabaichuan.py
tests/test_nabaichuan_example.py
```

### Example Output

The example script reads one `content_bundle.json` and writes JSONL records suitable for ingestion by Nabaichuan or a similar knowledge base.

Suggested records:

- one `video` record
- one `chapter` record per chapter
- optional `transcript_segment` records when requested by a flag

Example shape:

```json
{"type":"video","source_id":"bilibili:BV1xx:p1","title":"...","platform":"bilibili"}
{"type":"chapter","source_id":"bilibili:BV1xx:p1#chapter-1","title":"...","summary":"..."}
```

The script should not require Nabaichuan dependencies.

### Documentation

Document:

- Bundle fields Nabaichuan should treat as stable.
- Fields that may expand later.
- How to map chapters to notes/cards.
- How to preserve source timestamp links.
- How to avoid depending on Bilifan internal run directory layout.

### Tests

- Example script accepts a Bilibili bundle fixture.
- Example script accepts a YouTube bundle fixture.
- Output JSONL is valid UTF-8 and strict JSON per line.
- Output does not include local absolute paths.

## Implementation Sequence

### Slice 1: Bundle and Retry

Implement first because it reduces the cost of every later real-video test.

Commit target:

```text
feat: add content bundle and retry command
```

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bundle.py tests/test_pipeline.py tests/test_cli.py -q
```

### Slice 2: SourceAdapter Base

Introduce the adapter boundary while keeping existing Bilibili calls delegated.

Commit target:

```text
feat: add source adapter base
```

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_sources.py tests/test_pipeline.py -q
```

### Slice 3: BilibiliAdapter Migration

Move current Bilibili behavior behind the adapter and preserve existing output.

Commit target:

```text
refactor: route bilibili pipeline through source adapter
```

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bilibili.py tests/test_metadata.py tests/test_media.py tests/test_transcript.py tests/test_pipeline.py -q
```

### Slice 4: YouTubeAdapter

Add YouTube public-video support with mocked tests first, optional live smoke second.

Commit target:

```text
feat: add youtube source adapter
```

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_youtube.py tests/test_pipeline.py -q
```

### Slice 5: Nabaichuan Example

Add integration docs and example JSONL converter.

Commit target:

```text
docs: add nabaichuan bundle integration example
```

Verification:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_nabaichuan_example.py -q
```

### Final Verification

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
git diff --check
```

Optional live smoke:

- one public Bilibili URL through current Web UI or CLI.
- one public YouTube URL with available subtitles.
- one retry from a failed or copied run.
- one Nabaichuan example conversion from each platform bundle.

## Multi-Agent Plan

Use subagents only after Slice 1 establishes the bundle contract.

Recommended split:

- Agent A: bundle schema, bundle writer, retry command.
- Agent B: source adapter base and Bilibili migration.
- Agent C: YouTube adapter fixtures and parser tests.
- Agent D: Nabaichuan docs and example converter.
- Main agent: integration, conflict resolution, full verification, commits, push.

Parallelization rules:

- Agent C can build YouTube fixture tests after base adapter signatures are agreed.
- Agent D can draft docs once `content_bundle.json` schema is stable.
- Agent B should not rename current Bilibili modules until Slice 1 is committed.
- Main agent must own final pipeline integration because `pipeline.py` is a shared hotspot.

## Risks and Mitigations

### Risk: Adapter abstraction causes broad churn

Mitigation: Start with wrapper adapters that delegate to existing modules. Avoid rewriting metadata/media/transcript internals in the same slice.

### Risk: Retry becomes a hidden scheduler

Mitigation: Only implement explicit `--from summarization|render|bundle`. Reject missing prerequisites with clear errors.

### Risk: Bundle schema changes after Nabaichuan starts consuming it

Mitigation: Add `schema_version`, fixtures, strict tests, and documentation of stable fields.

### Risk: YouTube extraction is unstable

Mitigation: Mock unit tests are primary. Live YouTube smoke is optional and gated. Scope excludes cookies and restricted content.

### Risk: Web UI falls behind CLI capabilities

Mitigation: This phase adds CLI support first. Web UI retry buttons can be a follow-up after CLI behavior is stable.

### Risk: Local paths leak into bundle or Nabaichuan example

Mitigation: Bundle tests reject absolute paths and sensitive strings. Diagnostics sanitization remains separate.

## Acceptance Criteria

This phase is complete when:

- Existing Bilibili CLI and Web UI workflows still pass tests.
- Successful Bilibili runs include `content_bundle.json`.
- `bilifan retry` can recover from summarization/render/bundle stages using existing artifacts.
- Source adapter resolver supports Bilibili and YouTube.
- YouTube mocked subtitle-only pipeline reaches `content_bundle.json`.
- Nabaichuan example converts both Bilibili and YouTube bundle fixtures to valid JSONL.
- Full test suite passes.
- README or docs clearly state YouTube and Nabaichuan boundaries.

