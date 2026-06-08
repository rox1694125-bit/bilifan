# Bilifan Export, Language, and Folder Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user-friendly transcript exports, Whisper language selection, and a secure Web UI action to open each run's local folder.

**Architecture:** Keep a lightweight export layer in `src/bilifan/exports.py`, wire it into the existing pipeline at transcript and summarization boundaries, and expose new artifact links through the current Web UI history/job APIs. Keep folder opening in the Web layer with server-side run-key resolution and macOS-only `open`.

**Tech Stack:** Python 3.12, Typer, FastAPI, pytest, local openai-whisper, existing Bilifan pipeline modules.

---

## File Structure

- Create `src/bilifan/exports.py`
  - Owns `write_transcript_exports`, `write_notes_markdown`, timestamp formatting, and Markdown/SRT escaping.
- Create `tests/test_exports.py`
  - Unit tests for txt/srt/md formatting and one-off backfill behavior.
- Modify `src/bilifan/transcript.py`
  - Add explicit `language` preference and improve English auto detection.
- Modify `tests/test_transcript.py`
  - Cover `auto|zh|en`, mixed Chinese/English metadata, and subtitle-first behavior.
- Modify `src/bilifan/pipeline.py`
  - Add `language` to `PipelineRequest`, call export functions as soon as data is available, and include export artifacts in diagnostics.
- Modify `tests/test_pipeline.py`, `tests/test_cli.py`
  - Cover pipeline artifact paths and CLI `--language`.
- Modify `src/bilifan/cli.py`
  - Add `--language auto|zh|en`.
- Modify `src/bilifan/web/app.py`
  - Add `language` to payload/defaults and add open-folder endpoint.
- Modify `src/bilifan/web/files.py`
  - Add txt/srt/md to allowed root artifacts, artifact links, and safe folder resolution/open helper.
- Modify `src/bilifan/web/jobs.py`
  - Include txt/srt/md and folder action metadata in current job artifacts.
- Modify `src/bilifan/web/ui.py`
  - Add language select and render TXT/SRT/MD/Open Folder actions.
- Modify `tests/test_web_jobs.py`, `tests/test_web_history_files.py`, `tests/test_web_ui.py`
  - Cover Web API and UI behavior.
- No permanent historical-backfill command is added. Backfill is a one-off verification step after implementation.

## Parallelization Notes

Run implementation in these batches:

1. Task 1 can run first and independently.
2. Task 2 can run in parallel with Task 1 after reading current transcript tests.
3. Task 3 depends on Task 1 and Task 2.
4. Task 4 and Task 5 can run after Task 3 defines artifact keys and request shape.
5. Task 6 is final integration, local backfill, and verification.

Each worker must avoid committing `.DS_Store` files. Existing untracked `.DS_Store` files are local Finder noise.

## Task 1: Export Module

**Files:**
- Create: `src/bilifan/exports.py`
- Create: `tests/test_exports.py`

- [ ] **Step 1: Write failing export format tests**

Add `tests/test_exports.py` with tests equivalent to:

```python
from pathlib import Path

from bilifan.exports import (
    format_srt_timestamp,
    write_notes_markdown,
    write_transcript_exports,
)


def _metadata():
    return {
        "title": "测试视频",
        "part_title": "当前 P",
        "owner_name": "UP",
        "duration": 125,
        "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    }


def _transcript():
    return {
        "source": "whisper",
        "model": "turbo",
        "language": "zh",
        "segments": [
            {"start": 0, "end": 2.18, "text": "Hello 大家好"},
            {"start": 62.5, "end": 65.0, "text": "第二段"},
        ],
        "transcript_check": {"status": "ok"},
    }


def _chapters():
    return {
        "style": "学习笔记",
        "chapters": [
            {
                "chapter_index": 1,
                "title": "开场",
                "start": 0,
                "end": 65,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "summary": "讲清楚问题。",
                "key_points": ["要点一"],
                "quotes": ["关键句"],
                "visual_anchors": ["白板"],
            }
        ],
    }


def test_format_srt_timestamp_uses_subrip_format():
    assert format_srt_timestamp(3723.4567) == "01:02:03,457"


def test_write_transcript_exports_writes_txt_and_srt(tmp_path):
    written = write_transcript_exports(
        run_dir=tmp_path,
        metadata=_metadata(),
        transcript=_transcript(),
    )

    assert written == ["transcript.txt", "transcript.srt"]
    text = (tmp_path / "transcript.txt").read_text(encoding="utf-8")
    assert "测试视频" in text
    assert "Source: whisper" in text
    assert "[00:00] Hello 大家好" in text

    srt = (tmp_path / "transcript.srt").read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:02,180\nHello 大家好" in srt
    assert "2\n00:01:02,500 --> 00:01:05,000\n第二段" in srt


def test_write_notes_markdown_uses_learning_note_structure(tmp_path):
    written = write_notes_markdown(
        run_dir=tmp_path,
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
    )

    assert written == ["notes.md"]
    markdown = (tmp_path / "notes.md").read_text(encoding="utf-8")
    assert markdown.startswith("# 测试视频")
    assert "- UP: UP" in markdown
    assert "## 目录" in markdown
    assert "## 1. 开场" in markdown
    assert "> 关键句" in markdown
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_exports.py -q
```

Expected: FAIL because `bilifan.exports` does not exist.

- [ ] **Step 3: Implement `src/bilifan/exports.py`**

Implement these public functions:

```python
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ExportError(RuntimeError):
    pass


def write_transcript_exports(
    *,
    run_dir: Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    overwrite: bool = False,
) -> list[str]:
    text_path = run_dir / "transcript.txt"
    srt_path = run_dir / "transcript.srt"
    if overwrite or not text_path.exists():
        text_path.write_text(render_transcript_text(metadata, transcript), encoding="utf-8")
    if overwrite or not srt_path.exists():
        srt_path.write_text(render_transcript_srt(transcript), encoding="utf-8")
    return ["transcript.txt", "transcript.srt"]


def write_notes_markdown(
    *,
    run_dir: Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    overwrite: bool = False,
) -> list[str]:
    notes_path = run_dir / "notes.md"
    if overwrite or not notes_path.exists():
        notes_path.write_text(
            render_notes_markdown(metadata, transcript, chapters),
            encoding="utf-8",
        )
    return ["notes.md"]
```

The implementation must also include:

- `render_transcript_text(metadata, transcript) -> str`
- `render_transcript_srt(transcript) -> str`
- `render_notes_markdown(metadata, transcript, chapters) -> str`
- `format_srt_timestamp(seconds) -> str`
- `_format_short_time(seconds) -> str`
- `_segments(transcript) -> list[dict[str, Any]]`
- `_text(value) -> str`
- `_string_list(value) -> list[str]`

SRT output must end with a trailing newline. Markdown output must end with a trailing newline.

- [ ] **Step 4: Run export tests and verify pass**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_exports.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/bilifan/exports.py tests/test_exports.py
git commit -m "feat: add transcript and notes exports"
```

## Task 2: Whisper Language Selection

**Files:**
- Modify: `src/bilifan/transcript.py`
- Modify: `tests/test_transcript.py`

- [ ] **Step 1: Write failing language tests**

Add tests to `tests/test_transcript.py`:

```python
def test_choose_whisper_model_respects_explicit_language():
    metadata = {"title": "中文标题", "part_title": "英语原声"}

    assert choose_whisper_model(metadata, language="zh") == ("turbo", "zh")
    assert choose_whisper_model(metadata, language="en") == ("small.en", "en")


def test_choose_whisper_model_auto_detects_english_from_mixed_metadata():
    assert choose_whisper_model(
        {
            "title": "只需 30 分钟即可构建您自己的应用程序！吴恩达完整课程 - DeepLearningAI",
            "part_title": "英语原声",
            "description": "Andrew Ng course",
            "tags": ["Andrew Ng", "AI课程"],
        },
        language="auto",
    ) == ("small.en", "en")


