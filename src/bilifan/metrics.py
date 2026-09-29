"""Attempt measurements without prompts, generated text or subprocess output."""
from __future__ import annotations

import contextvars
import copy
import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from . import __version__
from .article_cache import atomic_json, sidecar_directory
from .execution import OperationCanceled, emit_event
from .quality import QUALITY_RULE_VERSION

METRICS_SCHEMA_VERSION = 1
_USAGE_KEYS = ("input_tokens", "output_tokens", "cached_input_tokens")
_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("bilifan_metrics", default=None)


@contextmanager
def attempt_context(operation: str, provider: str, model: str) -> Iterator[None]:
    context: dict[str, Any] = {
        "path": None, "started": time.monotonic(), "active_stages": {}, "finished": False,
        "unknown_usage": {key: False for key in _USAGE_KEYS},
        "record": {
            "schema_version": METRICS_SCHEMA_VERSION, "attempt_id": uuid.uuid4().hex,
            "operation": operation, "provider": provider, "model": model,
            "program_version": __version__, "program_fingerprint": _program_fingerprint(),
            "quality_rule_version": QUALITY_RULE_VERSION,
            "started_at": _now(), "finished_at": None, "status": "running",
            "queue_seconds": None, "processing_seconds": 0.0, "stages": {},
            "model_calls": 0, "model_failures": 0, "input_chars": 0,
            "inflight_calls": {}, "interrupted_calls": 0,
            "cache_hits": 0, "completed_chunks": 0, "total_chunks": 0, "remaining_chunks": 0,
            "usage": {key: None for key in _USAGE_KEYS},
            "known_usage": {key: 0 for key in _USAGE_KEYS},
        },
    }
    token = _context.set(context)
    try:
        yield
    except BaseException as exc:
        finish("canceled" if isinstance(exc, OperationCanceled) else "failed")
        raise
    else:
        if not context["finished"]:
            finish("succeeded")
    finally:
        _context.reset(token)


def bind_run(run_dir: Path) -> None:
    context = _context.get()
    if context is None:
        return
    path = sidecar_directory(run_dir) / "attempts" / f"{context['record']['attempt_id']}.json"
    if context["path"] is not None and context["path"] != path:
        raise ValueError("One attempt cannot change its stable run identity.")
    context["path"] = path
    _persist(context)


def stage_event(stage: str, status: str) -> None:
    context = _context.get()
    if context is None or context["finished"]:
        return
    now = time.monotonic()
    record = context["record"]["stages"].setdefault(stage, {"status": status, "seconds": 0.0, "started_at": _now(), "finished_at": None})
    if status == "running":
        context["active_stages"].setdefault(stage, now)
    elif stage in context["active_stages"]:
        record["seconds"] += max(0.0, now - context["active_stages"].pop(stage))
        record["finished_at"] = _now()
    record["status"] = status
    _persist(context)


def start_model_call(input_chars: int) -> str | None:
    context = _context.get()
    if context is None or context["finished"]:
        return None
    record = context["record"]
    call_id = uuid.uuid4().hex
    record["model_calls"] += 1
    record["input_chars"] += max(0, int(input_chars))
    record["inflight_calls"][call_id] = {"started_at": _now(), "input_chars": max(0, int(input_chars))}
    # Until completion, usage is unknown even if earlier calls reported usage.
    record["usage"] = {key: None for key in _USAGE_KEYS}
    _persist(context)
    return call_id


def complete_model_call(call_id: str | None, success: bool, usage: dict[str, Any] | None = None) -> None:
    context = _context.get()
    if context is None or context["finished"] or call_id not in context["record"]["inflight_calls"]:
        return
    record = context["record"]
    record["inflight_calls"].pop(call_id)
    record["model_failures"] += int(not success)
    usage = sanitize_usage(usage)
    for key in _USAGE_KEYS:
        value = usage.get(key)
        if value is None:
            context["unknown_usage"][key] = True
        else:
            record["known_usage"][key] += value
        record["usage"][key] = None if context["unknown_usage"][key] or record["inflight_calls"] else record["known_usage"][key]
    _persist(context)


def model_call(success: bool, input_chars: int, usage: dict[str, Any] | None = None) -> None:
    """Compatibility helper for synchronous callers; managed calls use start/end."""
    complete_model_call(start_model_call(input_chars), success, usage)


