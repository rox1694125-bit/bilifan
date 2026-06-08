# Bilifan Source Adapter Bundle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stable `content_bundle.json` contract, stage-level retry, source adapter boundary, first YouTube public-video support, and a Nabaichuan ingest example without regressing the current Bilibili MVP.

**Architecture:** Add `bundle.py` and retry support first because Bilibili, YouTube, and Nabaichuan all use the same output contract. Introduce `sources/` as a thin adapter layer that delegates current Bilibili behavior before adding YouTube. Keep the core pipeline responsible for orchestration and artifact writing; adapters own platform URL parsing, metadata mapping, subtitles, audio download, and timestamp links.

**Tech Stack:** Python 3.12, Typer, FastAPI, yt-dlp subprocess/fixtures, ffmpeg/ffprobe, openai-whisper fallback, Codex CLI summarization, pytest, JSON fixtures, strict local filesystem artifact handling.

---

## File Structure

Create:

- `src/bilifan/bundle.py`: strict bundle builder, sanitizer, artifact path validation.
- `src/bilifan/retry.py`: stage-level retry orchestration for existing run directories.
- `src/bilifan/sources/__init__.py`: source adapter exports.
- `src/bilifan/sources/base.py`: source-neutral adapter protocols and helper dataclasses.
- `src/bilifan/sources/bilibili.py`: wrapper adapter delegating to existing Bilibili modules.
- `src/bilifan/sources/youtube.py`: YouTube public-video adapter, metadata fixtures mapper, subtitle parser.
- `examples/content_bundle_to_nabaichuan.py`: standalone JSONL converter.
- `docs/nabaichuan-integration.md`: bundle-to-Nabaichuan field mapping.
- `tests/test_bundle.py`
- `tests/test_retry.py`
- `tests/test_sources.py`
- `tests/test_youtube.py`
- `tests/test_nabaichuan_example.py`

Modify:

- `src/bilifan/pipeline.py`: write bundle on success and expose retry-friendly internal stages.
- `src/bilifan/cli.py`: add `retry` command.
- `src/bilifan/web/files.py`: add `content_bundle.json` to whitelisted artifacts.
- `src/bilifan/web/jobs.py`: expose bundle link if present.
- `src/bilifan/web/ui.py`: render bundle link.
- `tests/test_pipeline.py`, `tests/test_cli.py`, `tests/test_web_history_files.py`, `tests/test_web_jobs.py`, `tests/test_web_ui.py`: expected artifact updates.
- `README.md`: document bundle, retry, YouTube scope, and Nabaichuan integration doc.

Shared constraints:

- Do not remove existing Bilibili functions while migrating.
- Do not change current Bilibili output IDs.
- Do not introduce cookies in Web UI.
- Do not write local absolute paths into bundle or JSONL.
- Commit after each completed slice.

---

## Task 1: Add Bundle Builder

**Files:**
- Create: `src/bilifan/bundle.py`
- Test: `tests/test_bundle.py`

- [ ] **Step 1: Write failing bundle tests**

Create `tests/test_bundle.py`:

```python
import json
from pathlib import Path

import pytest

from bilifan.bundle import BundleError, build_content_bundle, write_content_bundle


def _metadata():
    return {
        "bilifan_version": "0.1.0",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "video_id": "BV1abcDEF12G",
        "part_index": 1,
        "title": "测试视频",
        "part_title": "测试视频",
        "owner_name": "UP",
        "duration": 120,
        "tags": ["AI"],
        "metadata_source": "bilibili-public-api",
    }


def _transcript():
    return {
        "source": "whisper",
        "language": "zh",
        "model": "turbo",
        "segments": [{"start": 0, "end": 3.2, "text": "第一段"}],
        "transcript_check": {"status": "ok", "segment_count": 1},
    }


def _chapters():
    return {
        "style": "学习笔记",
        "chapters": [
            {
                "chapter_index": 1,
                "title": "开场",
                "start": 0,
                "end": 3.2,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "summary": "讲开场。",
                "key_points": ["要点"],
                "quotes": [],
                "visual_anchors": [],
            }
        ],
    }


def test_build_content_bundle_writes_source_summary_and_transcript():
    bundle = build_content_bundle(
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
        artifact_paths=["report.html", "notes.md", "transcript.txt"],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
    )

    assert bundle["schema_version"] == 1
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p1"
    assert bundle["source"]["platform"] == "bilibili"
    assert bundle["source"]["title"] == "测试视频"
    assert bundle["summary"]["chapters"][0]["title"] == "开场"
    assert bundle["transcript"]["segments"][0]["text"] == "第一段"
    assert bundle["artifacts"]["report_html"] == "report.html"


def test_write_content_bundle_rejects_absolute_artifact_paths(tmp_path):
    with pytest.raises(BundleError, match="relative"):
        build_content_bundle(
            metadata=_metadata(),
            transcript=_transcript(),
            chapters=_chapters(),
            artifact_paths=[str(tmp_path / "report.html")],
            platform="bilibili",
            source_id="BV1abcDEF12G",
            part_id="p1",
        )


def test_write_content_bundle_outputs_strict_json_without_local_paths(tmp_path):
    path = write_content_bundle(
        run_dir=tmp_path,
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
        artifact_paths=["report.html", "notes.md"],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(data, ensure_ascii=False)
    assert path.name == "content_bundle.json"
    assert str(tmp_path) not in serialized
    assert "Cookie" not in serialized
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bundle.py -q
```

Expected: import failure for `bilifan.bundle`.

- [ ] **Step 3: Implement minimal bundle builder**

Create `src/bilifan/bundle.py`:

```python
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from .diagnostics import redact_text

BUNDLE_SCHEMA_VERSION = 1


class BundleError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


def build_content_bundle(
    *,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    artifact_paths: list[str],
    platform: str,
    source_id: str,
    part_id: str,
) -> dict[str, Any]:
    artifacts = _artifact_map(artifact_paths)
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "bundle_id": f"{platform}:{source_id}:{part_id}",
        "source": {
            "platform": platform,
            "id": source_id,
            "part_id": part_id,
            "canonical_url": _first_text(metadata.get("input_url_sanitized")),
            "title": _first_text(metadata.get("title")),
            "author": _first_text(metadata.get("owner_name"), metadata.get("uploader")),
            "published_at": _nullable_text(metadata.get("published_at"), metadata.get("upload_date")),
            "duration_seconds": _float_or_none(metadata.get("duration")),
            "language": _first_text(transcript.get("language")) or "unknown",
        },
        "artifacts": artifacts,
        "summary": {
            "style": _first_text(chapters.get("style")) or "学习笔记",
            "chapters": _chapter_items(chapters),
        },
        "transcript": {
            "source": _first_text(transcript.get("source")),
            "language": _first_text(transcript.get("language")),
            "segments": _segment_items(transcript),
        },
        "provenance": {
            "bilifan_version": _first_text(metadata.get("bilifan_version")),
            "generated_at": _first_text(metadata.get("generated_at")),
            "llm_provider": _first_text(chapters.get("llm_provider"), metadata.get("llm_provider")),
            "llm_model": _first_text(chapters.get("llm_model"), metadata.get("llm_model")),
            "transcript_source": _first_text(transcript.get("source")),
            "metadata_source": _first_text(metadata.get("metadata_source")),
        },
    }


def write_content_bundle(
    *,
    run_dir: Path,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    artifact_paths: list[str],
    platform: str,
    source_id: str,
    part_id: str,
) -> Path:
    bundle = build_content_bundle(
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        artifact_paths=artifact_paths,
        platform=platform,
        source_id=source_id,
        part_id=part_id,
    )
    path = run_dir / "content_bundle.json"
    path.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def _artifact_map(paths: list[str]) -> dict[str, str]:
    mapping = {
        "report.html": "report_html",
        "report.pdf": "report_pdf",
        "notes.md": "notes_md",
        "transcript.txt": "transcript_txt",
        "transcript.srt": "transcript_srt",
    }
    artifacts: dict[str, str] = {}
    for path in paths:
        _validate_relative_path(path)
        name = mapping.get(path)
        if name:
            artifacts[name] = path
    return artifacts


def _validate_relative_path(path: str) -> None:
    if not isinstance(path, str) or not path:
        raise BundleError("Bundle artifact paths must be non-empty relative paths.")
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts or "\\" in path:
        raise BundleError("Bundle artifact paths must be relative to the run directory.")


def _chapter_items(chapters: dict[str, Any]) -> list[dict[str, Any]]:
    raw = chapters.get("chapters")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _segment_items(transcript: dict[str, Any]) -> list[dict[str, Any]]:
    raw = transcript.get("segments")
    if not isinstance(raw, list):
        return []
    return [
        {
            "start": item.get("start"),
            "end": item.get("end"),
            "text": redact_text(_first_text(item.get("text")), max_length=None),
        }
        for item in raw
        if isinstance(item, dict)
    ]


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            return redact_text(value, max_length=None)
        if isinstance(value, int | float):
            return str(value)
    return ""


def _nullable_text(*values: Any) -> str | None:
    text = _first_text(*values)
    return text or None


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    return None
```

- [ ] **Step 4: Run bundle tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bundle.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/bilifan/bundle.py tests/test_bundle.py
git commit -m "feat: add content bundle writer"
```

---

## Task 2: Integrate Bundle into Successful Pipeline and Web Artifacts

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `src/bilifan/web/files.py`
- Modify: `src/bilifan/web/jobs.py`
- Modify: `src/bilifan/web/ui.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_web_history_files.py`
- Test: `tests/test_web_jobs.py`
- Test: `tests/test_web_ui.py`

- [ ] **Step 1: Add failing pipeline artifact assertion**

In `tests/test_pipeline.py`, update `test_run_summarize_pipeline_writes_artifacts_and_reports_progress`:

```python
assert "content_bundle.json" in result.artifact_paths
bundle = json.loads((result.run_dir / "content_bundle.json").read_text(encoding="utf-8"))
assert bundle["source"]["platform"] == "bilibili"
assert bundle["summary"]["chapters"][0]["title"] == "开场"
```

- [ ] **Step 2: Run focused pipeline test and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py::test_run_summarize_pipeline_writes_artifacts_and_reports_progress -q
```

Expected: assertion failure because bundle is not yet written.

- [ ] **Step 3: Write bundle in pipeline success path**

Modify `src/bilifan/pipeline.py` imports:

```python
from .bundle import BundleError, write_content_bundle
```

Add `"bundle"` to `PipelineStage`:

```python
class PipelineStage(str, Enum):
    PREFLIGHT = "preflight"
    METADATA = "metadata"
    AUDIO = "audio"
    TRANSCRIPT = "transcript"
    CHUNKING = "chunking"
    SUMMARIZATION = "summarization"
    RENDER = "render"
    BUNDLE = "bundle"
```

After PDF handling and before final diagnostics:

```python
    bundle_warnings: list[str] = []
    try:
        bundle_path = write_content_bundle(
            run_dir=run.run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            artifact_paths=render_artifacts,
            platform="bilibili",
            source_id=ref.bvid,
            part_id=f"p{ref.part_index}",
        )
        render_artifacts.append(bundle_path.name)
    except BundleError:
        bundle_warnings.append("bundle_failed")

    render_warnings = [*render_warnings, *bundle_warnings]
```

Use `render_warnings` in final diagnostics and result.

- [ ] **Step 4: Add Web artifact support**

Modify `src/bilifan/web/files.py`:

```python
ROOT_FILES = {
    "metadata.json",
    "transcript.json",
    "chunks.json",
    "chapters.json",
    "diagnostics.json",
    "report.html",
    "report.pdf",
    "transcript.txt",
    "transcript.srt",
    "notes.md",
    "content_bundle.json",
}
```

In `_artifact_links`:

```python
if _safe_existing_file(run_dir, "content_bundle.json") is not None:
    artifacts["bundle"] = f"{prefix}/content_bundle.json"
```

Modify `src/bilifan/web/jobs.py` `_artifact_links`:

```python
if "content_bundle.json" in artifact_paths:
    artifacts["bundle"] = f"{prefix}/content_bundle.json"
```

Modify `src/bilifan/web/ui.py` in `renderLinks` and history rendering:

```javascript
if (artifacts.bundle) links.push(linkItem("bundle", artifacts.bundle));
```

- [ ] **Step 5: Update Web tests**

In Web tests, assert `"content_bundle.json"` and `"bundle"` markers:

```python
assert "content_bundle.json" in files
assert artifacts["bundle"].endswith("/content_bundle.json?token=test-token")
assert "bundle" in html
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py tests/test_web_history_files.py tests/test_web_jobs.py tests/test_web_ui.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/bilifan/pipeline.py src/bilifan/web/files.py src/bilifan/web/jobs.py src/bilifan/web/ui.py tests/test_pipeline.py tests/test_web_history_files.py tests/test_web_jobs.py tests/test_web_ui.py
git commit -m "feat: write content bundle in pipeline"
```

---

## Task 3: Add Stage-Level Retry Command

**Files:**
- Create: `src/bilifan/retry.py`
- Modify: `src/bilifan/cli.py`
- Test: `tests/test_retry.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write failing retry tests**

Create `tests/test_retry.py`:

```python
import json
from pathlib import Path

import pytest

from bilifan.retry import RetryError, RetryRequest, retry_run


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_run(tmp_path):
    run_dir = tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-09_120000"
    _write_json(run_dir / "metadata.json", {
        "bilifan_version": "0.1.0",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "video_id": "BV1abcDEF12G",
        "part_index": 1,
        "title": "测试视频",
        "owner_name": "UP",
        "duration": 120,
    })
    _write_json(run_dir / "transcript.json", {
        "source": "whisper",
        "language": "zh",
        "segments": [{"start": 0, "end": 10, "text": "转写"}],
        "transcript_check": {"status": "ok"},
    })
    _write_json(run_dir / "chunks.json", {
        "chunks": [{"chunk_index": 1, "start": 0, "end": 10, "segments": [], "text": "转写"}],
    })
    _write_json(run_dir / "chapters.json", {
        "style": "学习笔记",
        "chapters": [{
            "chapter_index": 1,
            "title": "开场",
            "start": 0,
            "end": 10,
            "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
            "summary": "摘要",
            "key_points": [],
            "quotes": [],
            "visual_anchors": [],
        }],
    })
    return run_dir


def test_retry_from_bundle_writes_content_bundle(tmp_path):
    run_dir = _make_run(tmp_path)

    result = retry_run(RetryRequest(run_dir=run_dir, from_stage="bundle"))

    assert "content_bundle.json" in result.artifact_paths
    assert (run_dir / "content_bundle.json").is_file()
    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-09_120000"


def test_retry_rejects_missing_prerequisite(tmp_path):
    run_dir = _make_run(tmp_path)
    (run_dir / "chapters.json").unlink()

    with pytest.raises(RetryError, match="chapters.json"):
        retry_run(RetryRequest(run_dir=run_dir, from_stage="bundle"))
```

- [ ] **Step 2: Run retry tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_retry.py -q
```

Expected: import failure for `bilifan.retry`.

- [ ] **Step 3: Implement retry request and bundle retry**

Create `src/bilifan/retry.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .bundle import BundleError, write_content_bundle
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .pipeline import PipelineResult

VALID_RETRY_STAGES = {"summarization", "render", "bundle"}


@dataclass(frozen=True)
class RetryRequest:
    run_dir: Path
    from_stage: str
    output_format: str = "html,pdf"
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    require_pdf: bool = False


class RetryError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(redact_text(message))


def retry_run(request: RetryRequest) -> PipelineResult:
    if request.from_stage not in VALID_RETRY_STAGES:
        raise RetryError("--from must be summarization, render, or bundle.")
    run_dir = request.run_dir.resolve(strict=False)
    if not run_dir.is_dir():
        raise RetryError(f"Run directory does not exist: {run_dir}")
    if request.from_stage == "bundle":
        return _retry_bundle(run_dir)
    raise RetryError(f"Retry from {request.from_stage} is not implemented in this slice.")


def _retry_bundle(run_dir: Path) -> PipelineResult:
    metadata = _read_required_json(run_dir, "metadata.json")
    transcript = _read_required_json(run_dir, "transcript.json")
    chapters = _read_required_json(run_dir, "chapters.json")
    platform = _platform_from_metadata(metadata)
    source_id = _first_text(metadata.get("video_id"), metadata.get("id"))
    part_id = f"p{int(metadata.get('part_index') or 1)}"
    artifacts = _existing_artifacts(run_dir)
    try:
        bundle_path = write_content_bundle(
            run_dir=run_dir,
            metadata=metadata,
            transcript=transcript,
            chapters=chapters,
            artifact_paths=artifacts,
            platform=platform,
            source_id=source_id,
            part_id=part_id,
        )
    except BundleError as exc:
        _write_retry_diagnostics(run_dir, metadata, "BundleError", str(exc), ["bundle_failed"], artifacts)
        raise RetryError(str(exc)) from exc
    final_artifacts = [*artifacts, bundle_path.name]
    _write_retry_diagnostics(run_dir, metadata, None, "Bundle retry completed.", [], final_artifacts)
    return PipelineResult(
        run_key=_run_key(run_dir),
        run_dir=run_dir,
        diagnostics_path=run_dir / "diagnostics.json",
        artifact_paths=final_artifacts,
        warnings=[],
    )


def _read_required_json(run_dir: Path, name: str) -> dict[str, Any]:
    path = run_dir / name
    if not path.is_file():
        raise RetryError(f"Retry requires {name}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RetryError(f"Retry could not read {name}.") from exc
    if not isinstance(data, dict):
        raise RetryError(f"Retry requires {name} to contain a JSON object.")
    return data


def _existing_artifacts(run_dir: Path) -> list[str]:
    names = ["report.html", "report.pdf", "notes.md", "transcript.txt", "transcript.srt"]
    return [name for name in names if (run_dir / name).is_file()]


def _platform_from_metadata(metadata: dict[str, Any]) -> str:
    return _first_text(metadata.get("platform")) or "bilibili"


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def _run_key(run_dir: Path) -> str:
    return f"{run_dir.parent.parent.name}/runs/{run_dir.name}"


def _write_retry_diagnostics(
    run_dir: Path,
    metadata: dict[str, Any],
    error_type: str | None,
    message: str,
    warnings: list[str],
    artifacts: list[str],
) -> None:
    write_diagnostics(
        run_dir / "diagnostics.json",
        Diagnostics(
            error_type=error_type,
            exit_code=0 if error_type is None else 1,
            stage="bundle",
            video_id=_first_text(metadata.get("video_id"), metadata.get("id")),
            part_index=int(metadata.get("part_index") or 1),
            duration_check=None,
            transcript_check=None,
            artifact_paths=["diagnostics.json", "metadata.json", "transcript.json", "chapters.json", *artifacts],
            sanitized_message=message,
            warnings=warnings,
        ),
    )
```