def test_build_transcript_passes_language_preference_to_whisper(tmp_path):
    audio = tmp_path / ".bilifan" / "cache" / "sample.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"audio")
    calls = []

    def fake_transcriber(audio_path, *, model_name, language):
        calls.append((audio_path, model_name, language))
        return [{"start": 0, "end": 1, "text": "I'm Andrew Ng"}]

    transcript = build_transcript(
        {"title": "中文标题", "part_title": "英语原声"},
        {"audio_path": ".bilifan/cache/sample.mp3", "duration_seconds": 1},
        tmp_path,
        force_whisper=True,
        language="en",
        whisper_transcriber=fake_transcriber,
    )

    assert transcript["model"] == "small.en"
    assert transcript["language"] == "en"
    assert calls[0][1:] == ("small.en", "en")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_transcript.py -q
```

Expected: FAIL because `choose_whisper_model` and `build_transcript` do not accept `language`.

- [ ] **Step 3: Implement language preference**

Modify signatures:

```python
def build_transcript(
    metadata: dict[str, Any],
    media: dict[str, Any],
    run_dir: Path,
    *,
    force_whisper: bool = False,
    transcriber: str = "auto",
    language: str = "auto",
    subtitle_fetcher=None,
    whisper_transcriber=None,
) -> dict[str, Any]:
    if language not in {"auto", "zh", "en"}:
        raise TranscriptError(f"Unsupported language: {language}")
    model_name, whisper_language = choose_whisper_model(metadata, language=language)
```

Modify selector:

```python
def choose_whisper_model(
    metadata: dict[str, Any],
    *,
    language: str = "auto",
) -> tuple[str, str]:
    if language == "zh":
        return "turbo", "zh"
    if language == "en":
        return "small.en", "en"
    if language != "auto":
        raise TranscriptError(f"Unsupported language: {language}")

    text = " ".join(
        [
            _first_text(metadata.get("part_title")),
            _first_text(metadata.get("title")),
            _first_text(metadata.get("description")),
            " ".join(_string_list(metadata.get("tags"))),
            _subtitle_language_text(metadata),
        ]
    )
    if _looks_english_metadata(text):
        return "small.en", "en"
    return "turbo", "zh"
