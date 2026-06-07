# Bilifan Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first Bilifan foundation slice: Python package skeleton, `summarize` CLI preflight, current-P Bilibili URL parsing, first-run consent, versioned run directories, and sanitized diagnostics.

**Architecture:** Keep the first slice offline and deterministic. The CLI should parse and validate user intent, create a safe run workspace, and write diagnostics without calling `yt-dlp`, Whisper, Codex, Chrome, or the network. Later slices will plug ingest, media, transcript, LLM, and rendering into these stable boundaries.

**Tech Stack:** Python 3.11+, Typer, pytest, standard-library `urllib.parse`, `dataclasses`, `json`, `pathlib`, `os`, `stat`.

---

## Scope

This plan implements only the first foundation slice from `docs/superpowers/specs/2026-06-08-bilifan-mvp-design.md`.

Included:

- Project packaging and test harness.
- `bilifan summarize` command with offline preflight behavior.
- Current P parsing for canonical `https://www.bilibili.com/video/BV...` URLs.
- First-run and first-cookies consent persisted in a user config file outside the run output tree.
- Stable output ID: `BVxxxx_pN`.
- Versioned run directory under `outputs/<video-id>_pN/runs/<timestamp>/`.
- `latest.json` update without symlink dependency.
- Sanitized `diagnostics.json`.
- `_errors/runs/<timestamp>/diagnostics.json` for preflight `InputError` cases that do not yet have a stable BV/P id.

Excluded:

- `yt-dlp` metadata or media download.
- Whisper transcription.
- `codex exec` summary calls.
- HTML/PDF rendering.
- SVG diagrams.
- Local file input.
- Real cookies parsing or browser cookie extraction.
- Debug raw log persistence. The `--debug-log` flag may exist in the CLI, but this slice must reject it with a clear message.

## File Structure

- Create: `pyproject.toml`
  - Package metadata, console script, runtime dependency on Typer, dev dependency note for pytest.
- Create: `src/bilifan/__init__.py`
  - Package version.
- Create: `src/bilifan/__main__.py`
  - `python -m bilifan` entrypoint.
- Create: `src/bilifan/cli.py`
  - Typer app and `summarize` command.
- Create: `src/bilifan/bilibili.py`
  - Current-P URL parsing, URL sanitization, timestamp URL generation.
- Create: `src/bilifan/config.py`
  - User-level consent config read/write. Tests must inject the config root instead of writing the real user config.
- Create: `src/bilifan/runs.py`
  - Versioned run directory creation and `latest.json`.
- Create: `src/bilifan/diagnostics.py`
  - Structured diagnostics and redaction.
- Create: `tests/test_bilibili.py`
  - URL parsing and timestamp link tests.
- Create: `tests/test_config.py`
  - Consent config tests.
- Create: `tests/test_runs.py`
  - Run directory and `latest.json` tests.
- Create: `tests/test_diagnostics.py`
  - Redaction and diagnostics serialization tests.
- Create: `tests/test_cli.py`
  - CLI preflight integration tests.

## Public Behavior In This Slice

`bilifan summarize <url>` does not generate a report yet. It validates and prepares a run:

- If local-processing consent is missing and `--yes-i-understand` is not passed, prompt the user.
- If cookies flags are present and cookies consent is missing, prompt separately unless `--yes-i-understand` is passed.
- Parse the current P URL.
- Create a versioned run directory.
- Write `diagnostics.json` with `stage="preflight"` and warning `foundation_slice_only`.
- For invalid URLs, write sanitized diagnostics under `outputs/_errors/runs/<timestamp>/diagnostics.json` before returning a parameter error.
- Print the run directory path.
- Exit `0` on successful preflight.
- Reject `--debug-log` with a clear parameter error because raw debug logs are outside this slice.

This deliberately avoids fake metadata or fake report files.

---

### Task 1: Project Skeleton And CLI Entrypoint

**Files:**
- Create: `pyproject.toml`
- Create: `src/bilifan/__init__.py`
- Create: `src/bilifan/__main__.py`
- Create: `src/bilifan/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write the failing CLI smoke test**

Create `tests/test_cli.py`:

```python
from typer.testing import CliRunner

from bilifan.cli import app


