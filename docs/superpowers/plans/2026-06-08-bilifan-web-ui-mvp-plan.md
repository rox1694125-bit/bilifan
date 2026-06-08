# Bilifan Web UI MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `bilifan serve`, a local browser workbench for starting one Bilifan summary job, viewing stage progress, and opening generated report artifacts.

**Architecture:** Extract the current `bilifan summarize` flow into a shared `pipeline.py` API, then call that same API from both Typer CLI and a local FastAPI server. The Web UI uses one in-memory job manager, token-protected local endpoints, 1-second polling, a compact single-page frontend, and whitelisted file serving under `./outputs`.

**Tech Stack:** Python 3.11+, Typer, FastAPI, uvicorn, Jinja2, pytest, FastAPI TestClient/httpx, existing Bilifan metadata/media/transcript/chunking/summarizer/renderer modules.

---

## File Structure

- Modify `pyproject.toml`: add runtime dependencies `fastapi` and `uvicorn`; add dev dependency `httpx` for FastAPI tests.
- Modify `src/bilifan/config.py`: allow `accepted_via="web-ui"` for local-processing consent written from the Web UI.
- Create `src/bilifan/pipeline.py`: shared summary pipeline dataclasses, stage callback, success/failure handling, and artifact result.
- Modify `src/bilifan/cli.py`: keep Typer commands, delegate `summarize` to `pipeline.run_summarize_pipeline`, add `serve`.
- Create `src/bilifan/web/__init__.py`: package marker.
- Create `src/bilifan/web/security.py`: token generation and validation helpers.
- Create `src/bilifan/web/files.py`: safe run-key parsing, history scanning, whitelisted file lookup.
- Create `src/bilifan/web/jobs.py`: in-memory single-job manager and stage progress state.
- Create `src/bilifan/web/app.py`: FastAPI app factory, API routes, static HTML route, file routes.
- Create `src/bilifan/web/ui.py`: render the compact workbench HTML with inline CSS/JS.
- Create `tests/test_pipeline.py`: shared pipeline behavior with mocked stage functions.
- Create `tests/test_web_security.py`: token and file-path safety.
- Create `tests/test_web_history_files.py`: history and artifact route behavior.
- Create `tests/test_web_jobs.py`: job manager and API job lifecycle.
- Create `tests/test_web_ui.py`: HTML contract tests.
- Modify `tests/test_config.py`: verify Web UI consent source is accepted and persisted.
- Modify `tests/test_cli.py`: update mocks after pipeline extraction and add `serve` command tests.
- Modify `README.md`: document `bilifan serve`.

Keep `.superpowers/` ignored. Do not add visual companion files.

## Task 1: Dependencies and Pipeline Types

**Files:**
- Modify: `pyproject.toml`
- Create: `src/bilifan/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Add failing tests for pipeline request/result types**

Add `tests/test_pipeline.py`:

```python
from pathlib import Path

from bilifan.pipeline import (
    PipelineRequest,
    PipelineResult,
    PipelineStage,
    default_progress,
)


def test_pipeline_request_defaults_for_web_and_cli(tmp_path):
    request = PipelineRequest(url="https://www.bilibili.com/video/BV1abcDEF12G", out=tmp_path)

    assert request.output_format == "html,pdf"
    assert request.transcriber == "auto"
    assert request.force_whisper is False
    assert request.llm_provider == "codex-exec"
    assert request.llm_model == "gpt-5.5"
    assert request.require_pdf is False
    assert request.allow_long_video is False
    assert request.yes_i_understand is False
    assert request.overwrite is False
    assert request.cookies_from_browser is None
    assert request.cookies_file is None


def test_pipeline_result_uses_relative_run_key(tmp_path):
    result = PipelineResult(
        run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
        run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
        diagnostics_path=tmp_path / "diagnostics.json",
        artifact_paths=["report.html"],
        warnings=[],
    )

    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert result.artifact_paths == ["report.html"]


def test_default_progress_accepts_all_known_stages():
    for stage in PipelineStage:
        default_progress(stage.value, "running", f"{stage.value} running")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'bilifan.pipeline'`.

- [ ] **Step 3: Add dependencies**

Run:

```bash
UV_CACHE_DIR=/private/tmp/bilifan-uv-cache uv add fastapi uvicorn --no-config --default-index https://pypi.org/simple
UV_CACHE_DIR=/private/tmp/bilifan-uv-cache uv add --dev httpx --no-config --default-index https://pypi.org/simple
```

Expected: `pyproject.toml` contains `fastapi`, `uvicorn`, and dev `httpx`; `uv.lock` is updated without Aliyun mirror URLs.

- [ ] **Step 4: Create initial pipeline module**

Create `src/bilifan/pipeline.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PipelineStage(str, Enum):
    PREFLIGHT = "preflight"
    METADATA = "metadata"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    CHUNKING = "chunking"
    SUMMARIZATION = "summarization"
    RENDER = "render"


ProgressCallback = Callable[[str, str, str], None]


@dataclass(frozen=True)
class PipelineRequest:
    url: str
    out: Path
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    output_format: str = "html,pdf"
    transcriber: str = "auto"
    force_whisper: bool = False
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    require_pdf: bool = False
    allow_long_video: bool = False
    yes_i_understand: bool = False
    overwrite: bool = False


@dataclass(frozen=True)
class PipelineResult:
    run_key: str
    run_dir: Path
    diagnostics_path: Path
    artifact_paths: list[str]
    warnings: list[str]


def default_progress(stage: str, status: str, message: str) -> None:
    return None
```

- [ ] **Step 5: Run tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add pyproject.toml uv.lock src/bilifan/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline types for web ui"
```

## Task 2: Extract Shared Pipeline While Preserving CLI

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `src/bilifan/cli.py`
- Modify: `tests/test_cli.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Add failing pipeline success test with mocked stage functions**

Append to `tests/test_pipeline.py`:

```python
import json

from bilifan.bilibili import BilibiliPartRef
import bilifan.pipeline as pipeline


