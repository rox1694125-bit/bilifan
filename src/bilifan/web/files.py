from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

OUTPUT_ID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}_p[1-9][0-9]*")
RUN_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}")
CHUNK_FILE_PATTERN = re.compile(r"chunk_[0-9]+\.json")
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
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(latest, dict):
            continue

        run_id = _run_id_from_latest(latest)
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
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
            if path.is_file() and _is_valid_chunk_file(path.name)
        )
    return files


def resolve_run_file(outputs: Path, output_id: str, run_id: str, file_path: str) -> Path:
    if "\\" in file_path:
        raise ValueError("Invalid file path.")
    posix = PurePosixPath(file_path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Invalid file path.")
    is_allowed = _is_allowed_run_file(posix)
    if not is_allowed:
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
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
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


def _is_valid_chunk_file(name: str) -> bool:
    return CHUNK_FILE_PATTERN.fullmatch(name) is not None


def _is_allowed_run_file(path: PurePosixPath) -> bool:
    return str(path) in ROOT_FILES or (
        len(path.parts) == 2
        and path.parts[0] == "partial_summaries"
        and _is_valid_chunk_file(path.parts[1])
    )