runner = CliRunner()


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output
```

- [ ] **Step 2: Run the failing smoke test**

Run:

```bash
pytest tests/test_cli.py::test_cli_help_lists_summarize_command -v
```

Expected: FAIL because `bilifan.cli` does not exist.

- [ ] **Step 3: Add package skeleton and Typer app**

Create `pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "bilifan"
version = "0.1.0"
description = "Local Bilibili video learning-note generator"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
  "typer>=0.12,<1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8,<9",
]

[project.scripts]
bilifan = "bilifan.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

Create `src/bilifan/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/bilifan/__main__.py`:

```python
from .cli import main


if __name__ == "__main__":
    main()
```

Create `src/bilifan/cli.py`:

```python
import typer

app = typer.Typer(no_args_is_help=True)


@app.command()
def summarize(url: str) -> None:
    """Prepare a local Bilifan run for one Bilibili current-P URL."""
    typer.echo(f"preflight pending for {url}")


def main() -> None:
    app()
```

- [ ] **Step 4: Run the smoke test**

Run:

```bash
pytest tests/test_cli.py::test_cli_help_lists_summarize_command -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add pyproject.toml src/bilifan tests/test_cli.py
git commit -m "feat: add bilifan cli skeleton"
```

---

### Task 2: Current-P URL Parser

**Files:**
- Create: `src/bilifan/bilibili.py`
- Create: `tests/test_bilibili.py`

- [ ] **Step 1: Write parser tests**

Create `tests/test_bilibili.py`:

```python
import pytest

from bilifan.bilibili import BilibiliPartRef, parse_bilibili_url


def test_parse_bilibili_url_with_explicit_part_and_tracking_params():
    ref = parse_bilibili_url(
        "https://www.bilibili.com/video/BV1abcDEF12G/?p=2&spm_id_from=333.999"
    )

    assert ref == BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=2,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    )
    assert ref.output_id == "BV1abcDEF12G_p2"
    assert ref.timestamp_url(1234.7) == (
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=1234"
    )


def test_parse_bilibili_url_defaults_to_part_one():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G")

    assert ref.part_index == 1
    assert ref.sanitized_url == "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
    assert ref.output_id == "BV1abcDEF12G_p1"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/BV1abcDEF12G",
        "https://www.bilibili.com/read/cv123",
        "not a url",
    ],
)
def test_parse_bilibili_url_rejects_unsupported_urls(url):
    with pytest.raises(ValueError, match="supported Bilibili video URL"):
        parse_bilibili_url(url)


def test_parse_bilibili_url_rejects_invalid_part_index():
    with pytest.raises(ValueError, match="positive integer"):
        parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=0")
```

- [ ] **Step 2: Run parser tests and verify failure**

Run:

```bash
pytest tests/test_bilibili.py -v
```

Expected: FAIL because `bilifan.bilibili` does not exist.

- [ ] **Step 3: Implement current-P parser**

Create `src/bilifan/bilibili.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class BilibiliPartRef:
    bvid: str
    part_index: int
    sanitized_url: str

    @property
    def output_id(self) -> str:
        return f"{self.bvid}_p{self.part_index}"

    def timestamp_url(self, seconds: float) -> str:
        timestamp = max(0, int(seconds))
        return f"https://www.bilibili.com/video/{self.bvid}?p={self.part_index}&t={timestamp}"


def parse_bilibili_url(url: str) -> BilibiliPartRef:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Expected a supported Bilibili video URL.")
    if parsed.netloc not in {"www.bilibili.com", "bilibili.com"}:
        raise ValueError("Expected a supported Bilibili video URL.")

    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2 or parts[0] != "video" or not parts[1].startswith("BV"):
        raise ValueError("Expected a supported Bilibili video URL.")

    bvid = parts[1]
    query = parse_qs(parsed.query)
    raw_part = query.get("p", ["1"])[0]

    try:
        part_index = int(raw_part)
    except ValueError as exc:
        raise ValueError("Bilibili part index must be a positive integer.") from exc

    if part_index < 1:
        raise ValueError("Bilibili part index must be a positive integer.")

    sanitized_url = f"https://www.bilibili.com/video/{bvid}?p={part_index}"
    return BilibiliPartRef(
        bvid=bvid,
        part_index=part_index,
        sanitized_url=sanitized_url,
    )
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
pytest tests/test_bilibili.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/bilifan/bilibili.py tests/test_bilibili.py
git commit -m "feat: parse bilibili current part urls"
```