def test_run_summarize_pipeline_writes_artifacts_and_reports_progress(tmp_path, monkeypatch):
    events = []

    def fake_metadata(ref, run_dir, *, cookies_from_browser=None, cookies_file=None):
        return {
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "title": "Mock title",
            "part_title": "Mock part",
            "owner_name": "Mock owner",
            "description": "",
            "tags": [],
            "cover_path": "",
            "duration": 120,
            "subtitles": [],
            "metadata_source": "mock",
        }

    def fake_audio(ref, metadata, run_dir, *, cookies_from_browser=None, cookies_file=None):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {"status": "ok"},
        }

    def fake_transcript(metadata, media, run_dir, *, force_whisper=False, transcriber="auto"):
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0, "end": 120, "text": "转写", "language": "zh", "source": "whisper"}],
            "transcript_check": {"status": "ok"},
        }

    def fake_chunks(transcript, media, *, allow_long_video=False, long_video_confirmed=False):
        return {
            "chunk_count": 1,
            "strategy": {"mode": "single_pass"},
            "chunks": [{"chunk_index": 1, "start": 0, "end": 120, "segments": [], "text": "转写"}],
        }

    def fake_summary(ref, metadata, chunks, run_dir, provider="codex-exec", model="gpt-5.5", style="学习笔记"):
        partial_dir = run_dir / "partial_summaries"
        partial_dir.mkdir(parents=True, exist_ok=True)
        (partial_dir / "chunk_001.json").write_text('{"chunk_index":1,"chapters":[]}', encoding="utf-8")
        return {
            "style": style,
            "chapters": [{
                "chapter_index": 1,
                "title": "开场",
                "start": 0,
                "end": 120,
                "timestamp_url": ref.timestamp_url(0),
                "summary": "摘要",
                "key_points": ["要点"],
                "quotes": [],
                "visual_anchors": [],
            }],
        }

    def fake_html(ref, metadata, transcript, chapters, run_dir):
        path = run_dir / "report.html"
        path.write_text("<html>report</html>", encoding="utf-8")
        return path

    def fake_pdf(html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_chunks)
    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summary)
    monkeypatch.setattr(pipeline, "render_report_html", fake_html)
    monkeypatch.setattr(pipeline, "export_report_pdf", fake_pdf)

    result = pipeline.run_summarize_pipeline(
        pipeline.PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            out=tmp_path / "outputs",
            yes_i_understand=True,
        ),
        progress_callback=lambda stage, status, message: events.append((stage, status, message)),
    )

    assert result.run_key.startswith("BV1abcDEF12G_p1/runs/")
    assert "report.html" in result.artifact_paths
    assert "report.pdf" in result.artifact_paths
    assert (result.run_dir / "metadata.json").is_file()
    assert (result.run_dir / "transcript.json").is_file()
    assert (result.run_dir / "chunks.json").is_file()
    assert (result.run_dir / "chapters.json").is_file()
    assert (result.run_dir / "diagnostics.json").is_file()
    assert [event[:2] for event in events if event[1] == "running"] == [
        ("preflight", "running"),
        ("metadata", "running"),
        ("audio", "running"),
        ("transcript", "running"),
        ("chunking", "running"),
        ("summarization", "running"),
        ("render", "running"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py::test_run_summarize_pipeline_writes_artifacts_and_reports_progress -q
```

Expected: FAIL with `AttributeError: module 'bilifan.pipeline' has no attribute 'run_summarize_pipeline'`.

- [ ] **Step 3: Move summarize body into `run_summarize_pipeline`**

In `src/bilifan/pipeline.py`, import the current helpers used by `cli.py` and add:

```python
def run_summarize_pipeline(
    request: PipelineRequest,
    *,
    progress_callback: ProgressCallback = default_progress,
) -> PipelineResult:
    progress_callback(PipelineStage.PREFLIGHT.value, "running", "Preparing run.")
    requested_formats = _parse_output_formats(request.output_format)
    should_export_pdf = "pdf" in requested_formats or request.require_pdf
    ref = parse_bilibili_url(request.url)
    run = create_run(request.out, ref, overwrite=request.overwrite)
    progress_callback(PipelineStage.PREFLIGHT.value, "done", "Run directory prepared.")

    progress_callback(PipelineStage.METADATA.value, "running", "Fetching metadata.")
    metadata = fetch_current_part_metadata(
        ref,
        run.run_dir,
        cookies_from_browser=request.cookies_from_browser,
        cookies_file=request.cookies_file,
    )
    _write_json(run.run_dir / "metadata.json", metadata)
    progress_callback(PipelineStage.METADATA.value, "done", "Metadata written.")

    progress_callback(PipelineStage.AUDIO.value, "running", "Downloading audio.")
    media = download_current_part_audio(
        ref,
        metadata,
        run.run_dir,
        cookies_from_browser=request.cookies_from_browser,
        cookies_file=request.cookies_file,
    )
    progress_callback(PipelineStage.AUDIO.value, "done", "Audio verified.")

    progress_callback(PipelineStage.TRANSCRIPT.value, "running", "Building transcript.")
    transcript = build_transcript(
        metadata,
        media,
        run.run_dir,
        force_whisper=request.force_whisper,
        transcriber=request.transcriber,
    )
    _write_json(run.run_dir / "transcript.json", transcript)
    progress_callback(PipelineStage.TRANSCRIPT.value, "done", "Transcript written.")

    progress_callback(PipelineStage.CHUNKING.value, "running", "Splitting transcript.")
    chunks = build_chunks(
        transcript,
        media,
        allow_long_video=request.allow_long_video,
        long_video_confirmed=request.yes_i_understand,
    )
    _write_json(run.run_dir / "chunks.json", chunks)
    progress_callback(PipelineStage.CHUNKING.value, "done", "Chunks written.")

    progress_callback(PipelineStage.SUMMARIZATION.value, "running", "Summarizing chunks.")
    chapters = summarize_chunks(
        ref=ref,
        metadata=metadata,
        chunks=chunks,
        run_dir=run.run_dir,
        provider=request.llm_provider,
        model=request.llm_model,
        style="学习笔记",
    )
    _write_json(run.run_dir / "chapters.json", chapters)
    progress_callback(PipelineStage.SUMMARIZATION.value, "done", "Chapters written.")

    progress_callback(PipelineStage.RENDER.value, "running", "Rendering report.")
    report_html = render_report_html(
        ref=ref,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        run_dir=run.run_dir,
    )
    warnings: list[str] = []
    artifacts = [
        "diagnostics.json",
        "metadata.json",
        media["audio_path"],
        "transcript.json",
        "chunks.json",
        "chapters.json",
        report_html.name,
    ]
    if should_export_pdf:
        try:
            report_pdf = export_report_pdf(html_path=report_html, pdf_path=run.run_dir / "report.pdf")
            artifacts.append(report_pdf.name)
        except PdfExportError as exc:
            if request.require_pdf:
                _write_success_or_failure_diagnostics(run, ref, media, transcript, artifacts, exc, ["pdf_failed"])
                progress_callback(PipelineStage.RENDER.value, "failed", str(exc))
                raise
            warnings.append("pdf_failed")
    if transcript["transcript_check"]["status"] == "transcript_incomplete":
        warnings.append("transcript_incomplete")
    _write_render_diagnostics(run, ref, media, transcript, artifacts, warnings)
    progress_callback(PipelineStage.RENDER.value, "done", "Report rendered.")
    return PipelineResult(
        run_key=_display_run_path(run),
        run_dir=run.run_dir,
        diagnostics_path=run.run_dir / "diagnostics.json",
        artifact_paths=artifacts,
        warnings=warnings,
    )
```

Move `_parse_output_formats`, `_write_json`, `_display_run_path`, `_partial_summary_artifacts`, and diagnostics-writing helpers from `cli.py` into `pipeline.py`. Keep the existing diagnostic JSON shape.

- [ ] **Step 4: Simplify CLI to delegate to pipeline**

In `src/bilifan/cli.py`, keep consent handling and Typer options, then replace the long body after consent with:

```python
    try:
        result = run_summarize_pipeline(
            PipelineRequest(
                url=url,
                out=out,
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                output_format=output_format,
                transcriber=transcriber,
                force_whisper=force_whisper,
                llm_provider=llm_provider,
                llm_model=llm_model,
                require_pdf=require_pdf,
                allow_long_video=allow_long_video,
                yes_i_understand=yes_i_understand,
                overwrite=overwrite,
            )
        )
    except ValueError as exc:
        raise typer.BadParameter(redact_text(str(exc))) from exc
    except (
        MetadataIngestError,
        MediaDownloadError,
        TranscriptError,
        ChunkingError,
        SummarizationError,
        PdfExportError,
    ) as exc:
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"Prepared Bilifan run: {result.run_key}")
```

Import `PipelineRequest` and `run_summarize_pipeline`. Remove imports that CLI no longer uses directly.

- [ ] **Step 5: Update CLI tests to monkeypatch pipeline**

In `tests/test_cli.py`, add a helper:

```python
from pathlib import Path
from bilifan.pipeline import PipelineResult


def _install_fake_pipeline(monkeypatch):
    calls = []

    def fake_run_summarize_pipeline(request, *, progress_callback=None):
        calls.append(request)
        run_dir = request.out / "BV1abcDEF12G_p2" / "runs" / "2026-06-08_120000"
        run_dir.mkdir(parents=True, exist_ok=True)
        return PipelineResult(
            run_key="BV1abcDEF12G_p2/runs/2026-06-08_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["report.html"],
            warnings=[],
        )

    monkeypatch.setattr(cli, "run_summarize_pipeline", fake_run_summarize_pipeline)
    return calls
```

Use this helper for CLI option-forwarding tests. Keep lower-level pipeline artifact tests in `tests/test_pipeline.py`.

- [ ] **Step 6: Run focused tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_cli.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/bilifan/pipeline.py src/bilifan/cli.py tests/test_pipeline.py tests/test_cli.py
git commit -m "refactor: share summarize pipeline"
```

## Task 3: Web Security, History, and File Access Helpers

**Files:**
- Create: `src/bilifan/web/__init__.py`
- Create: `src/bilifan/web/security.py`
- Create: `src/bilifan/web/files.py`
- Test: `tests/test_web_security.py`
- Test: `tests/test_web_history_files.py`

- [ ] **Step 1: Add failing security tests**

Create `tests/test_web_security.py`:

```python
import pytest

from bilifan.web.security import TokenAuth, generate_token


def test_generate_token_is_urlsafe_and_long_enough():
    token = generate_token()

    assert len(token) >= 32
    assert "/" not in token
    assert "+" not in token


def test_token_auth_accepts_matching_header_or_query():
    auth = TokenAuth("secret-token")

    auth.require(header_token="secret-token", query_token=None)
    auth.require(header_token=None, query_token="secret-token")


def test_token_auth_rejects_missing_or_wrong_token():
    auth = TokenAuth("secret-token")

    with pytest.raises(PermissionError):
        auth.require(header_token=None, query_token=None)
    with pytest.raises(PermissionError):
        auth.require(header_token="wrong", query_token=None)
```

- [ ] **Step 2: Add failing history/file tests**

Create `tests/test_web_history_files.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from bilifan.web.files import (
    list_latest_runs,
    list_run_files,
    resolve_run_file,
)


def _make_run(outputs, output_id="BV1abcDEF12G_p1", run_id="2026-06-08_120000", *, success=True):
    video_dir = outputs / output_id
    run_dir = video_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (video_dir / "latest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": f"runs/{run_id}",
                "generated_at": "2026-06-08T12:00:00+00:00",
                "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text('{"title":"Mock title"}', encoding="utf-8")
    (run_dir / "diagnostics.json").write_text(
        json.dumps({"error_type": None if success else "MetadataIngestError", "stage": "render" if success else "metadata"}),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"%PDF")
    partial_dir = run_dir / "partial_summaries"
    partial_dir.mkdir()
    (partial_dir / "chunk_001.json").write_text("{}", encoding="utf-8")
    return run_dir


def test_list_latest_runs_reads_outputs_latest_json(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    items = list_latest_runs(outputs)

    assert len(items) == 1
    assert items[0]["output_id"] == "BV1abcDEF12G_p1"
    assert items[0]["title"] == "Mock title"
    assert items[0]["status"] == "succeeded"
    assert items[0]["stage"] == "render"
    assert items[0]["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"


def test_list_run_files_only_includes_whitelisted_files(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    run_dir = outputs / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
    (run_dir / "secret.txt").write_text("no", encoding="utf-8")

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "metadata.json" in files
    assert "report.html" in files
    assert "partial_summaries/chunk_001.json" in files
    assert "secret.txt" not in files


@pytest.mark.parametrize("file_path", ["../metadata.json", "/tmp/secret", "partial_summaries/../metadata.json", "a\\\\b"])
def test_resolve_run_file_rejects_unsafe_paths(tmp_path, file_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    with pytest.raises(ValueError):
        resolve_run_file(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000", file_path)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_security.py tests/test_web_history_files.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'bilifan.web'`.

- [ ] **Step 4: Implement security helpers**

Create `src/bilifan/web/__init__.py` as an empty file.

Create `src/bilifan/web/security.py`:

```python
from __future__ import annotations

import secrets
from dataclasses import dataclass


def generate_token() -> str:
    return secrets.token_urlsafe(32)


@dataclass(frozen=True)
class TokenAuth:
    token: str

    def require(self, *, header_token: str | None, query_token: str | None) -> None:
        candidate = header_token or query_token
        if not candidate or not secrets.compare_digest(candidate, self.token):
            raise PermissionError("Invalid Bilifan Web UI token.")
```

- [ ] **Step 5: Implement file/history helpers**

Create `src/bilifan/web/files.py`:

```python
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any


OUTPUT_ID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}_p[1-9][0-9]*")
RUN_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}")
ROOT_FILES = {
    "metadata.json",
    "transcript.json",
    "chunks.json",
    "chapters.json",
    "diagnostics.json",
    "report.html",
    "report.pdf",
}


def list_latest_runs(outputs: Path) -> list[dict[str, Any]]:
    if not outputs.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for latest_path in sorted(outputs.glob("*/latest.json")):
        output_id = latest_path.parent.name
        if OUTPUT_ID_PATTERN.fullmatch(output_id) is None:
            continue
        try:
            latest = json.loads(latest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        run_id = _run_id_from_latest(latest)
        if not run_id:
            continue
        run_dir = outputs / output_id / "runs" / run_id
        diagnostics = _read_json_object(run_dir / "diagnostics.json")
        metadata = _read_json_object(run_dir / "metadata.json")
        status = "failed" if diagnostics.get("error_type") else "succeeded"
        items.append(
            {
                "run_key": f"{output_id}/runs/{run_id}",
                "output_id": output_id,
                "run_id": run_id,
                "title": _text(metadata.get("title")) or output_id,
                "status": status,
                "stage": _text(diagnostics.get("stage")),
                "generated_at": _text(latest.get("generated_at")),
                "artifacts": _artifact_names(run_dir),
            }
        )
    return sorted(items, key=lambda item: item["generated_at"], reverse=True)


def list_run_files(outputs: Path, output_id: str, run_id: str) -> list[str]:
    run_dir = _run_dir(outputs, output_id, run_id)
    files = [name for name in sorted(ROOT_FILES) if (run_dir / name).is_file()]
    partial_dir = run_dir / "partial_summaries"
    if partial_dir.is_dir():
        files.extend(
            f"partial_summaries/{path.name}"
            for path in sorted(partial_dir.glob("*.json"))
            if path.is_file()
        )
    return files


def resolve_run_file(outputs: Path, output_id: str, run_id: str, file_path: str) -> Path:
    if "\\" in file_path:
        raise ValueError("Invalid file path.")
    posix = PurePosixPath(file_path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Invalid file path.")
    if file_path not in ROOT_FILES and not (
        len(posix.parts) == 2
        and posix.parts[0] == "partial_summaries"
        and posix.parts[1].startswith("chunk_")
        and posix.parts[1].endswith(".json")
    ):
        raise ValueError("File is not a Bilifan artifact.")
    run_dir = _run_dir(outputs, output_id, run_id)
    resolved = (run_dir / file_path).resolve(strict=False)
    if not resolved.is_relative_to(run_dir.resolve(strict=False)):
        raise ValueError("File resolves outside run directory.")
    if not resolved.is_file():
        raise FileNotFoundError(file_path)
    return resolved


def _run_dir(outputs: Path, output_id: str, run_id: str) -> Path:
    if OUTPUT_ID_PATTERN.fullmatch(output_id) is None or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("Invalid run key.")
    run_dir = (outputs / output_id / "runs" / run_id).resolve(strict=False)
    if not run_dir.is_relative_to(outputs.resolve(strict=False)):
        raise ValueError("Run resolves outside outputs.")
    return run_dir


def _run_id_from_latest(latest: dict[str, Any]) -> str:
    run_id = _text(latest.get("run_id"))
    run_dir = _text(latest.get("run_dir"))
    if RUN_ID_PATTERN.fullmatch(run_id):
        return run_id
    if run_dir.startswith("runs/"):
        candidate = run_dir.removeprefix("runs/")
        if RUN_ID_PATTERN.fullmatch(candidate):
            return candidate
    return ""


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _artifact_names(run_dir: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    if (run_dir / "report.html").is_file():
        artifacts["html"] = "report.html"
    if (run_dir / "report.pdf").is_file():
        artifacts["pdf"] = "report.pdf"
    if (run_dir / "diagnostics.json").is_file():
        artifacts["diagnostics"] = "diagnostics.json"
    return artifacts


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
```

- [ ] **Step 6: Run tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_security.py tests/test_web_history_files.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

```bash
git add src/bilifan/web tests/test_web_security.py tests/test_web_history_files.py
git commit -m "feat: add web safety helpers"
```

## Task 4: Web App API and Job Manager

- **Files:**
- Modify: `src/bilifan/config.py`
- Modify: `tests/test_config.py`
- Create: `src/bilifan/web/jobs.py`
- Create: `src/bilifan/web/app.py`
- Test: `tests/test_web_jobs.py`

- [ ] **Step 1: Add failing config test for Web UI consent source**

Append to `tests/test_config.py`:

```python
def test_write_consent_accepts_web_ui_source(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"

    write_consent(config_path, local_processing=True, accepted_via="web-ui")

    assert read_config(config_path).accepted_via == "web-ui"
```

- [ ] **Step 2: Update accepted consent sources**

Modify `src/bilifan/config.py`:

```python
ALLOWED_ACCEPTED_VIA = frozenset({"cli", "prompt", "yes-i-understand", "test", "web-ui"})
```

- [ ] **Step 3: Add failing API/job tests**

Create `tests/test_web_jobs.py`:

```python
from pathlib import Path

from fastapi.testclient import TestClient

from bilifan.pipeline import PipelineResult
from bilifan.web.app import create_app


def _headers(token="test-token"):
    return {"X-Bilifan-Token": token}


def test_api_requires_token(tmp_path):
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 403


def test_config_and_consent_endpoints(tmp_path, monkeypatch):
    config_home = tmp_path / "config"
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(config_home))
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    before = client.get("/api/config", headers=_headers()).json()
    assert before["consent"]["local_processing"] is False

    response = client.post("/api/consent", headers=_headers())
    assert response.status_code == 200

    after = client.get("/api/config", headers=_headers()).json()
    assert after["consent"]["local_processing"] is True


def test_job_success_lifecycle(tmp_path):
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request)
        run_dir = request.out / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
        run_dir.mkdir(parents=True)
        (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
        (run_dir / "diagnostics.json").write_text('{"error_type": null, "stage": "render"}', encoding="utf-8")
        progress_callback("metadata", "running", "Fetching metadata.")
        progress_callback("metadata", "done", "Metadata written.")
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["report.html", "diagnostics.json"],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "format": "html",
            "force_whisper": False,
            "require_pdf": False,
            "allow_long_video": False,
        },
    )

    assert response.status_code == 200
    state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == "succeeded"
    assert state["stage"] == "render"
    assert state["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert state["progress"][0] == {"stage": "preflight", "status": "pending"}
    assert calls[0].output_format == "html"


def test_running_job_conflict(tmp_path):
    def fake_pipeline(request, *, progress_callback):
        progress_callback("metadata", "running", "still running")
        return None

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=False,
    )
    client = TestClient(app)

    payload = {
        "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "format": "html",
        "force_whisper": False,
        "require_pdf": False,
        "allow_long_video": False,
    }
    first = client.post("/api/jobs", headers=_headers(), json=payload)
    second = client.post("/api/jobs", headers=_headers(), json=payload)

    assert first.status_code == 200
    assert second.status_code == 409
```

- [ ] **Step 4: Run tests to verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_write_consent_accepts_web_ui_source tests/test_web_jobs.py -q
```

Expected: FAIL with invalid `accepted_via` for the config test and `ModuleNotFoundError` for `bilifan.web.app` or missing `JobManager`.

- [ ] **Step 5: Implement job manager**

Create `src/bilifan/web/jobs.py`:

```python
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from bilifan.diagnostics import redact_text
from bilifan.pipeline import PipelineRequest, PipelineResult


STAGES = ["preflight", "metadata", "audio", "transcript", "chunking", "summarization", "render"]


@dataclass
class JobState:
    job_id: str = ""
    status: str = "idle"
    stage: str = ""
    message: str = ""
    progress: list[dict[str, str]] = field(default_factory=lambda: [{"stage": stage, "status": "pending"} for stage in STAGES])
    run_key: str = ""
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress": self.progress,
            "run_key": self.run_key,
            "artifacts": self.artifacts,
            "warnings": self.warnings,
        }


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = JobState()

    def current(self) -> dict[str, Any]:
        with self._lock:
            return self._state.as_dict()

    def start(self, request: PipelineRequest, runner, *, inline: bool = False) -> str:
        with self._lock:
            if self._state.status == "running":
                raise RuntimeError("A Bilifan job is already running.")
            job_id = str(uuid.uuid4())
            self._state = JobState(job_id=job_id, status="running", message="Job started.")
        if inline:
            self._run(request, runner)
        else:
            thread = threading.Thread(target=self._run, args=(request, runner), daemon=True)
            thread.start()
        return job_id

    def progress(self, stage: str, status: str, message: str) -> None:
        with self._lock:
            self._state.stage = stage
            self._state.message = redact_text(message)
            for item in self._state.progress:
                if item["stage"] == stage:
                    item["status"] = status
                    break

    def _run(self, request: PipelineRequest, runner) -> None:
        try:
            result: PipelineResult = runner(request, progress_callback=self.progress)
        except Exception as exc:
            with self._lock:
                self._state.status = "failed"
                self._state.message = redact_text(str(exc))
                if self._state.stage:
                    for item in self._state.progress:
                        if item["stage"] == self._state.stage:
                            item["status"] = "failed"
                            break
            return
        with self._lock:
            self._state.status = "succeeded"
            self._state.stage = "render"
            self._state.message = "Report ready."
            self._state.run_key = result.run_key
            self._state.warnings = result.warnings
            self._state.artifacts = _artifact_links(result.run_key, result.artifact_paths)