```

Add helpers:

```python
def _string_list(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _subtitle_language_text(metadata: dict[str, Any]) -> str:
    subtitles = metadata.get("subtitles")
    if not isinstance(subtitles, list):
        return ""
    return " ".join(_first_text(item.get("language")) for item in subtitles if isinstance(item, dict))


def _looks_english_metadata(text: str) -> bool:
    lowered = text.lower()
    english_signals = ("英语原声", "英文", "english", "andrew ng", "deeplearningai")
    if any(signal in lowered for signal in english_signals):
        return True
    return bool(text) and not _contains_cjk(text) and _ascii_letter_ratio(text) >= 0.8
```

- [ ] **Step 4: Run transcript tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_transcript.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/bilifan/transcript.py tests/test_transcript.py
git commit -m "feat: add whisper language selection"
```

## Task 3: Pipeline and CLI Integration

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `src/bilifan/cli.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing pipeline tests**

Add or update tests in `tests/test_pipeline.py` so a successful fake run asserts:

```python
assert (run_dir / "transcript.txt").is_file()
assert (run_dir / "transcript.srt").is_file()
assert (run_dir / "notes.md").is_file()
assert "transcript.txt" in result.artifact_paths
assert "transcript.srt" in result.artifact_paths
assert "notes.md" in result.artifact_paths
```

Add a failure-after-transcript case:

```python
def _install_successful_pipeline_fakes(monkeypatch, *, summarize_chunks):
    def fake_fetch_current_part_metadata(url, **kwargs):
        return {
            "bvid": "BV1abcDEF12G",
            "page": 1,
            "title": "测试视频",
            "part_title": "P1",
            "owner_name": "UP",
            "duration": 12,
            "input_url_sanitized": url,
        }

    def fake_download_current_part_audio(metadata, run_dir, **kwargs):
        audio_path = run_dir / "audio.m4a"
        audio_path.write_text("audio", encoding="utf-8")
        return {"path": str(audio_path), "duration": 12, "duration_mismatch": False}

    def fake_build_transcript(metadata, media, run_dir, **kwargs):
        return {
            "source": "whisper",
            "model": "turbo",
            "language": "zh",
            "segments": [{"start": 0, "end": 3, "text": "测试逐字稿"}],
            "transcript_check": {"status": "ok"},
        }

    def fake_build_chunks(transcript, metadata, **kwargs):
        return {"chunks": [{"chunk_index": 1, "start": 0, "end": 3, "text": "测试逐字稿"}]}

    def fake_render_report_html(**kwargs):
        report = kwargs["run_dir"] / "report.html"
        report.write_text("<html><body>ok</body></html>", encoding="utf-8")
        return report

    def fake_export_report_pdf(*, html_path, require_pdf=False):
        pdf_path = html_path.with_suffix(".pdf")
        pdf_path.write_text("pdf", encoding="utf-8")
        return {"path": pdf_path, "warnings": []}

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(pipeline, "export_report_pdf", fake_export_report_pdf)
    monkeypatch.setattr(pipeline, "summarize_chunks", summarize_chunks)


def test_summarization_failure_keeps_transcript_exports_in_artifacts(tmp_path, monkeypatch):
    def fake_summarize_chunks(**kwargs):
        raise pipeline.SummarizationError("codex exec failed")

    _install_successful_pipeline_fakes(
        monkeypatch,
        summarize_chunks=fake_summarize_chunks,
    )
    request = PipelineRequest(
        url="https://www.bilibili.com/video/BV1abcDEF12G",
        out=tmp_path,
        yes_i_understand=True,
    )

    with pytest.raises(PipelineRunError) as exc_info:
        pipeline.run_summarize_pipeline(request)

    assert "transcript.txt" in exc_info.value.artifact_paths
    assert "transcript.srt" in exc_info.value.artifact_paths
```

- [ ] **Step 2: Write failing CLI language test**

Add to `tests/test_cli.py`:

```python
def test_summarize_passes_language_option_to_pipeline(monkeypatch, tmp_path):
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request)
        diagnostics = tmp_path / "diagnostics.json"
        diagnostics.write_text("{}", encoding="utf-8")
        return cli.PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=tmp_path,
            diagnostics_path=diagnostics,
            artifact_paths=["report.html"],
            warnings=[],
        )

    monkeypatch.setattr(cli, "run_summarize_pipeline", fake_pipeline)
    result = runner.invoke(
        cli.app,
        [
            "--yes-i-understand",
            "summarize",
            "https://www.bilibili.com/video/BV1abcDEF12G",
            "--out",
            str(tmp_path),
            "--language",
            "en",
        ],
    )

    assert result.exit_code == 0
    assert calls[0].language == "en"
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_cli.py -q
```

Expected: FAIL because `PipelineRequest.language` and CLI `--language` do not exist.

- [ ] **Step 4: Add pipeline request field and CLI option**

In `PipelineRequest` add:

```python
language: str = "auto"
```

When building transcript:

```python
transcript = build_transcript(
    metadata,
    media,
    run.run_dir,
    force_whisper=request.force_whisper,
    transcriber=request.transcriber,
    language=request.language,
)
```

In `cli.py` add Typer option:

```python
language: str = typer.Option("auto", "--language")
```

and pass `language=language` into `PipelineRequest`.

- [ ] **Step 5: Write transcript exports in pipeline**

After `_write_json(run.run_dir / "transcript.json", transcript)` call:

```python
transcript_export_artifacts: list[str] = []
try:
    transcript_export_artifacts = write_transcript_exports(
        run_dir=run.run_dir,
        metadata=metadata,
        transcript=transcript,
    )
except ExportError as exc:
    transcript_export_warning = "transcript_export_failed"