- [ ] **Step 4: Add CLI retry command**

Modify `src/bilifan/cli.py` imports:

```python
from .retry import RetryError, RetryRequest, retry_run
```

Add command:

```python
@app.command()
def retry(
    run_dir: Path,
    from_stage: str = typer.Option("", "--from"),
    output_format: str = typer.Option("html,pdf", "--format"),
    llm_provider: str = typer.Option("codex-exec", "--llm-provider"),
    llm_model: str = typer.Option("gpt-5.5", "--llm-model"),
    require_pdf: bool = typer.Option(False, "--require-pdf"),
) -> None:
    """Retry a failed or completed Bilifan run from an existing stage."""
    if not from_stage:
        raise typer.BadParameter("--from is required and must be summarization, render, or bundle.")
    try:
        result = retry_run(
            RetryRequest(
                run_dir=run_dir,
                from_stage=from_stage,
                output_format=output_format,
                llm_provider=llm_provider,
                llm_model=llm_model,
                require_pdf=require_pdf,
            )
        )
    except RetryError as exc:
        typer.echo(redact_text(str(exc)), err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Retried Bilifan run: {result.run_key}")
```

- [ ] **Step 5: Add CLI test**

In `tests/test_cli.py`, add a test using `CliRunner` existing patterns:

```python
def test_retry_command_runs_bundle_retry(tmp_path):
    run_dir = tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-09_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text('{"video_id":"BV1abcDEF12G","part_index":1,"title":"t"}', encoding="utf-8")
    (run_dir / "transcript.json").write_text('{"source":"whisper","language":"zh","segments":[]}', encoding="utf-8")
    (run_dir / "chapters.json").write_text('{"style":"学习笔记","chapters":[]}', encoding="utf-8")

    result = runner.invoke(app, ["retry", str(run_dir), "--from", "bundle"])

    assert result.exit_code == 0
    assert "Retried Bilifan run" in result.output
    assert (run_dir / "content_bundle.json").is_file()
```

Use the existing runner/app names from `tests/test_cli.py`.

