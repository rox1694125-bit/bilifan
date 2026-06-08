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
