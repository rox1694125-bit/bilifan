# Bilifan Output Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the article-first output pipeline so new runs expose only `transcript.html`, `report.html`, `transcript.pdf`, and `report.pdf` while keeping internal machine artifacts hidden from ordinary Web result lists.

**Architecture:** Add `transcript_article.json` as the section source of truth after raw transcription and mechanical chunking. Generate report summaries from article sections, render transcript/report HTML from the same section boundaries, keep `content_bundle.json` hidden by default, and make `nabaichuan.jsonl` explicit-export only.

**Tech Stack:** Python 3.11, Typer, FastAPI, Jinja2, jsonschema, pytest, existing `codex exec` runner pattern.

---

## File Structure

- Create `src/bilifan/article.py`: builds and validates `transcript_article.json`; owns article schema, article prompt, Codex runner, normalization, and merge logic.
- Create `tests/test_article.py`: unit coverage for article prompt, source-specific cleaning level, validation, runner behavior, and timestamp/source-segment normalization.
- Modify `src/bilifan/summarizer.py`: add article-section-to-report summary functions while preserving old chunk summary functions for legacy retry compatibility where needed.
- Modify `tests/test_summarizer.py`: add tests for report summaries generated from article sections.
- Modify `src/bilifan/renderer.py`: add `render_transcript_html`; generalize PDF export without breaking `export_report_pdf`.
- Modify `tests/test_renderer.py`: cover transcript article HTML and both PDF output names.
- Modify `src/bilifan/bundle.py`: include `transcript_article` in `content_bundle.json` and map new artifact names.
- Modify `src/bilifan/exports.py`: keep `write_nabaichuan_jsonl`, but make records prefer article sections when the bundle has them.
- Modify `tests/test_bundle.py` and `tests/test_nabaichuan_export.py`: cover article-backed bundle and explicit export.
- Modify `src/bilifan/pipeline.py`: integrate article generation, article-backed report summary, transcript/report rendering, two PDF exports, hidden bundle, and no default nabaichuan export.
- Modify `src/bilifan/retry.py`: retry new runs with article-first flow; keep legacy old-run behavior when `transcript_article.json` is absent.
- Modify `tests/test_pipeline.py`, `tests/test_retry.py`, `tests/test_cli.py`: cover new artifact set, PDF behavior, and retry compatibility.
- Modify `src/bilifan/web/files.py`, `src/bilifan/web/jobs.py`, `src/bilifan/web/ui.py`: filter ordinary artifacts to user files plus open-folder, while keeping direct file resolution for allowed internal files.
- Modify `tests/test_web_jobs.py`, `tests/test_web_history_files.py`, `tests/test_web_ui.py`: cover new-run visibility, failure visibility, explicit export, and six old-run compatibility categories.
- Modify `README.md`: update the output tree and Web result description after code behavior changes.

## Task 1: Transcript Article Contract and Generator

**Files:**
- Create: `src/bilifan/article.py`
- Create: `tests/test_article.py`

- [ ] **Step 1: Write failing article tests**

Create `tests/test_article.py` with these tests:

```python
import json
import subprocess

import pytest

from bilifan.article import (
    ARTICLE_SCHEMA_VERSION,
    ArticleError,
    build_article_prompt,
    generate_transcript_article,
    normalize_transcript_article,
    run_codex_article_generation,
)
from bilifan.bilibili import BilibiliPartRef


REF = BilibiliPartRef(
    bvid="BV1abcDEF12G",
    part_index=1,
    sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
)


def _metadata():
    return {"title": "测试视频", "part_title": "P1", "owner_name": "UP", "duration": 90}


def _transcript(source="whisper"):
    return {
        "source": source,
        "language": "zh",
        "model": "turbo" if source == "whisper" else "",
        "segments": [
            {"start": 0, "end": 30, "text": "今天我们讲人工只能和工作流。"},
            {"start": 30, "end": 60, "text": "这个地方其实其实很重要。"},
            {"start": 60, "end": 90, "text": "最后总结一下。"},
        ],
        "transcript_check": {"status": "ok"},
    }


def _chunks():
    return {
        "chunks": [
            {
                "chunk_index": 1,
                "start": 0,
                "end": 90,
                "segment_start_index": 0,
                "segment_end_index": 2,
                "segments": [
                    {"source_index": 0, "start": 0, "end": 30, "text": "今天我们讲人工只能和工作流。"},
                    {"source_index": 1, "start": 30, "end": 60, "text": "这个地方其实其实很重要。"},
                    {"source_index": 2, "start": 60, "end": 90, "text": "最后总结一下。"},
                ],
                "text": "今天我们讲人工只能和工作流。\n这个地方其实其实很重要。\n最后总结一下。",
            }
        ]
    }


def _article_payload():
    return {
        "schema_version": ARTICLE_SCHEMA_VERSION,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 90,
                "source_segment_start_index": 0,
                "source_segment_end_index": 2,
                "paragraphs": [
                    {
                        "text": "今天我们讲人工智能和工作流。这个地方很重要。最后总结一下。",
                        "emphasis": [{"text": "人工智能", "kind": "strong"}],
                    }
                ],
                "key_terms": ["人工智能", "工作流"],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def test_build_article_prompt_uses_strong_cleaning_for_whisper():
    prompt = build_article_prompt(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript("whisper"),
        chunk=_chunks()["chunks"][0],
    )

    assert "强清洗" in prompt
    assert "错别字" in prompt
    assert "人工只能" in prompt
    assert "output_schema" in prompt


def test_build_article_prompt_uses_light_cleaning_for_subtitles():
    prompt = build_article_prompt(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript("bilibili-subtitle"),
        chunk=_chunks()["chunks"][0],
    )

    assert "轻清洗" in prompt
    assert "少改词" in prompt


def test_normalize_transcript_article_adds_timestamp_urls_and_validates_ranges():
    article = normalize_transcript_article(
        _article_payload(),
        ref=REF,
        transcript=_transcript(),
        chunks=_chunks(),
    )

    section = article["sections"][0]
    assert article["schema_version"] == ARTICLE_SCHEMA_VERSION
    assert section["timestamp_url"].endswith("&t=0")
    assert section["cleaning_level"] == "strong"
    assert section["paragraphs"][0]["emphasis"][0] == {"text": "人工智能", "kind": "strong"}


def test_normalize_transcript_article_rejects_unanchored_section():
    payload = _article_payload()
    payload["sections"][0]["source_segment_start_index"] = 99

    with pytest.raises(ArticleError, match="source segment"):
        normalize_transcript_article(payload, ref=REF, transcript=_transcript(), chunks=_chunks())


def test_run_codex_article_generation_invokes_codex_exec(tmp_path):
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_article_payload(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    article = run_codex_article_generation(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chunk=_chunks()["chunks"][0],
        run_dir=tmp_path,
        model="gpt-5.5",
        runner=fake_runner,
    )

    assert calls[0]["cmd"][1:3] == ["exec", "--ephemeral"]
    assert calls[0]["cmd"][calls[0]["cmd"].index("--model") + 1] == "gpt-5.5"
    assert "强清洗" in calls[0]["input"]
    assert article["sections"][0]["title"] == "人工智能工作流"


def test_generate_transcript_article_writes_stable_artifact(tmp_path):
    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_article_payload(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    article = generate_transcript_article(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chunks=_chunks(),
        run_dir=tmp_path,
        model="gpt-5.5",
        runner=fake_runner,
    )

    written = json.loads((tmp_path / "transcript_article.json").read_text(encoding="utf-8"))
    assert article == written
    assert written["sections"][0]["timestamp_url"].endswith("&t=0")
```

- [ ] **Step 2: Run article tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_article.py -q
```

Expected: fails because `bilifan.article` does not exist.

- [ ] **Step 3: Implement `src/bilifan/article.py`**

Implement these public names:

```python
ARTICLE_SCHEMA_VERSION = 1
ARTICLE_ARTIFACT = "transcript_article.json"

class ArticleError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))

def build_article_prompt(
    *,
    ref,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunk: dict[str, Any],
) -> str:
    return rendered_prompt