```

Add successful artifacts to later `artifact_paths`. On later failures after transcript, include:

```python
"transcript.json",
*transcript_export_artifacts,
```

- [ ] **Step 6: Write notes export in pipeline**

After `_write_json(run.run_dir / "chapters.json", chapters)` call:

```python
notes_artifacts: list[str] = []
try:
    notes_artifacts = write_notes_markdown(
        run_dir=run.run_dir,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
    )
except ExportError:
    render_warnings.append("notes_export_failed")
```

Add `"notes.md"` to final render artifacts when written.

- [ ] **Step 7: Run pipeline and CLI tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 3**

```bash
git add src/bilifan/pipeline.py src/bilifan/cli.py tests/test_pipeline.py tests/test_cli.py
git commit -m "feat: export transcript artifacts from pipeline"
```

## Task 4: Web API Artifacts and Open Folder

**Files:**
- Modify: `src/bilifan/web/files.py`
- Modify: `src/bilifan/web/jobs.py`
- Modify: `src/bilifan/web/app.py`
- Modify: `tests/test_web_history_files.py`
- Modify: `tests/test_web_jobs.py`

- [ ] **Step 1: Write failing artifact-link tests**

Update fixture runs in Web tests to create `transcript.txt`, `transcript.srt`, and `notes.md`.

Assert history artifacts:

```python
assert items[0]["artifacts"]["txt"].endswith("/files/transcript.txt")
assert items[0]["artifacts"]["srt"].endswith("/files/transcript.srt")
assert items[0]["artifacts"]["md"].endswith("/files/notes.md")
assert items[0]["artifacts"]["folder"].endswith("/open-folder")
```

Assert file list includes:

```python
assert "transcript.txt" in files
assert "transcript.srt" in files
assert "notes.md" in files
```

- [ ] **Step 2: Write failing open-folder endpoint tests**

In `tests/test_web_jobs.py` add tests using monkeypatch:

```python
from subprocess import CompletedProcess


def test_open_folder_endpoint_requires_token(tmp_path):
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)
    response = client.post("/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder")
    assert response.status_code == 403


def test_open_folder_endpoint_opens_safe_run_dir(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    run_dir = outputs / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
    run_dir.mkdir(parents=True)
    opened = []

    monkeypatch.setattr("bilifan.web.files.platform.system", lambda: "Darwin")
    monkeypatch.setattr("bilifan.web.files.subprocess.run", lambda cmd, **kwargs: opened.append(cmd) or CompletedProcess(cmd, 0, "", ""))

    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder?token=test-token"
    )

    assert response.status_code == 200
    assert opened == [["open", str(run_dir.resolve())]]
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_history_files.py tests/test_web_jobs.py -q
```

Expected: FAIL because new artifacts and endpoint do not exist.

- [ ] **Step 4: Add artifact names and links**

In `ROOT_FILES` add:

```python
"transcript.txt",
"transcript.srt",
"notes.md",
```

In `_artifact_links` add:

```python
if _safe_existing_file(run_dir, "transcript.txt") is not None:
    artifacts["txt"] = f"{prefix}/transcript.txt"
if _safe_existing_file(run_dir, "transcript.srt") is not None:
    artifacts["srt"] = f"{prefix}/transcript.srt"
if _safe_existing_file(run_dir, "notes.md") is not None:
    artifacts["md"] = f"{prefix}/notes.md"
artifacts["folder"] = f"/api/runs/{run_key}/open-folder"
```

Mirror the same keys in `src/bilifan/web/jobs.py::_artifact_links`.

- [ ] **Step 5: Implement safe folder opening**

In `src/bilifan/web/files.py` add:

```python
import platform
import subprocess