- [ ] **Step 6: Run retry and CLI tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_retry.py tests/test_cli.py -q
```

Expected: pass after adapting test imports to existing CLI fixture names.

- [ ] **Step 7: Extend retry from render and summarization**

Add tests first:

```python
def test_retry_from_render_uses_existing_chapters_and_writes_report(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    calls = {"render": 0}

    def fake_render_report_html(**kwargs):
        calls["render"] += 1
        path = kwargs["run_dir"] / "report.html"
        path.write_text("<html>ok</html>", encoding="utf-8")
        return path

    monkeypatch.setattr("bilifan.retry.render_report_html", fake_render_report_html)
    result = retry_run(RetryRequest(run_dir=run_dir, from_stage="render", output_format="html"))

    assert calls["render"] == 1
    assert "report.html" in result.artifact_paths
```

```python
def test_retry_from_summarization_regenerates_chapters(tmp_path, monkeypatch):
    run_dir = _make_run(tmp_path)
    (run_dir / "chapters.json").unlink()

    def fake_summarize_chunks(**kwargs):
        return {"style": "学习笔记", "chapters": []}

    monkeypatch.setattr("bilifan.retry.summarize_chunks", fake_summarize_chunks)
    result = retry_run(RetryRequest(run_dir=run_dir, from_stage="summarization", output_format="html"))

    assert "chapters.json" in result.artifact_paths
```

Implement `retry.py` by importing and reusing:

```python
from .exports import write_notes_markdown
from .renderer import export_report_pdf, render_report_html
from .summarizer import summarize_chunks
from .bilibili import BilibiliPartRef
```

Build `BilibiliPartRef` from metadata in this slice:

```python
def _ref_from_metadata(metadata: dict[str, Any]) -> BilibiliPartRef:
    bvid = _first_text(metadata.get("video_id"))
    part_index = int(metadata.get("part_index") or 1)
    url = _first_text(metadata.get("input_url_sanitized"))
    return BilibiliPartRef(bvid=bvid, part_index=part_index, sanitized_url=url)
```

- [ ] **Step 8: Run focused retry tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_retry.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add src/bilifan/retry.py src/bilifan/cli.py tests/test_retry.py tests/test_cli.py
git commit -m "feat: add stage retry command"
```

---

## Task 4: Add SourceAdapter Base and Resolver

**Files:**
- Create: `src/bilifan/sources/__init__.py`
- Create: `src/bilifan/sources/base.py`
- Create: `tests/test_sources.py`

- [ ] **Step 1: Write failing resolver tests**

Create `tests/test_sources.py`:

```python
import pytest

from bilifan.sources import SourceAdapterError, resolve_source_adapter
from bilifan.sources.base import VideoRef


def test_resolve_source_adapter_returns_bilibili():
    adapter = resolve_source_adapter("https://www.bilibili.com/video/BV1abcDEF12G?p=2")

    ref = adapter.parse_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    assert adapter.platform == "bilibili"
    assert ref.platform == "bilibili"
    assert ref.source_id == "BV1abcDEF12G"
    assert ref.part_id == "p2"


def test_resolve_source_adapter_returns_youtube():
    adapter = resolve_source_adapter("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert adapter.platform == "youtube"


def test_resolve_source_adapter_rejects_unknown_url():
    with pytest.raises(SourceAdapterError, match="Unsupported video URL"):
        resolve_source_adapter("https://example.com/video/1")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_sources.py -q
```

Expected: import failure for `bilifan.sources`.

- [ ] **Step 3: Implement base types**

Create `src/bilifan/sources/base.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class VideoRef:
    platform: str
    source_id: str
    part_id: str
    canonical_url: str
    raw_url: str

    @property
    def output_id(self) -> str:
        return f"{self.source_id}_{self.part_id}"


@dataclass(frozen=True)
class SourceOptions:
    cookies_from_browser: str | None = None
    cookies_file: Path | None = None
    language: str = "auto"
    force_whisper: bool = False


class SourceAdapter(Protocol):
    platform: str

    def parse_url(self, url: str) -> VideoRef:
        raise NotImplementedError

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        raise NotImplementedError

    def output_id(self, ref: VideoRef) -> str:
        raise NotImplementedError

    def fetch_metadata(self, ref: VideoRef, run_dir: Path, options: SourceOptions) -> dict[str, Any]:
        raise NotImplementedError

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        raise NotImplementedError
```

- [ ] **Step 4: Implement resolver with placeholder adapters**

Create `src/bilifan/sources/__init__.py`:

```python
from __future__ import annotations

from .base import SourceAdapter, SourceOptions, VideoRef
from .bilibili import BilibiliAdapter
from .youtube import YouTubeAdapter


class SourceAdapterError(ValueError):
    pass


def resolve_source_adapter(url: str) -> SourceAdapter:
    for adapter in (BilibiliAdapter(), YouTubeAdapter()):
        if adapter.can_parse(url):
            return adapter
    raise SourceAdapterError("Unsupported video URL. Bilifan supports Bilibili and YouTube public video URLs.")


__all__ = [
    "BilibiliAdapter",
    "SourceAdapter",
    "SourceAdapterError",
    "SourceOptions",
    "VideoRef",
    "YouTubeAdapter",
    "resolve_source_adapter",
]
```

Create minimal `src/bilifan/sources/youtube.py`:

```python
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from .base import SourceOptions, VideoRef


class YouTubeAdapter:
    platform = "youtube"

    def can_parse(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return host in {"www.youtube.com", "youtube.com", "youtu.be"} and bool(self._video_id(parsed))

    def parse_url(self, url: str) -> VideoRef:
        parsed = urlparse(url)
        video_id = self._video_id(parsed)
        if not video_id:
            raise ValueError("Invalid YouTube video URL.")
        canonical = f"https://www.youtube.com/watch?v={video_id}"
        return VideoRef(platform=self.platform, source_id=video_id, part_id="p1", canonical_url=canonical, raw_url=url)

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        return f"https://www.youtube.com/watch?v={ref.source_id}&t={max(0, int(seconds))}s"

    def output_id(self, ref: VideoRef) -> str:
        return f"YT{ref.source_id}_p1"

    def _video_id(self, parsed) -> str:
        if parsed.netloc.lower() == "youtu.be":
            return parsed.path.strip("/")
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        return ""
```

- [ ] **Step 5: Implement Bilibili wrapper adapter**

Create `src/bilifan/sources/bilibili.py`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from bilifan.bilibili import BilibiliPartRef, parse_bilibili_url
from bilifan.media import download_current_part_audio
from bilifan.metadata import fetch_current_part_metadata

from .base import SourceOptions, VideoRef


class BilibiliAdapter:
    platform = "bilibili"

    def can_parse(self, url: str) -> bool:
        try:
            parse_bilibili_url(url)
        except ValueError:
            return False
        return True

    def parse_url(self, url: str) -> VideoRef:
        ref = parse_bilibili_url(url)
        return VideoRef(
            platform=self.platform,
            source_id=ref.bvid,
            part_id=f"p{ref.part_index}",
            canonical_url=ref.sanitized_url,
            raw_url=url,
        )

    def legacy_ref(self, ref: VideoRef) -> BilibiliPartRef:
        part_index = int(ref.part_id.removeprefix("p") or "1")
        return BilibiliPartRef(
            bvid=ref.source_id,
            part_index=part_index,
            sanitized_url=ref.canonical_url,
        )

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        return self.legacy_ref(ref).timestamp_url(seconds)

    def output_id(self, ref: VideoRef) -> str:
        return self.legacy_ref(ref).output_id

    def fetch_metadata(self, ref: VideoRef, run_dir: Path, options: SourceOptions) -> dict[str, Any]:
        return fetch_current_part_metadata(
            self.legacy_ref(ref),
            run_dir,
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
    ) -> dict[str, Any]:
        return download_current_part_audio(
            self.legacy_ref(ref),
            metadata,
            run_dir,
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )
```

- [ ] **Step 6: Run source tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_sources.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/bilifan/sources tests/test_sources.py
git commit -m "feat: add source adapter base"
```

---

## Task 5: Route Bilibili Pipeline Through Adapter

**Files:**
- Modify: `src/bilifan/pipeline.py`
- Modify: `src/bilifan/summarizer.py`
- Modify: `src/bilifan/renderer.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Add failing adapter call test**

In `tests/test_pipeline.py`, add:

```python
def test_pipeline_resolves_adapter_before_creating_run(tmp_path, monkeypatch):
    calls = {"parse": 0}

    class FakeAdapter:
        platform = "bilibili"
        def can_parse(self, url):
            return True
        def parse_url(self, url):
            calls["parse"] += 1
            from bilifan.sources.base import VideoRef
            return VideoRef("bilibili", "BV1abcDEF12G", "p1", "https://www.bilibili.com/video/BV1abcDEF12G?p=1", url)
        def output_id(self, ref):
            return "BV1abcDEF12G_p1"

    monkeypatch.setattr(pipeline, "resolve_source_adapter", lambda url: FakeAdapter())
    monkeypatch.setattr(pipeline, "create_run", lambda out, ref, overwrite=False: (_ for _ in ()).throw(RuntimeError("stop")))

    with pytest.raises(RuntimeError, match="stop"):
        pipeline.run_summarize_pipeline(PipelineRequest(url="https://www.bilibili.com/video/BV1abcDEF12G", out=tmp_path))

    assert calls["parse"] == 1
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_pipeline.py::test_pipeline_resolves_adapter_before_creating_run -q
```

Expected: failure because pipeline still calls `parse_bilibili_url` directly.

- [ ] **Step 3: Add compatibility wrapper for run creation**

Keep `create_run()` using Bilibili-like refs for this slice by adding a small adapter conversion in `pipeline.py`:

```python
from .sources import resolve_source_adapter
from .sources.bilibili import BilibiliAdapter


def _legacy_run_ref(adapter, source_ref):
    if isinstance(adapter, BilibiliAdapter):
        return adapter.legacy_ref(source_ref)
    return _GenericRunRef(source_ref, adapter)


class _GenericRunRef:
    def __init__(self, source_ref, adapter):
        self.bvid = adapter.output_id(source_ref)
        self.part_index = 1
        self.sanitized_url = source_ref.canonical_url
        self.output_id = adapter.output_id(source_ref)

    def timestamp_url(self, seconds: float) -> str:
        return self._adapter.timestamp_url(self._source_ref, seconds)
```

When writing actual code, ensure `_GenericRunRef.__init__` stores `_source_ref` and `_adapter`.

- [ ] **Step 4: Replace direct Bilibili parse/fetch/download calls**

In `run_summarize_pipeline`, replace:

```python
ref = parse_bilibili_url(request.url)
```

with:

```python
adapter = resolve_source_adapter(request.url)
source_ref = adapter.parse_url(request.url)
ref = _legacy_run_ref(adapter, source_ref)
```

Replace metadata call:

```python
metadata = adapter.fetch_metadata(
    source_ref,
    run.run_dir,
    SourceOptions(
        cookies_from_browser=request.cookies_from_browser,
        cookies_file=request.cookies_file,
        language=request.language,
        force_whisper=request.force_whisper,
    ),
)
metadata["platform"] = adapter.platform
```

Replace audio call:

```python
media = adapter.download_audio(source_ref, metadata, run.run_dir, source_options)
```

Bundle call should use:

```python
platform=adapter.platform,
source_id=source_ref.source_id,
part_id=source_ref.part_id,
```

- [ ] **Step 5: Run Bilibili-focused tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_bilibili.py tests/test_metadata.py tests/test_media.py tests/test_transcript.py tests/test_pipeline.py -q
```

Expected: pass after adapting monkeypatch targets in tests that patch `fetch_current_part_metadata` or `download_current_part_audio`. Prefer patching adapter methods or keep imported names as fallback wrappers if tests rely on them.

- [ ] **Step 6: Commit**

```bash
git add src/bilifan/pipeline.py src/bilifan/summarizer.py src/bilifan/renderer.py tests/test_pipeline.py tests/test_sources.py
git commit -m "refactor: route bilibili pipeline through source adapter"
```

---

## Task 6: Add YouTube Metadata, Subtitle, and Audio Adapter

**Files:**
- Modify: `src/bilifan/sources/youtube.py`
- Create: `tests/fixtures/youtube_metadata.json`
- Create: `tests/fixtures/youtube_subtitles.vtt`
- Test: `tests/test_youtube.py`

- [ ] **Step 1: Write YouTube parser and mapping tests**

Create `tests/test_youtube.py`:

```python
import json
from pathlib import Path

import pytest

from bilifan.sources.youtube import YouTubeAdapter, parse_youtube_vtt


def test_youtube_parse_watch_and_short_urls():
    adapter = YouTubeAdapter()

    watch = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    short = adapter.parse_url("https://youtu.be/dQw4w9WgXcQ")

    assert watch.source_id == "dQw4w9WgXcQ"
    assert short.source_id == "dQw4w9WgXcQ"
    assert adapter.timestamp_url(watch, 12.8).endswith("&t=12s")


def test_youtube_rejects_playlist_only_url():
    adapter = YouTubeAdapter()

    assert adapter.can_parse("https://www.youtube.com/playlist?list=PL123") is False


def test_youtube_metadata_mapping(tmp_path):
    adapter = YouTubeAdapter()
    raw = {
        "id": "dQw4w9WgXcQ",
        "title": "Example",
        "channel": "Channel",
        "duration": 123,
        "description": "Description",
        "tags": ["AI"],
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "subtitles": {"en": [{"url": "https://example.com/en.vtt", "ext": "vtt"}]},
        "automatic_captions": {},
    }

    metadata = adapter.map_metadata(raw, canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert metadata["platform"] == "youtube"
    assert metadata["video_id"] == "dQw4w9WgXcQ"
    assert metadata["owner_name"] == "Channel"
    assert metadata["duration"] == 123
    assert metadata["subtitles"][0]["language"] == "en"


def test_parse_youtube_vtt_segments():
    segments = parse_youtube_vtt(
        "WEBVTT\\n\\n00:00:01.000 --> 00:00:03.500\\nHello world\\n"
    )

    assert segments == [{"start": 1.0, "end": 3.5, "text": "Hello world"}]
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_youtube.py -q
```

Expected: missing `map_metadata` and `parse_youtube_vtt`.

- [ ] **Step 3: Implement metadata mapping and VTT parser**

Modify `src/bilifan/sources/youtube.py`:

```python
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from bilifan.diagnostics import redact_text


class YouTubeAdapter:
    platform = "youtube"

    def map_metadata(self, raw: dict[str, Any], *, canonical_url: str) -> dict[str, Any]:
        video_id = _first_text(raw.get("id"))
        subtitles = _subtitle_tracks(raw.get("subtitles"), raw.get("automatic_captions"))
        return {
            "platform": self.platform,
            "video_id": video_id,
            "part_index": 1,
            "input_url_sanitized": canonical_url,
            "title": _first_text(raw.get("title")),
            "part_title": _first_text(raw.get("title")),
            "owner_name": _first_text(raw.get("channel"), raw.get("uploader")),
            "description": _first_text(raw.get("description")),
            "tags": raw.get("tags") if isinstance(raw.get("tags"), list) else [],
            "cover_url": _first_text(raw.get("thumbnail")),
            "cover_path": "",
            "duration": raw.get("duration"),
            "parts": [{"part_index": 1, "cid": video_id, "title": _first_text(raw.get("title")), "duration": raw.get("duration")}],
            "subtitles": subtitles,
            "metadata_source": "yt-dlp",
        }


def parse_youtube_vtt(content: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    blocks = re.split(r"\\n\\s*\\n", content.replace("\\r\\n", "\\n"))
    for block in blocks:
        lines = [line.strip() for line in block.split("\\n") if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), -1)
        if timing_index < 0:
            continue
        start_raw, end_raw = [part.strip().split(" ")[0] for part in lines[timing_index].split("-->", 1)]
        text = " ".join(lines[timing_index + 1 :]).strip()
        if text:
            segments.append({"start": _parse_vtt_time(start_raw), "end": _parse_vtt_time(end_raw), "text": redact_text(text, max_length=None)})
    return segments


def _parse_vtt_time(value: str) -> float:
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def _subtitle_tracks(subtitles: Any, automatic: Any) -> list[dict[str, str]]:
    tracks: list[dict[str, str]] = []
    for source_name, source in (("manual", subtitles), ("automatic", automatic)):
        if not isinstance(source, dict):
            continue
        for language, entries in source.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict):
                    tracks.append({
                        "language": str(language),
                        "url": _first_text(entry.get("url")),
                        "ext": _first_text(entry.get("ext")),
                        "source": source_name,
                    })
    return tracks


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            return redact_text(value, max_length=None)
        if isinstance(value, int | float):
            return str(value)
    return ""
```

- [ ] **Step 4: Add mocked pipeline test for YouTube subtitle-only**

In `tests/test_youtube.py`, add:

```python
def test_youtube_adapter_bundle_shape_from_mapped_metadata(tmp_path):
    from bilifan.bundle import write_content_bundle

    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    metadata = adapter.map_metadata({"id": ref.source_id, "title": "Example", "channel": "Channel", "duration": 3}, canonical_url=ref.canonical_url)
    transcript = {"source": "youtube_subtitle", "language": "en", "segments": [{"start": 0, "end": 3, "text": "Hello"}]}
    chapters = {"style": "学习笔记", "chapters": [{"chapter_index": 1, "title": "Intro", "start": 0, "end": 3, "timestamp_url": adapter.timestamp_url(ref, 0), "summary": "Summary", "key_points": [], "quotes": [], "visual_anchors": []}]}

    path = write_content_bundle(run_dir=tmp_path, metadata=metadata, transcript=transcript, chapters=chapters, artifact_paths=[], platform=adapter.platform, source_id=ref.source_id, part_id=ref.part_id)

    assert json.loads(path.read_text(encoding="utf-8"))["source"]["platform"] == "youtube"
```

- [ ] **Step 5: Add live methods behind adapter interface**

Implement:

```python
def fetch_metadata(self, ref: VideoRef, run_dir: Path, options: SourceOptions) -> dict[str, Any]:
    output_path = run_dir / ".bilifan" / "youtube_metadata.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["yt-dlp", "--dump-single-json", "--skip-download", ref.canonical_url]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(redact_text(result.stderr or result.stdout or "yt-dlp failed"))
    raw = json.loads(result.stdout)
    return self.map_metadata(raw, canonical_url=ref.canonical_url)
```

For audio fallback, implement `download_audio` in `src/bilifan/sources/youtube.py` with a direct `yt-dlp` subprocess command that extracts best audio to `.bilifan/cache/YT<video_id>_p1.mp3`, then calls `ffprobe` through the existing duration helper if one is available in `media.py`; otherwise add a focused helper in `media.py` during this task and cover it with `tests/test_media.py`. Keep cookies unsupported by raising a clear error when `options.cookies_file` or `options.cookies_from_browser` is set.

- [ ] **Step 6: Run YouTube tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_youtube.py tests/test_sources.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add src/bilifan/sources/youtube.py tests/test_youtube.py tests/fixtures
git commit -m "feat: add youtube source adapter"
```

---

## Task 7: Add Nabaichuan JSONL Example

**Files:**
- Create: `examples/content_bundle_to_nabaichuan.py`
- Create: `docs/nabaichuan-integration.md`
- Create: `tests/test_nabaichuan_example.py`

- [ ] **Step 1: Write failing example test**

Create `tests/test_nabaichuan_example.py`:

```python
import json
import subprocess
import sys
from pathlib import Path


def _bundle(path: Path, platform: str):
    path.write_text(json.dumps({
        "schema_version": 1,
        "bundle_id": f"{platform}:source:p1",
        "source": {"platform": platform, "id": "source", "part_id": "p1", "canonical_url": "https://example.com/video", "title": "Title", "author": "Author"},
        "summary": {"style": "学习笔记", "chapters": [{"chapter_index": 1, "title": "Chapter", "summary": "Summary", "timestamp_url": "https://example.com/video?t=0", "key_points": ["Point"]}]},
        "transcript": {"segments": [{"start": 0, "end": 1, "text": "Hello"}]},
        "artifacts": {},
        "provenance": {},
    }, ensure_ascii=False), encoding="utf-8")


def test_content_bundle_to_nabaichuan_outputs_jsonl(tmp_path):
    bundle_path = tmp_path / "content_bundle.json"
    output_path = tmp_path / "out.jsonl"
    _bundle(bundle_path, "bilibili")

    result = subprocess.run(
        [sys.executable, "examples/content_bundle_to_nabaichuan.py", str(bundle_path), "--out", str(output_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in output_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["type"] == "video"
    assert rows[1]["type"] == "chapter"
    assert rows[1]["source_url"].endswith("t=0")
    assert str(tmp_path) not in output_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_nabaichuan_example.py -q
```

Expected: script missing.

- [ ] **Step 3: Implement example script**

Create `examples/content_bundle_to_nabaichuan.py`:

```python
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Bilifan content_bundle.json to Nabaichuan-style JSONL.")
    parser.add_argument("bundle")
    parser.add_argument("--out", required=True)
    parser.add_argument("--include-transcript", action="store_true")
    args = parser.parse_args()

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    rows = convert_bundle(bundle, include_transcript=args.include_transcript)
    Path(args.out).write_text(
        "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return 0


def convert_bundle(bundle: dict[str, Any], *, include_transcript: bool = False) -> list[dict[str, Any]]:
    source = bundle.get("source") if isinstance(bundle.get("source"), dict) else {}
    bundle_id = str(bundle.get("bundle_id") or "")
    rows = [{
        "type": "video",
        "source_id": bundle_id,
        "platform": source.get("platform"),
        "title": source.get("title"),
        "author": source.get("author"),
        "source_url": source.get("canonical_url"),
    }]
    summary = bundle.get("summary") if isinstance(bundle.get("summary"), dict) else {}
    for chapter in summary.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        index = chapter.get("chapter_index")
        rows.append({
            "type": "chapter",
            "source_id": f"{bundle_id}#chapter-{index}",
            "parent_source_id": bundle_id,
            "title": chapter.get("title"),
            "summary": chapter.get("summary"),
            "key_points": chapter.get("key_points") or [],
            "source_url": chapter.get("timestamp_url"),
        })
    if include_transcript:
        transcript = bundle.get("transcript") if isinstance(bundle.get("transcript"), dict) else {}
        for index, segment in enumerate(transcript.get("segments") or [], start=1):
            if isinstance(segment, dict):
                rows.append({
                    "type": "transcript_segment",
                    "source_id": f"{bundle_id}#segment-{index}",
                    "parent_source_id": bundle_id,
                    "start": segment.get("start"),
                    "end": segment.get("end"),
                    "text": segment.get("text"),
                })
    return rows


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write integration docs**

Create `docs/nabaichuan-integration.md`:

```markdown
# Nabaichuan Integration

Bilifan integrates with Nabaichuan through `content_bundle.json`.

Stable fields:

- `schema_version`
- `bundle_id`
- `source.platform`
- `source.id`
- `source.part_id`
- `source.canonical_url`
- `source.title`
- `source.author`
- `summary.chapters`
- `summary.chapters[].timestamp_url`
- `transcript.segments`
- `provenance`

Recommended mapping:

| Bilifan bundle field | Nabaichuan record |
| --- | --- |
| `bundle_id` | video `source_id` |
| `source.title` | video title |
| `source.platform` | video platform |
| `source.author` | author/channel |
| `summary.chapters[]` | chapter notes/cards |
| `timestamp_url` | source backlink |
| `transcript.segments[]` | optional searchable transcript |

Use:

```bash
python examples/content_bundle_to_nabaichuan.py outputs/BV1abcDEF12G_p1/runs/2026-06-09_120000/content_bundle.json --out /tmp/nabaichuan.jsonl
```

The converter does not import Nabaichuan code and does not depend on Bilifan run directory internals.
```

- [ ] **Step 5: Run example tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_nabaichuan_example.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add examples/content_bundle_to_nabaichuan.py docs/nabaichuan-integration.md tests/test_nabaichuan_example.py
git commit -m "docs: add nabaichuan bundle integration example"
```

---

## Task 8: Update README and Final Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update README**

Add sections:

```markdown
## Content Bundle

Successful runs write `content_bundle.json`. This is the stable integration artifact for downstream tools such as Nabaichuan.

## Retry

Use `bilifan retry <run_dir> --from bundle|render|summarization` to regenerate downstream artifacts without downloading audio or rerunning Whisper.

## YouTube Scope

YouTube support is limited to public ordinary videos. Bilifan prefers subtitles and only falls back to Whisper when needed. Playlists, private videos, members-only videos, age-restricted videos, cookies, live streams, and Shorts-specific behavior are outside this phase.

## Nabaichuan

See `docs/nabaichuan-integration.md`.
```

- [ ] **Step 2: Run full tests**

Run:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
git diff --check
```

Expected:

```text
all tests pass
git diff --check exits 0
```

- [ ] **Step 3: Optional live smoke**

Run one Bilibili smoke:

```bash
.venv/bin/python -m bilifan summarize "https://www.bilibili.com/video/<public-bv>" --format html --yes-i-understand --out ./outputs
```

Run one retry smoke:

```bash
.venv/bin/python -m bilifan retry outputs/<output_id>/runs/<run_id> --from bundle
```

Run one Nabaichuan conversion:

```bash
python examples/content_bundle_to_nabaichuan.py outputs/<output_id>/runs/<run_id>/content_bundle.json --out /tmp/nabaichuan.jsonl
```

Run YouTube live smoke only when network and test video are explicitly approved:

```bash
BILIFAN_YOUTUBE_SMOKE=1 PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/test_youtube_smoke.py -q
```

- [ ] **Step 4: Commit README**

```bash
git add README.md
git commit -m "docs: document bundle retry and youtube scope"
```

- [ ] **Step 5: Push final branch**

```bash
git push origin codex/bilifan-foundation
```

---

## Execution Order and Agent Assignment

Recommended mode: `superpowers:subagent-driven-development`.

Run order:

1. Main agent executes Task 1 and Task 2 because they define the bundle contract.
2. Agent A executes Task 3 retry command after Task 2 is committed.
3. Agent B executes Task 4 and Task 5 source adapter migration.
4. Agent C executes Task 6 YouTube adapter after Task 4 is committed.
5. Agent D executes Task 7 Nabaichuan example after Task 1 is committed.
6. Main agent executes Task 8 and full verification.

Conflict rules:

- `pipeline.py` edits are owned by main agent.
- `cli.py` retry edits are owned by Agent A, then reviewed by main.
- `sources/` is owned by Agent B/C after base adapter commit.
- `examples/` and `docs/nabaichuan-integration.md` are owned by Agent D.
- Main agent resolves tests and final artifact link consistency.

---

## Self-Review

Spec coverage:

- Retry pipeline: Tasks 2 and 3.
- `content_bundle.json`: Tasks 1 and 2.
- SourceAdapter base: Task 4.
- Bilibili adapter migration: Task 5.
- YouTube adapter first version: Task 6.
- Nabaichuan ingest example: Task 7.
- Docs and final verification: Task 8.

Type consistency:

- `VideoRef`, `SourceOptions`, and `SourceAdapter` are introduced before use.
- `RetryRequest`, `RetryError`, and `retry_run` are introduced before CLI wiring.
- Bundle writer signatures are used consistently in pipeline, retry, and tests.

Implementation risk:

- Task 5 may need small test monkeypatch adjustments because current tests patch functions imported into `pipeline.py`.
- YouTube live behavior must remain optional; mocked fixtures are the required acceptance path.
- Retry from `summarization` and `render` should be implemented after bundle retry is green to keep the first retry slice controlled.