def cache_event(hit: bool, completed: int, total: int) -> None:
    context = _context.get()
    if context is None or context["finished"]:
        return
    record = context["record"]
    record["cache_hits"] += int(hit)
    record["completed_chunks"] = max(0, int(completed))
    record["total_chunks"] = max(record["completed_chunks"], int(total))
    record["remaining_chunks"] = record["total_chunks"] - record["completed_chunks"]
    _persist(context)


def finish(status: str) -> None:
    context = _context.get()
    if context is None or context["finished"]:
        return
    now = time.monotonic()
    record = context["record"]
    for stage, start in context["active_stages"].items():
        item = record["stages"][stage]
        item["seconds"] += max(0.0, now - start)
        item["status"] = status
        item["finished_at"] = _now()
    context["active_stages"].clear()
    _close_inflight(record)
    record["status"] = status
    record["finished_at"] = _now()
    record["processing_seconds"] = max(0.0, now - context["started"])
    context["finished"] = True
    _persist(context)



def finalize_abandoned(run_dir: Path, status: str, attempt_id: str | None = None) -> dict[str, Any] | None:
    """Call only after the executor confirms computation has stopped.

    Prefer the attempt ID observed in the job's metrics event. Without an ID,
    multiple running attempts are ambiguous and none is modified.
    """
    if status not in {"canceled", "interrupted", "failed"}:
        raise ValueError("Abandoned attempt requires a confirmed termination status.")
    base = sidecar_directory(run_dir) / "attempts"
    if attempt_id is not None:
        if not isinstance(attempt_id, str) or len(attempt_id) != 32 or any(c not in "0123456789abcdef" for c in attempt_id):
            return None
        paths = [base / f"{attempt_id}.json"]
    else:
        paths = list(base.glob("*.json"))
    candidates = []
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (isinstance(record, dict) and record.get("schema_version") == METRICS_SCHEMA_VERSION
                and record.get("status") == "running" and path.stem == record.get("attempt_id")):
            candidates.append((path, record))
    if len(candidates) != 1:
        return None
    path, record = candidates[0]
    finish_time = _now()
    record.update(status=status, finished_at=finish_time,
                  processing_seconds=_wall_elapsed(record.get("started_at"), finish_time))
    _close_inflight(record)
    for item in record.get("stages", {}).values():
        if isinstance(item, dict) and item.get("status") == "running":
            item.update(status=status, finished_at=finish_time,
                        seconds=_wall_elapsed(item.get("started_at"), finish_time))
    atomic_json(path, record)
    return record


def _close_inflight(record: dict[str, Any]) -> None:
    count = len(record.get("inflight_calls") or {})
    if count:
        record["model_failures"] += count
        record["interrupted_calls"] = record.get("interrupted_calls", 0) + count
        record["inflight_calls"] = {}
        record["usage"] = {key: None for key in _USAGE_KEYS}


def _wall_elapsed(start: str | None, finish: str) -> float:
    try:
        return max(0.0, (datetime.fromisoformat(finish) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return 0.0

def sanitize_usage(usage: Any) -> dict[str, int | None]:
    if not isinstance(usage, dict):
        return {}
    return {key: value for key in _USAGE_KEYS if type(value := usage.get(key)) is int and value >= 0}


def usage_from_codex_events(stdout: str) -> dict[str, int | None] | None:
    """Read only usage counters from completed turn events; never retain events."""
    total = {key: 0 for key in _USAGE_KEYS}
    missing: set[str] = set()
    found = False
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict) or event.get("type") != "turn.completed":
            continue
        found = True
        usage = sanitize_usage(event.get("usage"))
        for key in _USAGE_KEYS:
            if key not in usage:
                missing.add(key)
            else:
                total[key] += usage[key]
    return {key: None if key in missing else total[key] for key in _USAGE_KEYS} if found else None


def snapshot() -> dict[str, Any] | None:
    context = _context.get()
    return copy.deepcopy(context["record"]) if context is not None else None


def _persist(context: dict[str, Any]) -> None:
    if not context["finished"]:
        context["record"]["processing_seconds"] = max(0.0, time.monotonic() - context["started"])
    if context["path"] is not None:
        atomic_json(context["path"], context["record"])
    emit_event({"type": "metrics", "metrics": copy.deepcopy(context["record"])})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@lru_cache(maxsize=1)
def _program_fingerprint() -> str:
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]