def _artifact_links(run_key: str, artifact_paths: list[str]) -> dict[str, str]:
    prefix = f"/api/runs/{run_key}/files"
    artifacts: dict[str, str] = {}
    if "report.html" in artifact_paths:
        artifacts["html"] = f"{prefix}/report.html"
    if "report.pdf" in artifact_paths:
        artifacts["pdf"] = f"{prefix}/report.pdf"
    if "diagnostics.json" in artifact_paths:
        artifacts["diagnostics"] = f"{prefix}/diagnostics.json"
    return artifacts
```

- [ ] **Step 6: Implement FastAPI app factory**

Create `src/bilifan/web/app.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from bilifan.config import default_config_path, has_local_processing_consent, write_consent
from bilifan.pipeline import PipelineRequest, run_summarize_pipeline
from bilifan.web.files import list_latest_runs, list_run_files, resolve_run_file
from bilifan.web.jobs import JobManager
from bilifan.web.security import TokenAuth
from bilifan.web.ui import render_app_html


class JobCreateRequest(BaseModel):
    url: str
    format: str = "html,pdf"
    force_whisper: bool = False
    require_pdf: bool = False
    allow_long_video: bool = False


def create_app(
    *,
    outputs: Path,
    token: str,
    open_browser: bool = True,
    pipeline_runner: Callable = run_summarize_pipeline,
    run_jobs_inline: bool = False,
) -> FastAPI:
    app = FastAPI(title="Bilifan Local Web UI")
    auth = TokenAuth(token)
    jobs = JobManager()

    def require_token(
        x_bilifan_token: Annotated[str | None, Header()] = None,
        token_query: Annotated[str | None, Query(alias="token")] = None,
    ) -> None:
        try:
            auth.require(header_token=x_bilifan_token, query_token=token_query)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_app_html()

    @app.get("/api/config", dependencies=[Depends(require_token)])
    def config() -> dict:
        config_path = default_config_path()
        return {
            "consent": {"local_processing": has_local_processing_consent(config_path)},
            "defaults": {
                "format": "html,pdf",
                "force_whisper": False,
                "require_pdf": False,
                "allow_long_video": False,
            },
        }

    @app.post("/api/consent", dependencies=[Depends(require_token)])
    def consent() -> dict:
        write_consent(default_config_path(), local_processing=True, accepted_via="web-ui")
        return {"ok": True}

    @app.get("/api/history", dependencies=[Depends(require_token)])
    def history() -> dict:
        return {"items": list_latest_runs(outputs)}

    @app.post("/api/jobs", dependencies=[Depends(require_token)])
    def start_job(payload: JobCreateRequest) -> dict:
        request = PipelineRequest(
            url=payload.url,
            out=outputs,
            output_format=payload.format,
            force_whisper=payload.force_whisper,
            require_pdf=payload.require_pdf,
            allow_long_video=payload.allow_long_video,
            yes_i_understand=True,
            overwrite=False,
        )
        try:
            job_id = jobs.start(request, pipeline_runner, inline=run_jobs_inline)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"job_id": job_id, "status": "running"}

    @app.get("/api/jobs/current", dependencies=[Depends(require_token)])
    def current_job() -> dict:
        return jobs.current()

    @app.get("/api/runs/{output_id}/runs/{run_id}/files", dependencies=[Depends(require_token)])
    def run_files(output_id: str, run_id: str) -> dict:
        return {"files": list_run_files(outputs, output_id, run_id)}

    @app.get("/api/runs/{output_id}/runs/{run_id}/files/{file_path:path}", dependencies=[Depends(require_token)])
    def run_file(output_id: str, run_id: str, file_path: str) -> FileResponse:
        try:
            path = resolve_run_file(outputs, output_id, run_id, file_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Artifact not found.") from exc
        return FileResponse(path)

    return app
```

- [ ] **Step 7: Add temporary UI stub required by app import**

Create `src/bilifan/web/ui.py`:

```python
def render_app_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Bilifan</title></head>
<body><main id="app">Bilifan Web UI</main></body>
</html>"""
```

- [ ] **Step 8: Run API tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_config.py::test_write_consent_accepts_web_ui_source tests/test_web_jobs.py tests/test_web_security.py tests/test_web_history_files.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

Run:

```bash
git add src/bilifan/config.py src/bilifan/web tests/test_config.py tests/test_web_jobs.py
git commit -m "feat: add local web api"
```

## Task 5: Compact Workbench Frontend

**Files:**
- Modify: `src/bilifan/web/ui.py`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Add failing HTML contract tests**

Create `tests/test_web_ui.py`:

```python
from bilifan.web.ui import render_app_html


def test_render_app_html_contains_workbench_regions_and_controls():
    html = render_app_html()

    assert "Bilifan Web UI" in html
    assert 'id="history-list"' in html
    assert 'id="url-input"' in html
    assert 'id="format-select"' in html
    assert 'id="force-whisper"' in html
    assert 'id="require-pdf"' in html
    assert 'id="allow-long-video"' in html
    assert 'id="start-button"' in html
    assert 'id="stage-list"' in html
    assert 'id="result-links"' in html
    assert 'id="failure-panel"' in html
    assert "preflight" in html


def test_render_app_html_contains_polling_and_token_logic():
    html = render_app_html()

    assert "URLSearchParams" in html
    assert "X-Bilifan-Token" in html
    assert "/api/jobs/current" in html
    assert "setInterval" in html
    assert "/api/history" in html
    assert "/api/jobs" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_ui.py -q
```

Expected: FAIL because the stub lacks controls and polling logic.

- [ ] **Step 3: Replace UI stub with inline HTML/CSS/JS**

Modify `src/bilifan/web/ui.py`:

```python
def render_app_html() -> str:
    return """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bilifan Web UI</title>
  <style>
    :root { --ink:#1f2933; --muted:#667085; --line:#d8dee8; --panel:#f7f9fc; --accent:#0b6bcb; --danger:#b42318; }
    * { box-sizing: border-box; }
    body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--ink); background:#fff; }
    .shell { display:grid; grid-template-columns:280px minmax(0,1fr); min-height:100vh; }
    aside { border-right:1px solid var(--line); background:var(--panel); padding:18px; }
    main { padding:24px; max-width:980px; }
    h1 { font-size:20px; margin:0 0 16px; }
    h2 { font-size:16px; margin:0 0 12px; }
    label { display:block; font-size:13px; color:var(--muted); margin:12px 0 6px; }
    input, select { width:100%; padding:10px; border:1px solid var(--line); font:inherit; }
    button { padding:10px 14px; border:1px solid var(--accent); background:var(--accent); color:#fff; font:inherit; cursor:pointer; }
    button:disabled { opacity:.6; cursor:not-allowed; }
    .row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
    .toggle { display:flex; align-items:center; gap:8px; color:var(--ink); }
    .toggle input { width:auto; }
    .panel { border:1px solid var(--line); padding:14px; margin-top:16px; background:#fff; }
    .history-item { border:1px solid var(--line); padding:10px; margin-bottom:10px; background:#fff; }
    .muted { color:var(--muted); font-size:13px; }
    .stages { list-style:none; padding:0; margin:0; display:grid; gap:8px; }
    .stages li { border:1px solid var(--line); padding:8px; display:flex; justify-content:space-between; }
    .error { border-color:#fecdca; background:#fff5f5; color:var(--danger); }
    a { color:var(--accent); }
    @media (max-width: 780px) { .shell { grid-template-columns:1fr; } aside { border-right:0; border-bottom:1px solid var(--line); } }
  </style>
</head>
<body>
  <div class="shell">
    <aside>
      <h1>Bilifan</h1>
      <h2>历史报告</h2>
      <div id="history-list" class="muted">加载中...</div>
    </aside>
    <main>
      <section class="panel" id="consent-panel" hidden>
        <h2>本地处理确认</h2>
        <p class="muted">Bilifan 会下载当前 P 音频，可能运行本地 Whisper，并使用你配置的 Codex CLI 总结 transcript chunks。Transcript 文本可能发送给该 Codex 账号背后的模型服务。</p>
        <button id="consent-button">我理解并同意</button>
      </section>

      <section class="panel">
        <h2>新建总结</h2>
        <label for="url-input">B 站 URL</label>
        <input id="url-input" placeholder="https://www.bilibili.com/video/BV...?p=1">
        <label for="format-select">输出格式</label>
        <select id="format-select">
          <option value="html,pdf">HTML + PDF</option>
          <option value="html">HTML only</option>
        </select>
        <div class="row">
          <label class="toggle"><input id="force-whisper" type="checkbox">强制 Whisper</label>
          <label class="toggle"><input id="require-pdf" type="checkbox">PDF 必需</label>
          <label class="toggle"><input id="allow-long-video" type="checkbox">允许长视频</label>
        </div>
        <button id="start-button">开始总结</button>
      </section>

      <section class="panel">
        <h2>阶段进度</h2>
        <ul id="stage-list" class="stages"></ul>
      </section>

      <section class="panel" id="result-links"></section>
      <section class="panel error" id="failure-panel" hidden></section>
    </main>
  </div>
  <script>
    const params = new URLSearchParams(window.location.search);
    const token = params.get("token") || "";
    const stages = ["preflight","metadata","audio","transcript","chunking","summarization","render"];
    const headers = () => ({"Content-Type":"application/json","X-Bilifan-Token":token});

    async function api(path, options = {}) {
      const response = await fetch(path, {...options, headers:{...headers(), ...(options.headers || {})}});
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    function renderStages(progress) {
      const byStage = Object.fromEntries((progress || []).map(item => [item.stage, item.status]));
      document.getElementById("stage-list").innerHTML = stages.map(stage => `<li><span>${stage}</span><strong>${byStage[stage] || "pending"}</strong></li>`).join("");
    }

    function withToken(url) {
      if (!url) return "";
      return `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
    }

    async function loadConfig() {
      const config = await api("/api/config");
      document.getElementById("consent-panel").hidden = config.consent.local_processing;
    }

    async function loadHistory() {
      const data = await api("/api/history");
      document.getElementById("history-list").innerHTML = data.items.length ? data.items.map(item => `
        <div class="history-item">
          <strong>${item.title}</strong>
          <div class="muted">${item.output_id} · ${item.status}</div>
          <div><a target="_blank" href="${withToken(`/api/runs/${item.run_key}/files/report.html`)}">HTML</a>
          ${item.artifacts.pdf ? `<a target="_blank" href="${withToken(`/api/runs/${item.run_key}/files/report.pdf`)}">PDF</a>` : ""}
          <a target="_blank" href="${withToken(`/api/runs/${item.run_key}/files/diagnostics.json`)}">diagnostics</a></div>
        </div>`).join("") : "暂无历史报告";
    }

    async function pollJob() {
      const state = await api("/api/jobs/current");
      renderStages(state.progress);
      document.getElementById("start-button").disabled = state.status === "running";
      document.getElementById("failure-panel").hidden = state.status !== "failed";
      document.getElementById("failure-panel").textContent = state.status === "failed" ? `${state.stage}: ${state.message}` : "";
      const links = document.getElementById("result-links");
      if (state.status === "succeeded") {
        links.innerHTML = `<h2>结果</h2>
          ${state.artifacts.html ? `<a target="_blank" href="${withToken(state.artifacts.html)}">打开 report.html</a>` : ""}
          ${state.artifacts.pdf ? `<a target="_blank" href="${withToken(state.artifacts.pdf)}">打开 report.pdf</a>` : ""}
          ${state.artifacts.diagnostics ? `<a target="_blank" href="${withToken(state.artifacts.diagnostics)}">查看 diagnostics</a>` : ""}`;
        await loadHistory();
      }
    }

    document.getElementById("consent-button").addEventListener("click", async () => {
      await api("/api/consent", {method:"POST"});
      await loadConfig();
    });

    document.getElementById("start-button").addEventListener("click", async () => {
      await api("/api/jobs", {
        method:"POST",
        body: JSON.stringify({
          url: document.getElementById("url-input").value,
          format: document.getElementById("format-select").value,
          force_whisper: document.getElementById("force-whisper").checked,
          require_pdf: document.getElementById("require-pdf").checked,
          allow_long_video: document.getElementById("allow-long-video").checked
        })
      });
      await pollJob();
    });

    loadConfig().then(loadHistory).then(pollJob);
    setInterval(pollJob, 1000);
  </script>
</body>
</html>"""
```

- [ ] **Step 4: Run UI tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_ui.py -q
```

Expected: PASS.

- [ ] **Step 5: Run API + UI tests together**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/bilifan/web/ui.py tests/test_web_ui.py
git commit -m "feat: add web ui workbench"
```

## Task 6: `bilifan serve` Command

**Files:**
- Modify: `src/bilifan/cli.py`
- Test: `tests/test_cli.py`
- Modify: `README.md`

- [ ] **Step 1: Add failing serve CLI tests**

Append to `tests/test_cli.py`:

```python
def test_serve_command_starts_local_server_with_generated_token(monkeypatch, tmp_path):
    calls = {}

    def fake_generate_token():
        return "test-token"

    def fake_open(url):
        calls["opened_url"] = url
        return True

    def fake_run(app, host, port, log_level):
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port
        calls["log_level"] = log_level

    monkeypatch.setattr(cli, "generate_token", fake_generate_token)
    monkeypatch.setattr(cli.webbrowser, "open", fake_open)
    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    result = runner.invoke(app, ["serve", "--out", str(tmp_path / "outputs"), "--port", "8765"])

    assert result.exit_code == 0
    assert calls["host"] == "127.0.0.1"
    assert calls["port"] == 8765
    assert "token=test-token" in calls["opened_url"]
    assert "http://127.0.0.1:8765/?token=test-token" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_cli.py::test_serve_command_starts_local_server_with_generated_token -q
```

Expected: FAIL with command `serve` not found or missing imports.

- [ ] **Step 3: Implement serve command**

Modify `src/bilifan/cli.py` imports:

```python
import socket
import webbrowser

import uvicorn

from .web.app import create_app
from .web.security import generate_token
```

Add Typer command:

```python
@app.command()
def serve(
    out: Path = typer.Option(Path("./outputs"), "--out"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    no_open: bool = typer.Option(False, "--no-open"),
) -> None:
    """Start the local Bilifan Web UI."""
    if host != "127.0.0.1":
        raise typer.BadParameter("Web UI MVP only supports --host 127.0.0.1.")
    selected_port = _first_available_port(host, port)
    token = generate_token()
    local_url = f"http://{host}:{selected_port}/?token={token}"
    typer.echo(f"Bilifan Web UI: {local_url}")
    app_instance = create_app(outputs=out, token=token, open_browser=not no_open)
    if not no_open:
        webbrowser.open(local_url)
    uvicorn.run(app_instance, host=host, port=selected_port, log_level="info")


def _first_available_port(host: str, start_port: int) -> int:
    for candidate in range(start_port, start_port + 100):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
            except OSError:
                continue
            return candidate
    raise typer.BadParameter("Could not find an available local port.")
```

- [ ] **Step 4: Add tests for host restriction and no-open**

Append:

```python
def test_serve_rejects_non_localhost_host(tmp_path):
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0", "--out", str(tmp_path / "outputs")])

    assert result.exit_code == 2
    assert "only supports --host 127.0.0.1" in result.output


def test_serve_no_open_does_not_open_browser(monkeypatch, tmp_path):
    calls = {"opened": False}

    monkeypatch.setattr(cli, "generate_token", lambda: "test-token")
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: calls.__setitem__("opened", True))
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, host, port, log_level: None)

    result = runner.invoke(app, ["serve", "--no-open", "--out", str(tmp_path / "outputs")])

    assert result.exit_code == 0
    assert calls["opened"] is False
    assert "Bilifan Web UI:" in result.output
```

- [ ] **Step 5: Run serve tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_cli.py::test_serve_command_starts_local_server_with_generated_token tests/test_cli.py::test_serve_rejects_non_localhost_host tests/test_cli.py::test_serve_no_open_does_not_open_browser -q
```

Expected: PASS.

- [ ] **Step 6: Update README**

Add to `README.md`:

```markdown
## Local Web UI

Start the browser workbench:

```bash
python -m bilifan serve
```

The server listens on `127.0.0.1`, opens a tokenized local URL, and uses `./outputs` for Web UI runs. The Web UI supports public-video URL input, HTML/PDF format selection, force Whisper, require PDF, and allow long video. Cookies remain CLI-only in the Web UI MVP.
```
```

- [ ] **Step 7: Run CLI and README-adjacent tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_cli.py tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

Run:

```bash
git add src/bilifan/cli.py tests/test_cli.py README.md
git commit -m "feat: add bilifan serve command"
```

## Task 7: End-to-End Web UI Verification

**Files:**
- Modify: tests if failures expose contract gaps.
- No planned production files unless verification finds a bug.

- [ ] **Step 1: Run full test suite**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
```

Expected: all tests pass.

- [ ] **Step 2: Run diff check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 3: Start Web UI manually**

Run:

```bash
BILIFAN_CONFIG_HOME=/private/tmp/bilifan-web-config-test \
.venv/bin/python -m bilifan serve --out /private/tmp/bilifan-web-e2e --port 8765
```

Expected:

- Command prints `Bilifan Web UI: http://127.0.0.1:<port>/?token=...`.
- Browser opens the page.
- Page shows consent banner if test config is fresh.

- [ ] **Step 4: Manual short-video smoke**

In the Web UI, submit:

```text
https://www.bilibili.com/video/BV1ETEF6VEHu/?spm_id_from=333.1391.0.0
```

Settings:

- format: HTML + PDF.
- force Whisper: off.
- require PDF: off.
- allow long video: off.

Expected:

- Stage list advances through preflight, metadata, audio, transcript, chunking, summarization, render.
- Success links appear.
- `report.html` opens in a new tab.
- `report.pdf` opens if Chrome export succeeds.
- History left panel shows `BV1ETEF6VEHu_p1`.

- [ ] **Step 5: Verify artifact files**

Run:

```bash
find /private/tmp/bilifan-web-e2e/BV1ETEF6VEHu_p1/runs -maxdepth 3 -type f | sort
```

Expected includes:

```text
metadata.json
transcript.json
chunks.json
partial_summaries/chunk_001.json
chapters.json
diagnostics.json
report.html
```

If `report.pdf` is absent, `diagnostics.json` must contain `pdf_failed` and the job should still be succeeded because `require PDF` was off.

- [ ] **Step 6: Commit verification fixes if needed**

If manual smoke reveals a bug, fix it with focused tests and commit:

```bash
git add <changed files>
git commit -m "fix: stabilize web ui smoke"
```

If no code changes are needed, do not create an empty commit.

## Final Review Checklist

- [ ] Spec coverage: every requirement in `docs/superpowers/specs/2026-06-08-bilifan-web-ui-mvp-design.md` maps to a task above.
- [ ] Existing `bilifan summarize` behavior remains covered by tests.
- [ ] Web UI cannot serve files outside `./outputs`.
- [ ] Web UI does not expose cookies input.
- [ ] Web UI only binds `127.0.0.1`.
- [ ] Token is required for API and file routes.
- [ ] Full tests pass.
- [ ] Branch is committed and pushed.