---

### Task 3: First-Run Consent Config

**Files:**
- Create: `src/bilifan/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write consent config tests**

Create `tests/test_config.py`:

```python
from datetime import datetime, timezone
from stat import S_IMODE

from bilifan.config import (
    ConsentConfig,
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    read_config,
    write_consent,
)


def test_read_config_returns_default_when_missing(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"

    config = read_config(config_path)

    assert config == ConsentConfig()


def test_default_config_path_uses_bilifan_config_home(tmp_path):
    config_path = default_config_path(env={"BILIFAN_CONFIG_HOME": str(tmp_path)})

    assert config_path == tmp_path / "config.json"


def test_write_local_processing_consent_persists_only_local_notice(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    write_consent(config_path, local_processing=True, accepted_via="test", now=now)

    config = read_config(config_path)
    assert has_local_processing_consent(config_path) is True
    assert has_cookies_consent(config_path) is False
    assert config.local_processing_notice_accepted_at == "2026-06-08T01:15:30+00:00"
    assert config.cookies_notice_accepted_at is None
    assert config.accepted_via == "test"
    assert S_IMODE(config_path.stat().st_mode) == 0o600


def test_write_cookies_consent_preserves_existing_local_notice(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"
    first = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    second = datetime(2026, 6, 8, 1, 16, 0, tzinfo=timezone.utc)

    write_consent(config_path, local_processing=True, accepted_via="test", now=first)
    write_consent(config_path, cookies=True, accepted_via="test", now=second)

    config = read_config(config_path)
    assert config.local_processing_notice_accepted_at == "2026-06-08T01:15:30+00:00"
    assert config.cookies_notice_accepted_at == "2026-06-08T01:16:00+00:00"
```

- [ ] **Step 2: Run consent tests and verify failure**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: FAIL because `bilifan.config` does not exist.

- [ ] **Step 3: Implement consent config**

Create `src/bilifan/config.py`:

```python
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Mapping

NOTICE_VERSION = "2026-06-08"


@dataclass(frozen=True)
class ConsentConfig:
    schema_version: int = 1
    notice_version: str = NOTICE_VERSION
    local_processing_notice_accepted_at: str | None = None
    cookies_notice_accepted_at: str | None = None
    accepted_via: str | None = None


def default_config_path(
    *,
    env: Mapping[str, str] | None = None,
    home: str | PathLike[str] | None = None,
) -> Path:
    env_map = os.environ if env is None else env
    if env_map.get("BILIFAN_CONFIG_HOME"):
        return Path(env_map["BILIFAN_CONFIG_HOME"]) / "config.json"
    if env_map.get("XDG_CONFIG_HOME"):
        return Path(env_map["XDG_CONFIG_HOME"]) / "bilifan" / "config.json"
    home_dir = Path(home) if home is not None else Path.home()
    return home_dir / ".config" / "bilifan" / "config.json"


def read_config(path: Path) -> ConsentConfig:
    if not path.exists():
        return ConsentConfig()

    data = json.loads(path.read_text(encoding="utf-8"))
    return ConsentConfig(
        schema_version=int(data.get("schema_version", 1)),
        notice_version=str(data.get("notice_version", NOTICE_VERSION)),
        local_processing_notice_accepted_at=data.get(
            "local_processing_notice_accepted_at"
        ),
        cookies_notice_accepted_at=data.get("cookies_notice_accepted_at"),
        accepted_via=data.get("accepted_via"),
    )


def has_local_processing_consent(path: Path) -> bool:
    return read_config(path).local_processing_notice_accepted_at is not None


def has_cookies_consent(path: Path) -> bool:
    return read_config(path).cookies_notice_accepted_at is not None


def write_consent(
    path: Path,
    *,
    local_processing: bool = False,
    cookies: bool = False,
    accepted_via: str = "cli",
    now: datetime | None = None,
) -> None:
    current = read_config(path)
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)

    local_accepted_at = current.local_processing_notice_accepted_at
    cookies_accepted_at = current.cookies_notice_accepted_at
    if local_processing and local_accepted_at is None:
        local_accepted_at = timestamp
    if cookies and cookies_accepted_at is None:
        cookies_accepted_at = timestamp

    data = {
        "schema_version": 1,
        "notice_version": NOTICE_VERSION,
        "local_processing_notice_accepted_at": local_accepted_at,
        "cookies_notice_accepted_at": cookies_accepted_at,
        "accepted_via": accepted_via,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
```

- [ ] **Step 4: Run consent tests**

Run:

```bash
pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/bilifan/config.py tests/test_config.py
git commit -m "feat: persist local processing consent"
```

---

### Task 4: Versioned Run Directories

**Files:**
- Create: `src/bilifan/runs.py`
- Create: `tests/test_runs.py`

- [ ] **Step 1: Write run directory tests**

Create `tests/test_runs.py`:

```python
import json
from datetime import datetime, timezone

import pytest

from bilifan.bilibili import BilibiliPartRef
from bilifan.runs import create_error_run, create_run


def test_create_run_uses_stable_output_id_and_updates_latest(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=2,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    run = create_run(tmp_path / "outputs", ref, now=now)

    assert run.video_dir == tmp_path / "outputs" / "BV1abcDEF12G_p2"
    assert run.run_dir == run.video_dir / "runs" / "2026-06-08_011530"
    assert run.run_dir.is_dir()

    latest = json.loads((run.video_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "2026-06-08_011530"
    assert latest["run_dir"] == "runs/2026-06-08_011530"
    assert latest["generated_at"] == "2026-06-08T01:15:30+00:00"
    assert latest["input_url_sanitized"] == "https://www.bilibili.com/video/BV1abcDEF12G?p=2"


def test_create_run_refuses_existing_run_without_overwrite(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    create_run(tmp_path / "outputs", ref, now=now)

    with pytest.raises(FileExistsError, match="already exists"):
        create_run(tmp_path / "outputs", ref, now=now)


def test_create_run_allows_overwrite(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    first = create_run(tmp_path / "outputs", ref, now=now)
    second = create_run(tmp_path / "outputs", ref, now=now, overwrite=True)

    assert second.run_dir == first.run_dir


def test_create_error_run_does_not_update_video_latest(tmp_path):
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    run = create_error_run(tmp_path / "outputs", now=now)

    assert run.video_dir == tmp_path / "outputs" / "_errors"
    assert run.run_dir == run.video_dir / "runs" / "2026-06-08_011530"
    assert run.run_dir.is_dir()
    assert not (run.video_dir / "latest.json").exists()
```

- [ ] **Step 2: Run run directory tests and verify failure**

Run:

```bash
pytest tests/test_runs.py -v
```

Expected: FAIL because `bilifan.runs` does not exist.

- [ ] **Step 3: Implement run directory creation**

Create `src/bilifan/runs.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .bilibili import BilibiliPartRef


@dataclass(frozen=True)
class RunPaths:
    video_dir: Path
    run_dir: Path
    run_id: str


def _run_id(now: datetime | None = None) -> tuple[str, datetime]:
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y-%m-%d_%H%M%S"), current


def create_run(
    out_dir: Path,
    ref: BilibiliPartRef,
    *,
    now: datetime | None = None,
    overwrite: bool = False,
) -> RunPaths:
    run_id, current = _run_id(now)
    video_dir = out_dir / ref.output_id
    run_dir = video_dir / "runs" / run_id

    if run_dir.exists() and not overwrite:
        raise FileExistsError(f"Run directory already exists: {run_dir}")

    run_dir.mkdir(parents=True, exist_ok=overwrite)

    latest = {
        "run_id": run_id,
        "run_dir": f"runs/{run_id}",
        "generated_at": current.isoformat(),
        "input_url_sanitized": ref.sanitized_url,
    }
    video_dir.mkdir(parents=True, exist_ok=True)
    (video_dir / "latest.json").write_text(
        json.dumps(latest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    return RunPaths(video_dir=video_dir, run_dir=run_dir, run_id=run_id)


def create_error_run(out_dir: Path, *, now: datetime | None = None) -> RunPaths:
    run_id, _current = _run_id(now)
    video_dir = out_dir / "_errors"
    run_dir = video_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return RunPaths(video_dir=video_dir, run_dir=run_dir, run_id=run_id)
```

- [ ] **Step 4: Run run directory tests**

Run:

```bash
pytest tests/test_runs.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/bilifan/runs.py tests/test_runs.py
git commit -m "feat: create versioned bilifan run directories"
```

---

### Task 5: Sanitized Diagnostics

**Files:**
- Create: `src/bilifan/diagnostics.py`
- Create: `tests/test_diagnostics.py`

- [ ] **Step 1: Write diagnostics tests**

Create `tests/test_diagnostics.py`:

```python
import json

import pytest

from bilifan.diagnostics import (
    Diagnostics,
    redact_text,
    validate_artifact_paths,
    write_diagnostics,
)


def test_redact_text_removes_sensitive_values(tmp_path):
    home = tmp_path / "Users" / "jack"
    message = (
        "failed with /Users/jack/Downloads/bili-cookies.txt "
        "and CODEX_ACCESS_TOKEN=secret "
        "and Authorization: Bearer sk-testsecret "
        "and Cookie: SESSDATA=abc; bili_jct=def; DedeUserID=123 "
        "inside /Volumes/mySSD/projects/bilifan "
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999&vd_source=secret"
    )

    redacted = redact_text(message, home_markers=[home])

    assert "bili-cookies.txt" not in redacted
    assert "secret" not in redacted
    assert "spm_id_from" not in redacted
    assert "vd_source" not in redacted
    assert "SESSDATA=abc" not in redacted
    assert "bili_jct=def" not in redacted
    assert "Bearer sk-" not in redacted
    assert "/Users/jack" not in redacted
    assert "/Volumes/mySSD" not in redacted
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2" in redacted


def test_validate_artifact_paths_requires_relative_run_paths():
    assert validate_artifact_paths(["diagnostics.json", "assets/cover.jpg"]) == [
        "diagnostics.json",
        "assets/cover.jpg",
    ]

    with pytest.raises(ValueError, match="relative"):
        validate_artifact_paths(["/Users/jack/report.html"])

    with pytest.raises(ValueError, match="relative"):
        validate_artifact_paths(["../report.html"])


def test_write_diagnostics_uses_allowlisted_fields(tmp_path):
    path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type=None,
        exit_code=0,
        stage="preflight",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check=None,
        transcript_check=None,
        artifact_paths=["diagnostics.json"],
        sanitized_message="Prepared run with CODEX_ACCESS_TOKEN=secret",
        warnings=["foundation_slice_only"],
    )

    write_diagnostics(path, diagnostics)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert sorted(data) == [
        "artifact_paths",
        "duration_check",
        "error_type",
        "exit_code",
        "part_index",
        "sanitized_message",
        "stage",
        "transcript_check",
        "video_id",
        "warnings",
    ]
    serialized = json.dumps(data, ensure_ascii=False)
    assert "secret" not in serialized
    assert "CODEX_ACCESS_TOKEN=<redacted>" in serialized
    assert data["warnings"] == ["foundation_slice_only"]
```

- [ ] **Step 2: Run diagnostics tests and verify failure**

Run:

```bash
pytest tests/test_diagnostics.py -v
```

Expected: FAIL because `bilifan.diagnostics` does not exist.

- [ ] **Step 3: Implement diagnostics and redaction**

Create `src/bilifan/diagnostics.py`:

```python
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from dataclasses import replace
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

MAX_MESSAGE_LENGTH = 4096


@dataclass(frozen=True)
class Diagnostics:
    error_type: str | None
    exit_code: int
    stage: str
    video_id: str
    part_index: int
    duration_check: dict | None
    transcript_check: dict | None
    artifact_paths: list[str]
    sanitized_message: str
    warnings: list[str]


def redact_text(text: str, *, home_markers: list[Path] | None = None) -> str:
    redacted = text[:MAX_MESSAGE_LENGTH]
    redacted = re.sub(
        r"(CODEX_ACCESS_TOKEN|OPENAI_API_KEY|CODEX_API_KEY)=\S+",
        r"\1=<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"Authorization:\s*Bearer\s+\S+",
        "Authorization: Bearer <redacted>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", redacted)
    redacted = re.sub(r"eyJ[A-Za-z0-9._-]+", "<jwt-redacted>", redacted)
    redacted = re.sub(
        r"(SESSDATA|bili_jct|DedeUserID|buvid\w*|sid)=([^;\s]+)",
        r"\1=<redacted>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = re.sub(
        r"\S*cookies?\S*\.txt",
        "<cookies-file>",
        redacted,
        flags=re.IGNORECASE,
    )
    redacted = _sanitize_bilibili_urls(redacted)

    for marker in home_markers or []:
        marker_text = str(marker)
        if marker_text:
            redacted = redacted.replace(marker_text, "<home>")

    redacted = redacted.replace("/Users/jack", "<home>")
    redacted = re.sub(r"/Users/[^\s]+", "<home-path>", redacted)
    redacted = re.sub(r"/Volumes/[^\s]+", "<volume-path>", redacted)
    redacted = re.sub(r"~/[^\s]+", "<home-path>", redacted)
    return redacted


def validate_artifact_paths(paths: list[str]) -> list[str]:
    safe_paths: list[str] = []
    for raw_path in paths:
        path = PurePosixPath(raw_path)
        if raw_path.startswith("/") or ".." in path.parts:
            raise ValueError("Artifact paths must be relative paths inside the run directory.")
        safe_paths.append(str(path))
    return safe_paths


def write_diagnostics(path: Path, diagnostics: Diagnostics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_diagnostics = replace(
        diagnostics,
        artifact_paths=validate_artifact_paths(diagnostics.artifact_paths),
        sanitized_message=redact_text(diagnostics.sanitized_message),
    )
    path.write_text(
        json.dumps(asdict(safe_diagnostics), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _sanitize_bilibili_urls(text: str) -> str:
    pattern = re.compile(r"https?://(?:www\.)?bilibili\.com/video/BV[\w]+[^\s]*")
    return pattern.sub(lambda match: _sanitize_one_url(match.group(0)), text)


def _sanitize_one_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    part = query.get("p", ["1"])[0]
    bvid = parsed.path.rstrip("/").split("/")[-1]
    return f"https://www.bilibili.com/video/{bvid}?p={part}"
```

- [ ] **Step 4: Run diagnostics tests**

Run:

```bash
pytest tests/test_diagnostics.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

```bash
git add src/bilifan/diagnostics.py tests/test_diagnostics.py
git commit -m "feat: write sanitized diagnostics"
```

---

### Task 6: Summarize Preflight Integration

**Files:**
- Modify: `src/bilifan/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add CLI preflight tests**

Append to `tests/test_cli.py`:

```python
import json


def test_summarize_requires_consent_without_yes_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    result = runner.invoke(
        app,
        ["summarize", "https://www.bilibili.com/video/BV1abcDEF12G?p=2"],
        input="n\n",
    )

    assert result.exit_code == 1
    assert "Continue?" in result.output
    assert not (tmp_path / "config" / "config.json").exists()


def test_summarize_prepares_run_with_yes_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
    )

    assert result.exit_code == 0
    assert "Prepared Bilifan run" in result.output

    video_dir = tmp_path / "outputs" / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    diagnostics_path = video_dir / latest["run_dir"] / "diagnostics.json"
    diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))

    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["warnings"] == ["foundation_slice_only"]
    assert (tmp_path / "config" / "config.json").exists()


def test_summarize_records_cookie_notice_when_cookie_flags_are_used(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
    )

    assert result.exit_code == 0
    config_text = (tmp_path / "config" / "config.json").read_text(encoding="utf-8")
    assert "local_processing_notice_accepted_at" in config_text
    assert "cookies_notice_accepted_at" in config_text
    assert "bili-cookies.txt" not in config_text


def test_summarize_rejects_invalid_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=secret",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
    )

    assert result.exit_code == 2
    assert "supported Bilibili video URL" in result.output
    diagnostics_files = list((tmp_path / "outputs" / "_errors" / "runs").glob("*/diagnostics.json"))
    assert len(diagnostics_files) == 1
    diagnostics = json.loads(diagnostics_files[0].read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "InputError"
    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == ""
    assert diagnostics["part_index"] == 0
    assert "vd_source" not in diagnostics["sanitized_message"]


def test_summarize_rejects_debug_log_in_foundation_slice(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://www.bilibili.com/video/BV1abcDEF12G",
            "--debug-log",
            "--yes-i-understand",
        ],
    )

    assert result.exit_code == 2
    assert "--debug-log is reserved for a later slice" in result.output
```

- [ ] **Step 2: Run CLI integration tests and verify failure**

Run:

```bash
pytest tests/test_cli.py -v
```

Expected: FAIL because `summarize` has not wired parser, consent, runs, or diagnostics.

- [ ] **Step 3: Implement CLI preflight**

Replace `src/bilifan/cli.py` with:

```python
from __future__ import annotations

from pathlib import Path

import typer

from .bilibili import parse_bilibili_url
from .config import (
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    write_consent,
)
from .diagnostics import Diagnostics, redact_text, write_diagnostics
from .runs import create_error_run, create_run

app = typer.Typer(no_args_is_help=True)

CONSENT_TEXT = (
    "Bilifan runs locally and processes only URLs you provide.\n"
    "You are responsible for having permission to access and summarize the content.\n"
    "Bilifan does not bypass access controls or store cookies in reports."
)


@app.command()
def summarize(
    url: str,
    out: Path = typer.Option(Path("./outputs"), "--out"),
    cookies_from_browser: str | None = typer.Option(None, "--cookies-from-browser"),
    cookies_file: Path | None = typer.Option(None, "--cookies-file"),
    yes_i_understand: bool = typer.Option(False, "--yes-i-understand"),
    overwrite: bool = typer.Option(False, "--overwrite"),
    debug_log: bool = typer.Option(False, "--debug-log"),
) -> None:
    """Prepare a local Bilifan run for one Bilibili current-P URL."""
    if debug_log:
        raise typer.BadParameter("--debug-log is reserved for a later slice.")

    try:
        ref = parse_bilibili_url(url)
    except ValueError as exc:
        error_run = create_error_run(out)
        diagnostics = Diagnostics(
            error_type="InputError",
            exit_code=2,
            stage="preflight",
            video_id="",
            part_index=0,
            duration_check=None,
            transcript_check=None,
            artifact_paths=["diagnostics.json"],
            sanitized_message=redact_text(f"{exc}: {url}"),
            warnings=[],
        )
        write_diagnostics(error_run.run_dir / "diagnostics.json", diagnostics)
        raise typer.BadParameter(redact_text(str(exc))) from exc

    config_path = default_config_path()
    uses_cookies = cookies_from_browser is not None or cookies_file is not None
    _ensure_consent(
        config_path,
        yes_i_understand=yes_i_understand,
        uses_cookies=uses_cookies,
    )

    run = create_run(out, ref, overwrite=overwrite)

    diagnostics = Diagnostics(
        error_type=None,
        exit_code=0,
        stage="preflight",
        video_id=ref.bvid,
        part_index=ref.part_index,
        duration_check=None,
        transcript_check=None,
        artifact_paths=[],
        sanitized_message=redact_text(f"Prepared run for {ref.sanitized_url}"),
        warnings=["foundation_slice_only"],
    )
    write_diagnostics(run.run_dir / "diagnostics.json", diagnostics)
    typer.echo(f"Prepared Bilifan run: {run.run_dir}")


def _ensure_consent(
    config_path: Path,
    *,
    yes_i_understand: bool,
    uses_cookies: bool,
) -> None:
    needs_local_notice = not has_local_processing_consent(config_path)
    needs_cookies_notice = uses_cookies and not has_cookies_consent(config_path)

    if not needs_local_notice and not needs_cookies_notice:
        return

    if yes_i_understand:
        write_consent(
            config_path,
            local_processing=needs_local_notice,
            cookies=needs_cookies_notice,
            accepted_via="yes-i-understand",
        )
        return

    if needs_local_notice:
        typer.echo(CONSENT_TEXT)
        accepted = typer.confirm("Continue?", default=False)
        if not accepted:
            raise typer.Exit(code=1)
        write_consent(config_path, local_processing=True)

    if needs_cookies_notice:
        typer.echo("Cookies are only used locally for content your account can already view.")
        accepted = typer.confirm("Continue with cookies?", default=False)
        if not accepted:
            raise typer.Exit(code=1)
        write_consent(config_path, cookies=True)


def main() -> None:
    app()
```

- [ ] **Step 4: Run all first-slice tests**

Run:

```bash
pytest -v
```

Expected: PASS for all tests in this first slice.

- [ ] **Step 5: Run CLI manually**

Run:

```bash
python -m bilifan summarize "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999" --yes-i-understand --out /tmp/bilifan-plan-smoke
```

Expected: prints `Prepared Bilifan run: .../BV1abcDEF12G_p2/runs/<timestamp>` and writes a `diagnostics.json`.

- [ ] **Step 6: Commit**

Run:

```bash
git add src/bilifan/cli.py tests/test_cli.py
git commit -m "feat: prepare bilifan summarize preflight"
```

---

### Task 7: Documentation For Foundation Slice

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write README assertions as a documentation checklist**

Create `README.md`:

```markdown
# Bilifan

Bilifan is a local Bilibili video learning-note generator.

The current implementation is an early foundation slice. It prepares a local run
directory for one Bilibili current-P URL, records consent in your user config
directory, and writes sanitized diagnostics. It does not yet download media,
transcribe audio, call Codex, or render HTML/PDF reports.

## Boundaries

- Bilifan runs locally and processes only URLs you provide.
- Bilifan does not provide a hosted scraping service.
- Bilifan does not include Bilibili cookies.
- Bilifan does not bypass login, payment, region, risk-control, DRM, or access controls.
- You are responsible for having permission to access and summarize the content.
- If you provide cookies in future versions, they must only be used locally for content your account can already view.
- Future Codex-backed summarization may send transcript text to the model service configured in your local Codex environment.

## First Slice Usage

```bash
python -m bilifan summarize "https://www.bilibili.com/video/BV...?p=2" \
  --yes-i-understand \
  --out ./outputs
```

This creates:

```text
outputs/
  BV..._p2/
    latest.json
    runs/
      <timestamp>/
        diagnostics.json
```

## Not Implemented Yet

- `yt-dlp` metadata extraction.
- Audio download.
- Whisper transcription.
- `codex exec` summarization.
- HTML/PDF rendering.
```

- [ ] **Step 2: Verify README mentions required boundaries**

Run:

```bash
rg -n "does not bypass|does not include Bilibili cookies|does not provide a hosted scraping service|not yet download" README.md
```

Expected: four matching lines.

- [ ] **Step 3: Run full tests**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

Run:

```bash
git add README.md
git commit -m "docs: document bilifan foundation slice"
```

---

## Plan Self-Review

Spec coverage in this plan:

- Current-P URL parsing: Task 2.
- First-run and cookies confirmation: Task 3 and Task 6.
- Stable output ID and versioned run directories: Task 4 and Task 6.
- `latest.json` with relative run path and sanitized URL: Task 4.
- Sanitized diagnostics with allowlisted fields and relative artifact paths: Task 5 and Task 6.
- Public boundary documentation for the foundation slice: Task 7.

Deliberate gaps for later plans:

- Formal JSON Schema files for LLM outputs are not part of this foundation slice.
- `yt-dlp`, `ffprobe`, Whisper, `codex exec`, HTML, PDF, SVG, and real cookies handling are excluded.
- `--debug-log` raw persistence is explicitly rejected in this slice.

Subagent review adjustments incorporated:

- Consent config uses a user config file outside `outputs/` and tests inject `BILIFAN_CONFIG_HOME`.
- Cookies notice is separate from local-processing notice.
- Invalid URL `InputError` writes diagnostics under `outputs/_errors/runs/<timestamp>/`.
- Future Codex summarization is documented as potentially sending transcript text to the configured model service.

---

## Final Verification

- [ ] Run all tests:

```bash
pytest -v
```

Expected: PASS.

- [ ] Check worktree:

```bash
git status --short
```

Expected: no uncommitted source changes.

- [ ] Confirm commit history includes foundation tasks:

```bash
git log --oneline -8
```

Expected: includes the task commits from this plan.

## Known Follow-Up Plans

- `ingest/media`: wire `yt-dlp`, current-P metadata, cover download, audio download, `ffprobe` duration validation.
- `transcript`: subtitle-first transcript extraction and Whisper fallback.
- `llm`: `codex exec --output-schema` chunk summary and merge summary.
- `render`: offline HTML and best-effort PDF.
- `visual`: optional `--with-diagrams`.