def open_run_folder(outputs: Path, output_id: str, run_id: str) -> None:
    run_dir = _run_dir(outputs, output_id, run_id)
    resolved_outputs = outputs.resolve(strict=False)
    resolved_run_dir = run_dir.resolve(strict=True)
    if not resolved_run_dir.is_relative_to(resolved_outputs):
        raise ValueError("Run resolves outside outputs.")
    if not resolved_run_dir.is_dir():
        raise FileNotFoundError("Run folder was not found.")
    if platform.system() != "Darwin":
        raise RuntimeError("Opening folders is only supported on macOS in this MVP.")
    result = subprocess.run(
        ["open", str(resolved_run_dir)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError("macOS open command failed.")
```

- [ ] **Step 6: Add endpoint**

In `src/bilifan/web/app.py` import `open_run_folder` and add:

```python
@app.post("/api/runs/{output_id}/runs/{run_id}/open-folder")
def open_folder(
    output_id: str,
    run_id: str,
    _: None = Depends(require_token),
) -> dict[str, bool]:
    try:
        open_run_folder(outputs, output_id, run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}
```

- [ ] **Step 7: Run Web API tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_history_files.py tests/test_web_jobs.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 4**

```bash
git add src/bilifan/web/files.py src/bilifan/web/jobs.py src/bilifan/web/app.py tests/test_web_history_files.py tests/test_web_jobs.py
git commit -m "feat: expose export artifacts in web api"
```

## Task 5: Web UI Controls and Actions

**Files:**
- Modify: `src/bilifan/web/app.py`
- Modify: `src/bilifan/web/ui.py`
- Modify: `tests/test_web_ui.py`
- Modify: `tests/test_web_jobs.py`

- [ ] **Step 1: Write failing Web payload/default tests**

Assert config defaults include:

```python
assert response.json()["defaults"]["language"] == "auto"
```

Assert job creation passes language:

```python
assert calls[0].language == "en"
```

- [ ] **Step 2: Write failing UI tests**

Add assertions:

```python
html = render_app_html()
assert 'id="language-select"' in html
assert "只影响 Whisper；已有字幕默认优先使用。" in html
assert "open-folder" in html
assert "TXT" in html
assert "SRT" in html
assert "MD" in html
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_ui.py tests/test_web_jobs.py -q
```

Expected: FAIL because language UI and open-folder JS do not exist.

- [ ] **Step 4: Add language defaults and payload**

In `WEB_DEFAULTS` add:

```python
"language": "auto",
```

In `JobCreatePayload` add:

```python
language: str = WEB_DEFAULTS["language"]
```

In `PipelineRequest` creation pass:

```python
language=payload.language,
```

- [ ] **Step 5: Add Web UI language select**

Add a select near Force Whisper:

```html
<label class="field" for="language-select">
  <span>语言</span>
  <select id="language-select" name="language">
    <option value="auto">auto</option>
    <option value="zh">中文</option>
    <option value="en">英文</option>
  </select>
  <span class="hint">只影响 Whisper；已有字幕默认优先使用。</span>
</label>
```

Add element binding:

```javascript
languageSelect: document.getElementById("language-select"),
```

Load default:

```javascript
elements.languageSelect.value = defaults.language || "auto";
```

Submit payload:

```javascript
language: elements.languageSelect.value,
```

- [ ] **Step 6: Render new artifact actions**

Update `renderLinks` and `renderHistory`:

```javascript
if (artifacts.txt) links.push(linkItem("TXT", artifacts.txt));
if (artifacts.srt) links.push(linkItem("SRT", artifacts.srt));
if (artifacts.md) links.push(linkItem("MD", artifacts.md));
if (artifacts.folder) links.push(folderButton("打开本地文件夹", artifacts.folder));
```

Add:

```javascript
function folderButton(label, href) {
  return `<button class="link-button" type="button" data-folder-url="${escapeAttr(withToken(href))}">${escapeHtml(label)}</button>`;
}

async function openFolder(url) {
  await apiFetch(url, { method: "POST" });
  setJobMessage("已请求打开本地文件夹。");
}
```

Attach delegated click listener in `init`:

```javascript
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-folder-url]");
  if (!target) return;
  openFolder(target.getAttribute("data-folder-url")).catch((error) => {
    setJobMessage(error.message || "打开文件夹失败。", true);
  });
});
```

- [ ] **Step 7: Run Web UI tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_ui.py tests/test_web_jobs.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add src/bilifan/web/app.py src/bilifan/web/ui.py tests/test_web_ui.py tests/test_web_jobs.py
git commit -m "feat: add language and folder actions to web ui"
```

