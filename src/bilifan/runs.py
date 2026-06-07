from __future__ import annotations

import json
import shutil
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
    if run_dir.exists():
        shutil.rmtree(run_dir)

    run_dir.mkdir(parents=True, exist_ok=False)

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
