"""Completion is an explicit, validated publication rather than a missing error."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OUTPUT_PROFILE = "transcript_article_v1"
REQUIRED_ARTIFACTS = ("metadata.json", "transcript.json", "transcript.txt", "transcript.srt",
                      "transcript_article.json", "transcript.html", "content_bundle.json")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".write-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def validate_delivery(run_dir: Path) -> None:
    for name in REQUIRED_ARTIFACTS:
        path = run_dir / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
            raise ValueError(f"Cannot complete delivery without valid {name}; retry rendering first.")
        if name.endswith(".json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError(f"Invalid delivery {name}.")
    article = json.loads((run_dir / "transcript_article.json").read_text(encoding="utf-8"))
    from jsonschema import ValidationError, validate
    from .article import ARTICLE_SCHEMA
    try:
        validate(article, ARTICLE_SCHEMA)
    except ValidationError as exc:
        raise ValueError("Invalid transcript_article.json; retry article generation first.") from exc
    sections = article.get("sections")
    if not isinstance(sections, list) or not sections or any(
        not isinstance(s, dict) or not isinstance(s.get("paragraphs"), list) or not s["paragraphs"]
        or any(not isinstance(p, dict) or not isinstance(p.get("text"), str) or not p["text"].strip()
               for p in s["paragraphs"]) for s in sections
    ):
        raise ValueError("Invalid transcript_article.json; retry article generation first.")
    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    if bundle.get("output_profile") != OUTPUT_PROFILE or bundle.get("summary", {}).get("chapters"):
        raise ValueError("Invalid article delivery profile or unexpected summary chapters.")


def mark_complete(run_dir: Path, *, update_latest: bool = False) -> None:
    validate_delivery(run_dir)
    hashes = {name: hashlib.sha256((run_dir / name).read_bytes()).hexdigest() for name in REQUIRED_ARTIFACTS}
    completed = datetime.now(timezone.utc).isoformat()
    from .execution import current_operation_identity
    atomic_json(run_dir / "completion.json", {
        "schema_version": 1, "status": "succeeded", "output_profile": OUTPUT_PROFILE,
        "completed_at": completed, "artifacts": hashes, "execution": current_operation_identity(),
    })
    atomic_json(run_dir / "run_state.json", {"status": "succeeded", "output_profile": OUTPUT_PROFILE})
    if update_latest:
        promote_latest(run_dir)


def promote_latest(run_dir: Path) -> None:
    """Advance a success pointer, including a recovered run, but never regress it."""
    pointer = run_dir.parent.parent / "latest.json"
    try:
        previous = json.loads(pointer.read_text(encoding="utf-8"))
        previous_id = str(previous.get("run_id", ""))
        if (previous_id > run_dir.name and Path(previous_id).name == previous_id
                and successful_delivery(run_dir.parent / previous_id)):
            return
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    atomic_json(pointer, {
        "run_id": run_dir.name, "run_dir": f"runs/{run_dir.name}",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_url_sanitized": metadata.get("input_url_sanitized", ""),
    })


def successful_delivery(run_dir: Path, diagnostic: dict | None = None) -> bool:
    """New runs require their marker; legacy runs require real readable output."""
    try:
        state_path = run_dir / "run_state.json"
        if state_path.exists():
            if state_path.is_symlink() or (run_dir / "completion.json").is_symlink():
                return False
            state = json.loads(state_path.read_text(encoding="utf-8"))
            receipt = json.loads((run_dir / "completion.json").read_text(encoding="utf-8"))
            if state.get("status") != "succeeded" or receipt.get("status") != "succeeded":
                return False
            validate_delivery(run_dir)
            hashes = receipt.get("artifacts", {})
            if any(hashes.get(name) != hashlib.sha256((run_dir / name).read_bytes()).hexdigest()
                   for name in REQUIRED_ARTIFACTS):
                return False
            return True
        diagnostic = diagnostic if diagnostic is not None else json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
        return ("error_type" in diagnostic and diagnostic["error_type"] is None
                and diagnostic.get("exit_code", 0) == 0
                and any((run_dir / name).is_file() for name in ("transcript.html", "report.html")))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
