"""Fresh-interpreter worker for pipeline/retry and optional GPU transcription."""
from __future__ import annotations

import dataclasses
import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from .execution import (
    ExecutionUncertain, OperationCanceled, _Context, _context, _read_json, _result_payload,
    atomic_json, check_cancelled, record_completion,
)


def initialize_worker(state: Path, nonce: str) -> _Context:
    request = _read_json(state / "request.json")
    if request.get("nonce") != nonce:
        raise ValueError("Worker nonce mismatch")
    context = _Context(Path(request["outputs_root"]).resolve(), state, nonce, int(os.environ["BILIFAN_EXECUTION_LOCK_FD"]), request.get("job_id"), 1)
    _context.set(context)
    control_fd = int(os.environ["BILIFAN_EXECUTION_CONTROL_FD"])
    def parent_watch() -> None:
        try:
            while os.read(control_fd, 32):
                pass
        finally:
            (state / "cancel").touch()
            # check_cancelled stops managed commands. A blocked Python/model
            # call also receives TERM after a small cooperative window.
            time.sleep(0.2)
            if not (state / "publication-complete.json").exists():
                from .execution_supervisor import _publishing
                if not _publishing(state):
                    try:
                        os.killpg(os.getpgrp(), signal.SIGTERM)
                    except ProcessLookupError:
                        pass
    threading.Thread(target=parent_watch, name="bilifan-parent-watch", daemon=True).start()
    def on_term(_signum: int, _frame: Any) -> None:
        (state / "cancel").touch()
        from .execution_supervisor import _publishing
        if not _publishing(state):
            check_cancelled()
    signal.signal(signal.SIGTERM, on_term)
    signal.signal(signal.SIGINT, on_term)
    return context


def _progress(stage: str, status: str, message: str) -> None:
    check_cancelled()
    try:
        os.write(1, (json.dumps({"type": "progress", "stage": stage, "status": status, "message": message}, ensure_ascii=False) + "\n").encode())
    except BrokenPipeError:
        context = _context.get()
        if context:
            (context.state / "cancel").touch()
        check_cancelled()


def run_operation(operation: dict[str, Any], root: Path) -> Any:
    kind = operation.get("kind", "pipeline")
    if kind == "pipeline":
        from .pipeline import PipelineRequest, run_summarize_pipeline
        request = dict(operation.get("request") or operation.get("params") or {})
        request["out"] = root
        if request.get("cookies_file"):
            request["cookies_file"] = Path(request["cookies_file"])
        names = {field.name for field in dataclasses.fields(PipelineRequest)}
        request = {key: value for key, value in request.items() if key in names and key != "confirm_long_video"}
        return run_summarize_pipeline(PipelineRequest(**request), progress_callback=_progress)
    if kind == "retry":
        from .retry import retry_run
        run_key = operation.get("run_key")
        if not isinstance(run_key, str) or not run_key:
            raise ValueError("Retry operation requires run_key")
        directory = (root / run_key).resolve()
        if not directory.is_relative_to(root) or directory == root or ".." in Path(run_key).parts or Path(run_key).is_absolute():
            raise ValueError("Retry run directory is outside outputs")
        from .execution import emit_event
        emit_event({"type": "run_created", "run_key": run_key})
        options = dict(operation.get("options") or operation.get("params") or {})
        _progress(str(options.get("from_stage", "summarization")), "running", "正在恢复处理。")
        return retry_run(directory, **options)
    raise ValueError(f"Unsupported operation: {kind}")


def main_worker(state: Path, nonce: str) -> int:
    context = initialize_worker(state, nonce)
    request = _read_json(state / "request.json")
    try:
        check_cancelled()
        result = run_operation(request["operation"], context.root)
        # Root publication writes this inside its guard; this is an idempotent
        # fallback for compatible runners which have not yet adopted the hook.
        record_completion(result)
        atomic_json(state / "result.json", {"nonce": nonce, "status": "completed", "result": _result_payload(result)})
        return 0
    except OperationCanceled:
        atomic_json(state / "result.json", {"nonce": nonce, "status": "canceled"})
        return 2
    except BaseException as exc:
        from .diagnostics import redact_text
        operation = request.get("operation", {})
        error = {"message": redact_text(str(exc)), "run_key": getattr(exc, "run_key", "") or operation.get("run_key", ""), "diagnostics_path": str(getattr(exc, "diagnostics_path", "") or ""), "artifact_paths": getattr(exc, "artifact_paths", []), "warnings": getattr(exc, "warnings", []), "exit_code": getattr(exc, "exit_code", 1)}
        # RetryError may carry only this attempt's diagnostic path. Do not infer
        # context from an old successful run's diagnostics or a previous retry.
        diagnostic_path = getattr(exc, "diagnostics_path", None)
        if operation.get("kind") == "retry" and diagnostic_path is not None:
            try:
                path = Path(diagnostic_path)
                if path.is_file() and path.resolve().is_relative_to(context.root):
                    diagnostic = _read_json(path)
                    for field in ("artifact_paths", "warnings"):
                        values = diagnostic.get(field)
                        if isinstance(values, list):
                            error[field] = [value for value in values if isinstance(value, str)]
            except (OSError, ValueError):
                pass
        status = "uncertain" if isinstance(exc, ExecutionUncertain) or context.uncertain else "failed"
        atomic_json(state / "result.json", {"nonce": nonce, "status": status, "error": error})
        return 1


def main_whisper(request_path: Path, result_path: Path) -> int:
    request = _read_json(request_path)
    try:
        if request["backend"] == "mlx":
            import mlx_whisper
            from .transcript import _mlx_whisper_model_path
            result = mlx_whisper.transcribe(request["audio_path"], path_or_hf_repo=_mlx_whisper_model_path(request["model_name"]), language=request["language"], verbose=False)
        else:
            import whisper
            model = whisper.load_model(request["model_name"])
            result = model.transcribe(request["audio_path"], language=request["language"])
        segments = result.get("segments") if isinstance(result, dict) else None
        if not isinstance(segments, list):
            raise ValueError("Whisper returned invalid transcript segments.")
        atomic_json(result_path, {"segments": segments})
        return 0
    except BaseException as exc:
        from .diagnostics import redact_text
        atomic_json(result_path, {"error": redact_text(str(exc))})
        return 1


if __name__ == "__main__":
    if sys.argv[1] == "--whisper":
        raise SystemExit(main_whisper(Path(sys.argv[2]), Path(sys.argv[3])))
    raise SystemExit(main_worker(Path(sys.argv[1]), sys.argv[2]))
