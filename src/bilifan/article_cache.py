"""Per-run checkpoints outside publication workspaces; never export this state."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import re
import uuid
from pathlib import Path
from typing import Any, Callable

CACHE_SCHEMA_VERSION = 1


def sidecar_directory(run_dir: Path) -> Path:
    run = Path(run_dir).resolve()
    return run.parent / ".workbench-state" / run.name


def cache_directory(run_dir: Path) -> Path:
    """The caller must pass the original run, never its temporary retry copy."""
    return sidecar_directory(run_dir) / "article-cache"



def active_generation(directory: Path, *, force: bool = False) -> Path:
    """Force starts a fresh generation; later normal resumes only that generation."""
    marker = Path(directory) / "active.json"
    generation = None
    if not force:
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            candidate = payload.get("generation") if isinstance(payload, dict) else None
            if isinstance(candidate, str) and re.fullmatch(r"[a-f0-9]{32}", candidate):
                generation = candidate
        except (OSError, ValueError):
            pass
    if generation is None:
        generation = uuid.uuid4().hex
        atomic_json(marker, {"schema_version": 1, "generation": generation})
    return Path(directory) / "generations" / generation

def cache_key(*, prompt: str, provider: str, model: str, normalization_version: str) -> str:
    return _digest({"prompt": prompt, "provider": provider, "model": model,
                    "normalization_version": normalization_version, "cache_schema_version": CACHE_SCHEMA_VERSION})


def load_checkpoint(directory: Path, key: str, *, normalize: Callable[[dict[str, Any]], dict[str, Any]]) -> dict[str, Any] | None:
    path = Path(directory) / f"{key}.json"
    try:
        if path.is_symlink() or directory.is_symlink():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schema_version") != CACHE_SCHEMA_VERSION
                or value.get("key") != key or value.get("article_digest") != _digest(value.get("article"))):
            return None
        return normalize(value["article"])
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        # A single corrupt or obsolete block never invalidates its siblings.
        return None


def save_checkpoint(directory: Path, key: str, article: dict[str, Any], *, chunk_index: int) -> None:
    atomic_json(Path(directory) / f"{key}.json", {
        "schema_version": CACHE_SCHEMA_VERSION, "key": key,
        "chunk_index": chunk_index, "article_digest": _digest(article), "article": article,
    })


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Flush one private JSON record and atomically replace its previous version."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(parent.is_symlink() for parent in [path, *path.parents]):
        raise OSError("Cannot write workbench state through a symbolic link.")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