## Task 6: Backfill, Verification, and Documentation

**Files:**
- Modify: `README.md`
- Use local `outputs/` for one-off backfill.

- [ ] **Step 1: Update README**

Document:

```markdown
- `--language auto|zh|en`: controls Whisper fallback language/model selection. Bilibili subtitles are still preferred unless `--force-whisper` is used.
- Runs may include `transcript.txt`, `transcript.srt`, and `notes.md` in addition to JSON intermediates and reports.
- The local Web UI can open a run folder on macOS.
```

- [ ] **Step 2: Run full tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: all tests pass.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: One-off backfill existing local runs**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import json
from pathlib import Path

from bilifan.exports import write_notes_markdown, write_transcript_exports

outputs = Path("outputs")
written = 0
skipped = 0
failed = 0

for run_dir in sorted(outputs.glob("*/runs/*")):
    if not run_dir.is_dir():
        continue
    try:
        metadata_path = run_dir / "metadata.json"
        transcript_path = run_dir / "transcript.json"
        chapters_path = run_dir / "chapters.json"
        metadata = (
            json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata_path.is_file()
            else {}
        )
        if transcript_path.is_file():
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            before = {
                "transcript.txt": (run_dir / "transcript.txt").is_file(),
                "transcript.srt": (run_dir / "transcript.srt").is_file(),
            }
            write_transcript_exports(
                run_dir=run_dir,
                metadata=metadata,
                transcript=transcript,
                overwrite=False,
            )
            written += sum(
                1
                for name, existed in before.items()
                if not existed and (run_dir / name).is_file()
            )
        if metadata_path.is_file() and transcript_path.is_file() and chapters_path.is_file():
            transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
            chapters = json.loads(chapters_path.read_text(encoding="utf-8"))
            existed = (run_dir / "notes.md").is_file()
            write_notes_markdown(
                run_dir=run_dir,
                metadata=metadata,
                transcript=transcript,
                chapters=chapters,
                overwrite=False,
            )
            if not existed and (run_dir / "notes.md").is_file():
                written += 1
        if not transcript_path.is_file() and not chapters_path.is_file():
            skipped += 1
    except Exception as exc:
        failed += 1
        print(f"failed {run_dir}: {exc}")

print(f"written={written} skipped={skipped} failed={failed}")
PY
```

Expected: command exits 0 and does not overwrite existing files.

Expected current successful runs to gain:

```text
transcript.txt
transcript.srt
notes.md
```

- [ ] **Step 5: Verify backfilled files**

Run:

```bash
find outputs -maxdepth 4 -type f \( -name transcript.txt -o -name transcript.srt -o -name notes.md \) | sort
```

Expected: files appear under successful historical run directories.

- [ ] **Step 6: Run Web smoke**

Start:

```bash
.venv/bin/python -m bilifan serve --no-open --port 8792
```

Open the tokenized local URL. Verify:

- Language select is visible.
- History cards show TXT/SRT/MD when present.
- `打开本地文件夹` returns success on macOS.
- Existing report links still work.

Stop the server after smoke.

- [ ] **Step 7: Commit Task 6**

```bash
git add README.md
git commit -m "docs: document export and language options"
```

- [ ] **Step 8: Push branch**

```bash
git push origin codex/bilifan-foundation
```

Expected: remote branch updates successfully.

## Final Acceptance Criteria

- New runs generate `transcript.txt`, `transcript.srt`, and `notes.md` at the correct stages.
- Existing local history has been backfilled once.
- CLI accepts `--language auto|zh|en`.
- Web UI sends `language` and shows language selection.
- Web UI shows TXT/SRT/MD links when files exist.
- Web UI can open a run folder on macOS using a token-protected endpoint.
- Folder endpoint cannot open arbitrary paths or symlink escapes.
- Full test suite passes.
- Branch is pushed.
