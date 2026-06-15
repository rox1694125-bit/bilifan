from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from .jobs import explain_failure, retry_actions_for
from .run_info import transcript_source_label

OUTPUT_ID_PATTERN = re.compile(
    r"(?:(?:BV[0-9A-Za-z]{10}|YT[0-9A-Za-z_-]{6,128})_p[1-9][0-9]*|_errors)"
)
RUN_ID_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{6}")
CHUNK_FILE_PATTERN = re.compile(r"chunk_[0-9]+\.json")
FRAME_FILE_PATTERN = re.compile(r"chapter_[0-9]{3}_[0-9]{6}\.jpg")
ROOT_FILES = {
    "metadata.json",
    "transcript.json",
    "chunks.json",
    "chapters.json",
    "diagnostics.json",
    "content_bundle.json",
    "report.html",
    "report.pdf",
    "transcript.txt",
    "transcript.srt",
    "notes.md",
    "nabaichuan.jsonl",
}
MEDIA_FILES = {"media/audio.mp3"}


def list_latest_runs(outputs: Path) -> list[dict[str, Any]]:
    if not outputs.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for latest_path in sorted(outputs.glob("*/latest.json")):
        output_id = latest_path.parent.name
        if OUTPUT_ID_PATTERN.fullmatch(output_id) is None:
            continue
        video_dir = _safe_existing_dir(outputs, output_id)
        if video_dir is None:
            continue
        latest_file = _safe_existing_file(video_dir, "latest.json")
        if latest_file is None:
            continue
        try:
            latest = json.loads(latest_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(latest, dict):
            continue

        run_id = _run_id_from_latest(latest)
        if RUN_ID_PATTERN.fullmatch(run_id) is None:
            continue

        try:
            run_dir = _run_dir(outputs, output_id, run_id)
        except ValueError:
            continue
        diagnostics = _read_json_object(
            _safe_existing_file(run_dir, "diagnostics.json")
        )
        metadata = _read_json_object(_safe_existing_file(run_dir, "metadata.json"))
        transcript = _read_json_object(_safe_existing_file(run_dir, "transcript.json"))
        status = "failed" if diagnostics.get("error_type") else "succeeded"
        stage = _text(diagnostics.get("stage"))
        artifact_paths = _text_list(diagnostics.get("artifact_paths"))
        warnings = _text_list(diagnostics.get("warnings"))
        items.append(
            {
                "run_key": f"{output_id}/runs/{run_id}",
                "output_id": output_id,
                "run_id": run_id,
                "title": _text(metadata.get("title")) or output_id,
                "status": status,
                "stage": stage,
                "transcript_source_label": transcript_source_label(transcript),
                "generated_at": _text(latest.get("generated_at")),
                "artifacts": _artifact_links(
                    f"{output_id}/runs/{run_id}",
                    run_dir,
                    artifact_paths=artifact_paths if status == "failed" else None,
                ),
                "friendly_error": (
                    explain_failure(
                        stage=stage,
                        message=_text(diagnostics.get("sanitized_message")),
                        warnings=warnings,
                    )
                    if status == "failed"
                    else None
                ),
                "retry_actions": (
                    retry_actions_for(stage, artifact_paths)
                    if status == "failed"
                    else []
                ),
            }
        )
    return sorted(items, key=lambda item: item["generated_at"], reverse=True)


def list_all_runs(outputs: Path) -> list[dict[str, Any]]:
    if not outputs.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for video_dir in sorted(outputs.iterdir()):
        output_id = video_dir.name
        if OUTPUT_ID_PATTERN.fullmatch(output_id) is None:
            continue
        safe_video_dir = _safe_existing_dir(outputs, output_id)
        if safe_video_dir is None:
            continue
        runs_dir = _safe_existing_dir(safe_video_dir, "runs")
        if runs_dir is None:
            continue
        for run_dir in sorted(runs_dir.iterdir()):
            run_id = run_dir.name
            if RUN_ID_PATTERN.fullmatch(run_id) is None:
                continue
            try:
                safe_run_dir = _run_dir(outputs, output_id, run_id)
            except ValueError:
                continue
            if (
                not safe_run_dir.is_dir()
                or safe_run_dir.resolve(strict=False) != run_dir.resolve(strict=False)
            ):
                continue
            items.append(_run_item(outputs, output_id, run_id, generated_at=""))
    return sorted(items, key=lambda item: (item["generated_at"], item["run_key"]), reverse=True)


def list_run_files(outputs: Path, output_id: str, run_id: str) -> list[str]:
    run_dir = _run_dir(outputs, output_id, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"{output_id}/runs/{run_id}")
    files = [
        name
        for name in sorted(ROOT_FILES)
        if _safe_existing_file(run_dir, name) is not None
    ]
    files.extend(
        name
        for name in sorted(MEDIA_FILES)
        if _safe_existing_file(run_dir, name) is not None
    )
    partial_dir = _safe_existing_dir(run_dir, "partial_summaries")
    if partial_dir is not None:
        files.extend(
            relative_path
            for path in sorted(partial_dir.glob("*.json"))
            for relative_path in [f"partial_summaries/{path.name}"]
            if _is_valid_chunk_file(path.name)
            and _safe_existing_file(run_dir, relative_path) is not None
        )
    frame_dir = _safe_existing_dir(run_dir, "media/frames")
    if frame_dir is not None:
        files.extend(
            relative_path
            for path in sorted(frame_dir.glob("*.jpg"))
            for relative_path in [f"media/frames/{path.name}"]
            if _is_valid_frame_file(path.name)
            and _safe_existing_file(run_dir, relative_path) is not None
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
    resolved = _safe_existing_file(run_dir, file_path)
    if resolved is not None:
        return resolved
    fallback = (run_dir / file_path).resolve(strict=False)
    if not fallback.is_relative_to(run_dir.resolve(strict=False)):
        raise ValueError("File resolves outside run directory.")
    raise FileNotFoundError(file_path)


def open_run_folder(outputs: Path, output_id: str, run_id: str) -> None:
    run_dir = resolve_run_dir(outputs, output_id, run_id)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"{output_id}/runs/{run_id}")
    if platform.system() != "Darwin":
        raise RuntimeError("Opening run folders is only supported on macOS.")
    try:
        result = subprocess.run(
            ["open", str(run_dir)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("macOS open command failed.") from exc
    if result.returncode != 0:
        raise RuntimeError("macOS open command failed.")


def resolve_run_dir(outputs: Path, output_id: str, run_id: str) -> Path:
    return _run_dir(outputs, output_id, run_id)


def _run_dir(outputs: Path, output_id: str, run_id: str) -> Path:
    if OUTPUT_ID_PATTERN.fullmatch(output_id) is None or RUN_ID_PATTERN.fullmatch(run_id) is None:
        raise ValueError("Invalid run key.")
    run_dir = (outputs / output_id / "runs" / run_id).resolve(strict=False)
    if not run_dir.is_relative_to(outputs.resolve(strict=False)):
        raise ValueError("Run resolves outside outputs.")
    return run_dir


def _run_item(
    outputs: Path,
    output_id: str,
    run_id: str,
    *,
    generated_at: str,
) -> dict[str, Any]:
    run_dir = _run_dir(outputs, output_id, run_id)
    diagnostics = _read_json_object(_safe_existing_file(run_dir, "diagnostics.json"))
    metadata = _read_json_object(_safe_existing_file(run_dir, "metadata.json"))
    transcript = _read_json_object(_safe_existing_file(run_dir, "transcript.json"))
    status = "failed" if diagnostics.get("error_type") else "succeeded"
    stage = _text(diagnostics.get("stage"))
    artifact_paths = _text_list(diagnostics.get("artifact_paths"))
    warnings = _text_list(diagnostics.get("warnings"))
    return {
        "run_key": f"{output_id}/runs/{run_id}",
        "output_id": output_id,
        "run_id": run_id,
        "title": _text(metadata.get("title")) or output_id,
        "status": status,
        "stage": stage,
        "transcript_source_label": transcript_source_label(transcript),
        "generated_at": generated_at,
        "artifacts": _artifact_links(
            f"{output_id}/runs/{run_id}",
            run_dir,
            artifact_paths=artifact_paths if status == "failed" else None,
        ),
        "friendly_error": (
            explain_failure(
                stage=stage,
                message=_text(diagnostics.get("sanitized_message")),
                warnings=warnings,
            )
            if status == "failed"
            else None
        ),
        "retry_actions": (
            retry_actions_for(stage, artifact_paths) if status == "failed" else []
        ),
    }


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


def _read_json_object(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _artifact_links(
    run_key: str,
    run_dir: Path,
    *,
    artifact_paths: list[str] | None = None,
) -> dict[str, str]:
    prefix = f"/api/runs/{run_key}/files"
    if artifact_paths is not None:
        return _artifact_links_from_paths(prefix, run_key, run_dir, artifact_paths)
    artifacts: dict[str, str] = {}
    if _safe_existing_file(run_dir, "report.html") is not None:
        artifacts["html"] = f"{prefix}/report.html"
    if _safe_existing_file(run_dir, "report.pdf") is not None:
        artifacts["pdf"] = f"{prefix}/report.pdf"
    if _safe_existing_file(run_dir, "diagnostics.json") is not None:
        artifacts["diagnostics"] = f"{prefix}/diagnostics.json"
    if _safe_existing_file(run_dir, "transcript.txt") is not None:
        artifacts["txt"] = f"{prefix}/transcript.txt"
    if _safe_existing_file(run_dir, "transcript.srt") is not None:
        artifacts["srt"] = f"{prefix}/transcript.srt"
    if _safe_existing_file(run_dir, "notes.md") is not None:
        artifacts["md"] = f"{prefix}/notes.md"
    if _safe_existing_file(run_dir, "content_bundle.json") is not None:
        artifacts["bundle"] = f"{prefix}/content_bundle.json"
    if _safe_existing_file(run_dir, "nabaichuan.jsonl") is not None:
        artifacts["nabaichuan"] = f"{prefix}/nabaichuan.jsonl"
    if _safe_existing_file(run_dir, "media/audio.mp3") is not None:
        artifacts["audio"] = f"{prefix}/media/audio.mp3"
    artifacts["folder"] = f"/api/runs/{run_key}/open-folder"
    return artifacts


def _artifact_links_from_paths(
    prefix: str,
    run_key: str,
    run_dir: Path,
    artifact_paths: list[str],
) -> dict[str, str]:
    artifact_set = set(artifact_paths)
    artifacts: dict[str, str] = {}
    known_artifacts = {
        "html": "report.html",
        "pdf": "report.pdf",
        "diagnostics": "diagnostics.json",
        "txt": "transcript.txt",
        "srt": "transcript.srt",
        "md": "notes.md",
        "bundle": "content_bundle.json",
        "nabaichuan": "nabaichuan.jsonl",
        "audio": "media/audio.mp3",
    }
    for key, relative_path in known_artifacts.items():
        if (
            relative_path in artifact_set
            and _safe_existing_file(run_dir, relative_path) is not None
        ):
            artifacts[key] = f"{prefix}/{relative_path}"
    if artifact_paths:
        artifacts["folder"] = f"/api/runs/{run_key}/open-folder"
    return artifacts


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _is_valid_chunk_file(name: str) -> bool:
    return CHUNK_FILE_PATTERN.fullmatch(name) is not None


def _is_valid_frame_file(name: str) -> bool:
    return FRAME_FILE_PATTERN.fullmatch(name) is not None


def _is_allowed_run_file(path: PurePosixPath) -> bool:
    return str(path) in ROOT_FILES or str(path) in MEDIA_FILES or (
        len(path.parts) == 2
        and path.parts[0] == "partial_summaries"
        and _is_valid_chunk_file(path.parts[1])
    ) or (
        len(path.parts) == 3
        and path.parts[0] == "media"
        and path.parts[1] == "frames"
        and _is_valid_frame_file(path.parts[2])
    )


def _safe_existing_file(root_dir: Path, relative_path: str) -> Path | None:
    resolved_root_dir = root_dir.resolve(strict=False)
    resolved = (root_dir / relative_path).resolve(strict=False)
    if not resolved.is_relative_to(resolved_root_dir):
        return None
    return resolved if resolved.is_file() else None


def _safe_existing_dir(root_dir: Path, relative_path: str) -> Path | None:
    resolved_root_dir = root_dir.resolve(strict=False)
    resolved = (root_dir / relative_path).resolve(strict=False)
    if not resolved.is_relative_to(resolved_root_dir):
        return None
    return resolved if resolved.is_dir() else None