def run_codex_article_generation(
    *,
    ref,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunk: dict[str, Any],
    run_dir: Path,
    model: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    return parsed_article_json

def normalize_transcript_article(
    article: dict[str, Any],
    *,
    ref,
    transcript: dict[str, Any],
    chunks: dict[str, Any],
) -> dict[str, Any]:
    return normalized_article

def generate_transcript_article(
    *,
    ref,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chunks: dict[str, Any],
    run_dir: Path,
    provider: str = "codex-exec",
    model: str = "gpt-5.5",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    return written_article
```

Implementation requirements:

- Use the existing `summarizer.resolve_codex_executable()` helper instead of duplicating Codex binary lookup.
- Use `jsonschema.validate` against an `ARTICLE_SCHEMA`.
- Use `tempfile.TemporaryDirectory(dir=run_dir)` and `--output-schema` / `--output-last-message`, matching `run_codex_chunk_summary`.
- Cleaning level is `"strong"` when `transcript["source"] == "whisper"`, otherwise `"light"`.
- Prompt must explicitly say strong cleaning fixes Whisper typo/homophone/terminology/repetition issues and light cleaning should improve punctuation/paragraphing while making fewer word substitutions.
- Normalize section timestamps to non-negative floats and add `timestamp_url` with `ref.timestamp_url(start)`.
- Validate source segment ranges against transcript segment indices.
- Ensure every paragraph has `text` and `emphasis`; allowed emphasis kinds are `strong`, `mark`, and `list`.
- Write final JSON with `json.dumps(article, indent=2, ensure_ascii=False, allow_nan=False) + "\n"`.

- [ ] **Step 4: Run article tests and verify they pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_article.py -q
```

Expected: all tests in `tests/test_article.py` pass.

- [ ] **Step 5: Commit article generator**

Run:

```bash
git add src/bilifan/article.py tests/test_article.py
git commit -m "feat: add transcript article generator"
```

## Task 2: Article-Based Report Summary

**Files:**
- Modify: `src/bilifan/summarizer.py`
- Modify: `tests/test_summarizer.py`

- [ ] **Step 1: Write failing summary tests**

Append tests to `tests/test_summarizer.py`:

```python
def _article():
    return {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 90,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "source_segment_start_index": 0,
                "source_segment_end_index": 1,
                "paragraphs": [{"text": "今天我们讲人工智能和工作流。这个地方很重要。", "emphasis": []}],
                "key_terms": ["人工智能"],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def _article_report_payload():
    return {
        "chapters": [
            {
                "section_index": 1,
                "summary": "讲人工智能工作流的重要性。",
                "key_points": ["人工智能工作流是核心主题"],
                "quotes": ["这个地方很重要"],
                "visual_anchors": [],
            }
        ]
    }


def test_build_article_report_prompt_uses_cleaned_article_text():
    prompt = summarizer.build_article_report_prompt(
        metadata=_metadata(),
        article=_article(),
        style="学习笔记",
    )

    assert "清洗后的逐字稿文章" in prompt
    assert "人工智能和工作流" in prompt
    assert "这是转写内容" not in prompt


def test_summarize_article_sections_returns_existing_chapters_shape(tmp_path):
    def fake_runner(cmd, **kwargs):
        output_path = tmp_path / cmd[cmd.index("--output-last-message") + 1]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(_article_report_payload(), ensure_ascii=False), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    chapters = summarizer.summarize_article_sections(
        ref=REF,
        metadata=_metadata(),
        article=_article(),
        run_dir=tmp_path,
        model="gpt-5.5",
        style="学习笔记",
        runner=fake_runner,
    )

    chapter = chapters["chapters"][0]
    assert chapter["chapter_index"] == 1
    assert chapter["title"] == "人工智能工作流"
    assert chapter["summary"] == "讲人工智能工作流的重要性。"
    assert chapter["evidence"][0]["text_preview"].startswith("今天我们讲人工智能")
    assert chapters["summary_validation"]["status"] == "passed"
```

- [ ] **Step 2: Run targeted summarizer tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_summarizer.py -q
```

Expected: fails on missing article summary functions.

- [ ] **Step 3: Implement article report summary functions**

Add these public functions in `src/bilifan/summarizer.py`:

```python
def build_article_report_prompt(
    *,
    metadata: dict[str, Any],
    article: dict[str, Any],
    style: str,
) -> str:
    return rendered_prompt

def run_codex_article_report(
    *,
    metadata: dict[str, Any],
    article: dict[str, Any],
    run_dir: Path,
    model: str,
    style: str,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    return parsed_report_json

def summarize_article_sections(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    article: dict[str, Any],
    run_dir: Path,
    provider: str = "codex-exec",
    model: str = "gpt-5.5",
    style: str = "学习笔记",
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    return chapters_json
```

Implementation requirements:

- Reuse `validate_summary_style`, `resolve_codex_executable`, `_write_json`, `_read_json`, `_validate_json`, and timestamp formatting helpers where practical.
- Create an `ARTICLE_REPORT_SCHEMA` requiring `chapters[].section_index`, `summary`, `key_points`, `quotes`, and `visual_anchors`.
- Prompt must tell Codex to summarize only the cleaned article text and not invent facts.
- Convert each report chapter back to the existing `chapters.json` shape: `chapter_index`, `title`, `start`, `end`, `timestamp_url`, `summary`, `key_points`, `quotes`, `visual_anchors`, `evidence`.
- Evidence should be deterministic from the article section: source segment range, start/end, timestamp URL, and first paragraph preview.
- Add `summary_validation` with the same check keys currently used by report rendering.

- [ ] **Step 4: Run summarizer tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_summarizer.py -q
```

Expected: all summarizer tests pass.

- [ ] **Step 5: Commit article report summary**

Run:

```bash
git add src/bilifan/summarizer.py tests/test_summarizer.py
git commit -m "feat: summarize reports from transcript articles"
```

## Task 3: Transcript HTML Renderer and Generic PDF Export

**Files:**
- Modify: `src/bilifan/renderer.py`
- Modify: `tests/test_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Append tests to `tests/test_renderer.py`:

```python
def _article():
    return {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 90,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "source_segment_start_index": 0,
                "source_segment_end_index": 1,
                "paragraphs": [
                    {
                        "text": "今天我们讲人工智能和工作流。这个地方很重要。",
                        "emphasis": [{"text": "人工智能", "kind": "strong"}],
                    }
                ],
                "key_terms": ["人工智能", "工作流"],
                "warnings": [],
            }
        ],
        "warnings": ["部分术语可能未能确认"],
    }


def test_render_transcript_html_writes_readable_article_without_line_timestamps(tmp_path):
    html_path = renderer.render_transcript_html(
        ref=REF,
        metadata=_metadata(),
        article=_article(),
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert html_path.name == "transcript.html"
    assert "逐字稿文章" in html
    assert "人工智能工作流" in html
    assert "<strong>人工智能</strong>" in html
    assert "[0:00]" not in html
    assert "回到视频" in html
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2&amp;t=0" in html


def test_export_html_pdf_can_write_transcript_pdf(tmp_path):
    html_path = tmp_path / "transcript.html"
    pdf_path = tmp_path / "transcript.pdf"
    html_path.write_text("<html></html>", encoding="utf-8")

    def fake_runner(cmd, **kwargs):
        pdf_path.write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = renderer.export_html_pdf(
        html_path=html_path,
        pdf_path=pdf_path,
        chrome_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        runner=fake_runner,
    )

    assert result == pdf_path
```

- [ ] **Step 2: Run renderer tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_renderer.py -q
```

Expected: fails on missing `render_transcript_html` and `export_html_pdf`.

- [ ] **Step 3: Implement renderer changes**

Implementation requirements:

- Add `render_transcript_html(ref, metadata, article, run_dir) -> Path` returning `run_dir / "transcript.html"`.
- Add `export_html_pdf(html_path, pdf_path, runner=subprocess.run, chrome_path=None) -> Path`.
- Keep `export_report_pdf` as a wrapper around `export_html_pdf` with the same keyword parameters: `html_path`, `pdf_path`, `runner`, and `chrome_path`.
- Render transcript article as offline HTML with inline CSS.
- Do not show per-line timestamps in transcript body.
- Render section-level `timestamp_url` as a small “回到视频” link.
- Escape all article text through Jinja autoescape.
- Render emphasis by replacing exact paragraph text spans with `<strong>` for `kind == "strong"` and `<mark>` for `kind == "mark"` only after escaping. If replacement is ambiguous, leave plain text.

- [ ] **Step 4: Run renderer tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_renderer.py -q
```

Expected: all renderer tests pass.

- [ ] **Step 5: Commit renderer changes**

Run:

```bash
git add src/bilifan/renderer.py tests/test_renderer.py
git commit -m "feat: render transcript article outputs"
```

## Task 4: Bundle and Explicit Export Contract

**Files:**
- Modify: `src/bilifan/bundle.py`
- Modify: `src/bilifan/exports.py`
- Modify: `tests/test_bundle.py`
- Modify: `tests/test_nabaichuan_export.py`

- [ ] **Step 1: Write failing bundle/export tests**

Add tests that assert:

```python
def test_content_bundle_includes_transcript_article_and_new_artifacts():
    bundle = build_content_bundle(
        metadata=_metadata(),
        transcript=_transcript(),
        transcript_article=_article(),
        chapters=_chapters(),
        artifact_paths=["transcript.html", "report.html", "transcript.pdf", "report.pdf"],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
    )

    assert bundle["transcript_article"]["sections"][0]["title"] == "人工智能工作流"
    assert bundle["artifacts"]["transcript_html"] == "transcript.html"
    assert bundle["artifacts"]["transcript_pdf"] == "transcript.pdf"
    assert bundle["artifacts"]["report_html"] == "report.html"
    assert bundle["artifacts"]["report_pdf"] == "report.pdf"


def test_nabaichuan_records_prefer_article_sections_when_present():
    bundle = _bundle()
    bundle["transcript_article"] = {
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 60,
                "paragraphs": [{"text": "清洗后的正文。", "emphasis": []}],
            }
        ]
    }

    records = build_nabaichuan_records(bundle)
    transcript_records = [record for record in records if record["type"] == "transcript_segment"]
    assert transcript_records[0]["text"] == "清洗后的正文。"
```

- [ ] **Step 2: Run bundle/export tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bundle.py tests/test_nabaichuan_export.py -q
```

Expected: fails because bundle has no article support and export still only uses raw transcript segments.

- [ ] **Step 3: Implement bundle/export changes**

Implementation requirements:

- Add optional `transcript_article: dict[str, Any] | None = None` parameter to `build_content_bundle` and `write_content_bundle`.
- Add `transcript_article` top-level key to bundle when provided.
- Sanitize article text with existing `_sanitize_json_value`.
- Extend artifact map for `transcript.html`, `transcript.pdf`, and `transcript_article.json`.
- Keep backward compatibility when `transcript_article` is not passed.
- In `build_nabaichuan_records`, make transcript records prefer article sections:
  - each section becomes one transcript-like record from concatenated paragraph text;
  - fall back to existing raw transcript segment merge if article sections are missing.
- Keep single-run and batch export APIs writing `nabaichuan.jsonl` only when explicitly called.

- [ ] **Step 4: Run bundle/export tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bundle.py tests/test_nabaichuan_export.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 5: Commit bundle/export changes**

Run:

```bash
git add src/bilifan/bundle.py src/bilifan/exports.py tests/test_bundle.py tests/test_nabaichuan_export.py
git commit -m "feat: include transcript articles in bundle exports"
```

## Task 5: Pipeline and Retry Integration

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `src/bilifan/retry.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_retry.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing pipeline tests**

Update `tests/test_pipeline.py` expectations:

```python
assert "transcript_article.json" in result.artifact_paths
assert "transcript.html" in result.artifact_paths
assert "report.html" in result.artifact_paths
assert "content_bundle.json" in result.artifact_paths
assert "nabaichuan.jsonl" not in result.artifact_paths
assert "notes.md" not in result.artifact_paths
assert "transcript.txt" not in result.artifact_paths
assert "transcript.srt" not in result.artifact_paths
```

Add tests:

Add these concrete tests by reusing the existing fake pipeline fixtures in
`tests/test_pipeline.py`:

- `test_pipeline_exports_transcript_and_report_pdfs_when_pdf_requested`: monkeypatch
  `render_transcript_html` to write `transcript.html`, `render_report_html` to write
  `report.html`, and `export_html_pdf` to write the requested `pdf_path`; assert
  `transcript.pdf` and `report.pdf` are in `result.artifact_paths`.
- `test_pipeline_pdf_failure_warns_when_not_required`: monkeypatch `export_html_pdf`
  to raise `PdfExportError("pdf failed")`; assert the run succeeds, records one
  `pdf_failed` warning, and still returns both HTML artifacts.
- `test_pipeline_require_pdf_fails_if_transcript_pdf_fails`: pass a normal
  `PipelineRequest` with `require_pdf=True` and monkeypatch `export_html_pdf` to
  raise on the transcript PDF call; assert `PipelineRunError.exit_code == 1` and
  `transcript.html` is present in `exc_info.value.artifact_paths`.

- [ ] **Step 2: Run targeted pipeline/retry/CLI tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_retry.py tests/test_cli.py -q
```

Expected: fails because pipeline still writes old default exports and no article outputs.

- [ ] **Step 3: Integrate article-first pipeline**

Implementation requirements:

- Import `generate_transcript_article`, `summarize_article_sections`, `render_transcript_html`, and `export_html_pdf`.
- Keep `build_chunks` as mechanical context preparation, but make `transcript_article.json` the chapter source after chunking.
- Stop calling `write_transcript_exports` and `write_notes_markdown` in the successful default path.
- Stop calling `write_nabaichuan_jsonl` in the successful default path.
- After `chapters = summarize_article_sections(ref=ref, metadata=metadata, article=article, run_dir=run.run_dir, provider=request.llm_provider, model=request.llm_model, style=request.summary_template)`, keep writing `chapters.json` as an internal report summary for now.
- Render `transcript.html` before `report.html`.
- When PDF is enabled, call `export_html_pdf` twice:
  - `transcript.html` -> `transcript.pdf`
  - `report.html` -> `report.pdf`
- If either PDF fails and `require_pdf` is false, append one `pdf_failed` warning and continue.
- If either PDF fails and `require_pdf` is true, write diagnostics and raise `PipelineRunError`.
- Pass `transcript_article=article` to `write_content_bundle`.
- Diagnostics artifact paths should include internal files, but Web filtering will hide them.

- [ ] **Step 4: Integrate retry**

Implementation requirements:

- For `from_stage == "summarization"` in `retry.py`, read `chunks.json`, regenerate `transcript_article.json`, then regenerate article-backed `chapters.json`.
- For `from_stage == "render"`, require `transcript_article.json` for new runs. If absent, use existing legacy `chapters.json` behavior so old runs can still render.
- For `from_stage == "bundle"`, pass article to `write_content_bundle` when `transcript_article.json` exists.
- Remove default retry-time `write_notes_markdown` and default `write_nabaichuan_jsonl`.
- Preserve old-run compatibility when only `chapters.json` exists.

- [ ] **Step 5: Run pipeline/retry/CLI tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_retry.py tests/test_cli.py -q
```

Expected: targeted tests pass.

- [ ] **Step 6: Commit pipeline integration**

Run:

```bash
git add src/bilifan/pipeline.py src/bilifan/retry.py tests/test_pipeline.py tests/test_retry.py tests/test_cli.py
git commit -m "feat: integrate article-first output pipeline"
```

## Task 6: Web Visibility and Legacy Compatibility

**Files:**
- Modify: `src/bilifan/web/files.py`
- Modify: `src/bilifan/web/jobs.py`
- Modify: `src/bilifan/web/ui.py`
- Modify: `tests/test_web_jobs.py`
- Modify: `tests/test_web_history_files.py`
- Modify: `tests/test_web_ui.py`

- [ ] **Step 1: Write failing Web visibility tests**

Update new-run artifact tests to expect only user files plus folder:

```python
assert state["artifacts"] == {
    "transcript_html": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.html",
    "html": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
    "transcript_pdf": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.pdf",
    "pdf": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.pdf",
    "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
}
```

Add failure assertion:

```python
assert "diagnostics" not in state["artifacts"]
assert state["artifacts"]["folder"].endswith("/open-folder")
```

Add six legacy compatibility fixtures in tests by creating run directories with these file shapes:

```python
LEGACY_CASES = [
    ("legacy_success_no_bundle", ["report.html", "report.pdf", "notes.md", "transcript.txt", "transcript.srt", "diagnostics.json"]),
    ("legacy_success_bundle_no_nabaichuan", ["report.html", "report.pdf", "content_bundle.json", "diagnostics.json"]),
    ("legacy_success_full_old", ["report.html", "report.pdf", "notes.md", "transcript.txt", "transcript.srt", "content_bundle.json", "nabaichuan.jsonl", "diagnostics.json"]),
    ("legacy_transcript_partial", ["transcript.json", "transcript.txt", "transcript.srt", "diagnostics.json"]),
    ("legacy_diagnostics_only", ["diagnostics.json"]),
    ("legacy_youtube_success", ["report.html", "report.pdf", "content_bundle.json", "diagnostics.json"]),
]
```

Expected behavior:

- legacy successful runs may expose `html`, `pdf`, and `folder`;
- legacy partial/failed runs expose `folder` and friendly error only;
- none expose `bundle`, `nabaichuan`, `txt`, `srt`, `md`, `audio`, or `diagnostics` in ordinary artifacts.

- [ ] **Step 2: Run Web tests and verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_jobs.py tests/test_web_history_files.py tests/test_web_ui.py -q
```

Expected: fails because Web artifacts still expose diagnostics, text, markdown, bundle, nabaichuan, and audio.

- [ ] **Step 3: Implement Web artifact filtering**

Implementation requirements:

- In `web/files.py`, split allowed direct files from ordinary listed/displayed files:
  - direct allowed files still include internal JSON, explicit export files, and legacy artifacts;
  - ordinary artifacts only include `transcript.html`, `report.html`, `transcript.pdf`, `report.pdf`, and `folder`.
- Add new artifact keys:
  - `transcript_html` -> `transcript.html`
  - `html` -> `report.html`
  - `transcript_pdf` -> `transcript.pdf`
  - `pdf` -> `report.pdf`
- For legacy successful runs without `transcript.html`, expose existing `report.html` and `report.pdf`.
- For failed runs, do not expose diagnostics links in ordinary artifacts; keep `friendly_error` and retry actions.
- In `web/jobs.py`, make `_artifact_links` apply the same filtering to current jobs and pipeline errors.
- In `web/ui.py`, update labels:
  - `transcript_html`: `逐字稿文章`
  - `html`: `主报告`
  - `transcript_pdf`: `逐字稿 PDF`
  - `pdf`: `报告 PDF`
  - `folder`: `打开本地文件夹`
- Keep explicit nabaichuan export buttons available for succeeded runs by run key, not by visible `bundle` artifact.
- Keep `/api/runs/{output_id}/runs/{run_id}/files/{file_path}` able to serve internal files when explicitly requested and token-authenticated.

- [ ] **Step 4: Run Web tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_jobs.py tests/test_web_history_files.py tests/test_web_ui.py -q
```

Expected: targeted Web tests pass.

- [ ] **Step 5: Commit Web visibility changes**

Run:

```bash
git add src/bilifan/web/files.py src/bilifan/web/jobs.py src/bilifan/web/ui.py tests/test_web_jobs.py tests/test_web_history_files.py tests/test_web_ui.py
git commit -m "feat: show consolidated web artifacts"
```

## Task 7: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: test files named in Tasks 1-6 if the final focused run exposes assertion drift from the intentional artifact-key rename.

- [ ] **Step 1: Update README output description**

Change the output tree to show:

```text
outputs/
  BV1abcDEF12G_p2/
    latest.json
    runs/
      <timestamp>/
        transcript.html
        report.html
        transcript.pdf
        report.pdf
        content_bundle.json        # hidden machine contract
        metadata.json              # hidden internal
        transcript.json            # hidden raw transcript
        transcript_article.json    # hidden article source
        chunks.json                # hidden internal
        chapters.json              # hidden report summary
        diagnostics.json           # hidden internal
```

State that `nabaichuan.jsonl` is produced by explicit single-run or batch export, not by every run.

- [ ] **Step 2: Run focused test groups**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider \
  tests/test_article.py \
  tests/test_summarizer.py \
  tests/test_renderer.py \
  tests/test_bundle.py \
  tests/test_nabaichuan_export.py \
  tests/test_pipeline.py \
  tests/test_retry.py \
  tests/test_web_jobs.py \
  tests/test_web_history_files.py \
  tests/test_web_ui.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run full suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: full suite passes or only pre-existing unrelated failures are identified with exact test names.

- [ ] **Step 4: Run diff check**

Run:

```bash
git diff --check
```

Expected: no whitespace errors.

- [ ] **Step 5: Commit docs and final alignment**

Run:

```bash
git add README.md tests src
git commit -m "docs: document consolidated outputs"
```

Skip this commit if there are no remaining unstaged changes after previous task commits.
