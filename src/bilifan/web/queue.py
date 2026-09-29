from __future__ import annotations

import inspect
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from typing import Any
from uuid import uuid4

from bilifan.diagnostics import redact_text
from bilifan.pipeline import PipelineRequest, PipelineRunError

from .jobs import STAGES, JobCanceled, _artifact_links, _now_iso, explain_failure, retry_actions_for
from .queue_storage import QueueStorageError, QueueStore, read_completion_receipt, write_completion_receipt, read_run_link
from .run_info import read_transcript_source_label

QUEUE_SCHEMA_VERSION = 2
OUTPUT_PROFILE = "transcript_article_v1"
RECENT_COMPLETED_LIMIT = 3
TERMINAL_QUEUE_STATUSES = {"succeeded", "failed", "canceled"}
ALL_STATUSES = TERMINAL_QUEUE_STATUSES | {"queued", "running", "canceling", "interrupted"}


@dataclass
class QueueJob:
    job_id: str
    status: str = "idle"
    request: dict[str, Any] = field(default_factory=dict)
    kind: str = "pipeline"
    options: dict[str, Any] = field(default_factory=dict)
    retry_of: str | None = None
    output_profile: str = OUTPUT_PROFILE
    origin: dict[str, Any] = field(default_factory=dict)
    title: str | None = None
    transcript_source_label: str | None = None
    stage: str = "preflight"
    interrupted_stage: str | None = None
    message: str = ""
    progress: list[dict[str, str]] = field(default_factory=list)
    run_key: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    friendly_error: dict[str, str] | None = None
    retry_actions: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=lambda: {"status": "unknown", "review_required": False, "reasons": []})
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    stage_started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["job_started_at"] = self.started_at
        data["elapsed_seconds"] = _elapsed(self.started_at, self.finished_at)
        data["stage_elapsed_seconds"] = _elapsed(self.stage_started_at, self.finished_at)
        data["queue_seconds"] = _elapsed(self.created_at, self.started_at or self.finished_at)
        if not self.origin:
            data.pop("origin", None)
        if self.friendly_error is None:
            data.pop("friendly_error", None)
        return data


class BatchQueueManager:
    """One ledger for every Web/intake/retry entry point, with one active operation."""

    def __init__(self, *, storage_path: Path, runner=None, retry_runner=None,
                 run_jobs_inline: bool = False, paused: bool = False, auto_start: bool = True) -> None:
        self._runner = runner
        self._retry_runner = retry_runner
        self._storage_path = Path(storage_path)
        self._outputs_root = self._storage_path.parent.parent
        self._run_jobs_inline = run_jobs_inline
        self._lock = Lock()
        self._paused = paused
        self._worker_running = False
        self._thread: Thread | None = None
        self._jobs: list[QueueJob] = []
        self._intake_batches: dict[str, dict[str, Any]] = {}
        self._cancel_events: dict[str, Event] = {}
        self._wake = Event()
        self._busy_until = 0.0
        self._busy_attempts = 0
        self._storage_error: str | None = None
        self._execution_error: str | None = None
        self._closed = False
        self._store: QueueStore | None = None
        try:
            self._store = QueueStore(self._storage_path)
            self._load()
        except (QueueStorageError, ValueError, TypeError, OSError) as exc:
            self._halt_storage(QueueStorageError(f"任务账本无法安全加载：{redact_text(str(exc))}"))
        if auto_start:
            self.start()

    def start(self) -> None:
        with self._lock:
            should_start = self._should_start_worker_locked()
        if should_start:
            self._start_worker()

    def close(self, timeout: float = 10.0) -> bool:
        """Stop accepting work; release writer ownership only after the worker exits."""
        with self._lock:
            self._closed = True
            self._wake.set()
            for event in self._cancel_events.values():
                event.set()
            thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout)
        with self._lock:
            if self._worker_running:
                return False
            if self._store is not None:
                self._store.close()
            return True

    def submit(self, requests: list[PipelineRequest], *, titles: list[str | None] | None = None,
               origins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if origins is not None and len(origins) != len(requests):
            raise ValueError("requests and origins must have the same length")
        with self._lock:
            checkpoint = self._checkpoint_locked()
            ids = []
            for index, request in enumerate(requests):
                job = QueueJob(job_id=uuid4().hex, status="queued", request=_request_to_payload(request),
                               title=_display_title(titles[index] if titles and index < len(titles) else None),
                               origin=deepcopy(origins[index]) if origins else {}, progress=_initial_progress())
                self._jobs.append(job)
                ids.append(job.job_id)
            self._commit_locked(checkpoint)
        self.start()
        state = self.state()
        state["submitted_job_ids"] = ids
        return state

    def submit_one(self, request: PipelineRequest, *, title: str | None = None,
                   origin: dict[str, Any] | None = None) -> QueueJob:
        state = self.submit([request], titles=[title], origins=[origin or {}])
        return self.get(state["submitted_job_ids"][0])

    def submit_retry(self, run_key: str, options: dict[str, Any], *, title: str | None = None,
                     retry_of: str | None = None, origin: dict[str, Any] | None = None) -> QueueJob:
        run_dir = self._safe_run_dir(run_key)
        with self._lock:
            checkpoint = self._checkpoint_locked()
            job = QueueJob(job_id=uuid4().hex, status="queued", kind="retry", run_key=run_key,
                           request={"out": str(self._outputs_root)}, options=deepcopy(options),
                           title=_display_title(title) or _read_metadata_title(run_dir), retry_of=retry_of,
                           origin=deepcopy(origin or {}), progress=_initial_progress(),
                           stage=str(options.get("from_stage") or "summarization"))
            self._jobs.append(job)
            self._commit_locked(checkpoint)
        self.start()
        return self.get(job.job_id)

    def get(self, job_id: str) -> QueueJob | None:
        with self._lock:
            return deepcopy(self._find_locked(job_id))

    def current(self) -> QueueJob:
        with self._lock:
            active = next((job for job in self._jobs if job.status in {"running", "canceling"}), None)
            return deepcopy(active or (self._jobs[-1] if self._jobs else QueueJob(job_id="")))

    def submit_intake_batch(self, *, batch_id: str, requests: list[PipelineRequest],
                            origins: list[dict[str, Any]], rejected: list[dict[str, Any]] | None = None,
                            duplicates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if len(requests) != len(origins):
            raise ValueError("requests and origins must have the same length")
        with self._lock:
            self._ensure_writable_locked()
            checkpoint = self._checkpoint_locked()
            existing = self._intake_batches.get(batch_id)
            recovered = self._intake_batch_from_jobs_locked(batch_id) if existing is None else None
            if existing is not None or recovered is not None:
                response = deepcopy(existing if existing is not None else recovered)
                if recovered is not None:
                    self._intake_batches[batch_id] = deepcopy(recovered)
                    self._commit_locked(checkpoint)
                response["idempotent"] = True
            else:
                accepted = []
                for index, (request, origin) in enumerate(zip(requests, origins, strict=True), start=1):
                    job = QueueJob(job_id=uuid4().hex, status="queued", request=_request_to_payload(request),
                                   origin=_intake_origin_payload(origin, batch_id=batch_id, index=index),
                                   progress=_initial_progress())
                    self._jobs.append(job)
                    accepted.append(_accepted_job_payload(job))
                response = {"ok": True, "batch_id": batch_id, "idempotent": False,
                            "accepted": accepted, "rejected": deepcopy(rejected or []),
                            "duplicates": deepcopy(duplicates or [])}
                self._intake_batches[batch_id] = deepcopy(response)
                self._commit_locked(checkpoint)
        self.start()
        return response

    def _intake_batch_from_jobs_locked(self, batch_id: str) -> dict[str, Any] | None:
        # A retry repeats the origin but must never add an accepted item to the original acknowledgement.
        accepted = [_accepted_job_payload(job) for job in self._jobs
                    if job.origin.get("external_batch_id") == batch_id and not job.retry_of]
        if not accepted:
            return None
        return {"ok": True, "batch_id": batch_id, "idempotent": False,
                "accepted": accepted, "rejected": [], "duplicates": []}

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state_locked()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            checkpoint = self._checkpoint_locked()
            self._paused = True
            self._commit_locked(checkpoint)
            self._wake.set()
            return self._state_locked()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            checkpoint = self._checkpoint_locked()
            self._paused = False
            self._execution_error = None
            self._commit_locked(checkpoint)
            self._wake.set()
        self.start()
        return self.state()

    def cancel_pending(self, job_id: str) -> dict[str, Any]:
        # Kept as a compatibility address; cancellation now covers running work too.
        return self.cancel(job_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._find_locked(job_id)
            if job is not None and job.status in {"queued", "running"}:
                checkpoint = self._checkpoint_locked()
                job.cancel_requested = True
                if job.status == "queued":
                    job.status, job.stage = "canceled", "canceled"
                    job.message, job.finished_at = "等待中的任务已取消。", _now_iso()
                else:
                    job.status = "canceling"
                    job.message = "正在取消；实际计算退出后再开始下一项。"
                    _set_progress(job.progress, job.stage, "canceling")
                self._commit_locked(checkpoint)
                event = self._cancel_events.get(job_id)
                if event is not None:
                    event.set()
            return self._state_locked()

    def cancel_current(self) -> QueueJob | None:
        with self._lock:
            job = next((job for job in self._jobs if job.status == "running"), None)
            job_id = job.job_id if job else None
        if job_id is None:
            return None
        self.cancel(job_id)
        return self.get(job_id)

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            original = self._find_locked(job_id)
            if original is None or original.status not in {"failed", "canceled", "interrupted"}:
                return self._state_locked()
            checkpoint = self._checkpoint_locked()
            job = QueueJob(job_id=uuid4().hex, status="queued", request=deepcopy(original.request),
                           kind=original.kind, options=deepcopy(original.options), retry_of=original.job_id,
                           origin=deepcopy(original.origin), title=original.title, progress=_initial_progress())
            # A normal recovery resumes the active generation, including completed
            # blocks from a previous explicitly forced regeneration.
            if "force_article" in job.options:
                job.options["force_article"] = False
            if "force_article" in job.request:
                job.request["force_article"] = False
            # Once raw transcription is durable, recovery reuses it and the stable chunk cache.
            if original.run_key:
                run_dir = self._safe_run_dir(original.run_key)
                if original.kind == "retry" or (run_dir / "transcript.json").is_file():
                    job.kind, job.run_key = "retry", original.run_key
                    if original.kind != "retry":
                        job.options = {key: value for key, value in original.request.items()
                                       if key in {"output_format", "llm_provider", "llm_model", "require_pdf", "allow_long_video"}}
                        job.options["from_stage"] = "summarization"
            self._jobs.append(job)
            self._commit_locked(checkpoint)
        self.start()
        result = self.state()
        result["submitted_job_ids"] = [job.job_id]
        return result

    def clear_completed(self) -> dict[str, Any]:
        with self._lock:
            checkpoint = self._checkpoint_locked()
            self._jobs = [job for job in self._jobs if job.status not in TERMINAL_QUEUE_STATUSES]
            self._commit_locked(checkpoint)
            return self._state_locked()

    def _start_worker(self) -> None:
        if self._run_jobs_inline:
            self._run_loop()
        else:
            # Multiple callers may reach here together; _run_loop claims under the lock.
            thread = Thread(target=self._run_loop, daemon=True, name="bilifan-task-queue")
            thread.start()

    def _run_loop(self) -> None:
        with self._lock:
            if self._worker_running or self._closed or self._storage_error:
                return
            self._worker_running = True
            self._thread = current_thread() if not self._run_jobs_inline else None
        try:
            while True:
                with self._lock:
                    if self._paused or self._closed or self._storage_error:
                        return
                    job = self._next_queued_locked()
                    if job is None:
                        return
                    backoff = max(0.0, self._busy_until - monotonic())
                    if not backoff:
                        job.status = "running"
                        job.stage = str(job.options.get("from_stage") or "preflight")
                        job.started_at = job.stage_started_at = _now_iso()
                        job.message = "任务已开始。"
                        self._cancel_events[job.job_id] = Event()
                        self._persist_locked()
                if backoff:
                    # An external CLI operation owns execution, but no human
                    # intervention is needed. Keep FIFO and check at most every
                    # five seconds; pause/shutdown can interrupt this wait.
                    self._wake.wait(backoff)
                    self._wake.clear()
                    continue
                self._run_job(job.job_id)
        except QueueStorageError:
            # _persist_locked records a visible halt. Never continue after a failed write.
            pass
        finally:
            with self._lock:
                self._worker_running = False
                if self._closed and self._store is not None:
                    self._store.close()
                should_start = self._should_start_worker_locked()
            if should_start:
                self._start_worker()

    def _run_job(self, job_id: str) -> None:
        def progress_callback(stage: str, status: str, message: str) -> None:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None or job.status not in {"running", "canceling"}:
                    return
                if job.stage != stage:
                    job.stage_started_at = _now_iso()
                job.stage = stage
                if job.status != "canceling":
                    job.message = redact_text(message)
                    _set_progress(job.progress, stage, status)
                self._persist_locked()
                if self._runner is not None and self._cancel_events[job_id].is_set():
                    raise JobCanceled()

        def event_callback(event: dict[str, Any]) -> None:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None:
                    return
                if event.get("type") in {"run_created", "run_key"} and event.get("run_key"):
                    self._safe_run_dir(str(event["run_key"]))
                    job.run_key = str(event["run_key"])
                if event.get("type") == "metrics" and isinstance(event.get("metrics"), dict):
                    job.metrics.update(deepcopy(event["metrics"]))
                self._persist_locked()

        with self._lock:
            job = deepcopy(self._find_locked(job_id))
            event = self._cancel_events[job_id]
        try:
            if self._runner is None and self._retry_runner is None:
                from bilifan.execution import execute_operation
                result = execute_operation({"kind": job.kind, "request": job.request,
                                            "run_key": job.run_key, "options": job.options},
                                           outputs_root=self._outputs_root, progress_callback=progress_callback,
                                           event_callback=event_callback, cancel_event=event, job_id=job_id)
            else:
                runner = self._runner if job.kind == "pipeline" else self._retry_runner
                if runner is None:
                    raise RuntimeError("Retry runner is not configured.")
                kwargs = {"progress_callback": progress_callback, "event_callback": event_callback,
                          "cancel_event": event}
                if job.kind == "retry":
                    kwargs.update(job.options)
                    result = _invoke_runner(runner, self._safe_run_dir(job.run_key), **kwargs)
                else:
                    result = _invoke_runner(runner, _payload_to_request(job.request), **kwargs)
                # Tests/in-process integrations have the same durable acknowledgement protocol.
                if result is not None:
                    try:
                        write_completion_receipt(self._outputs_root, job_id, result)
                    except (OSError, ValueError) as exc:
                        raise QueueStorageError("成果已生成，但完成凭证保存失败；已暂停调度，请核对后恢复。") from exc
            if result is None or not getattr(result, "run_key", None):
                raise RuntimeError("Pipeline runner returned no result.")
        except Exception as exc:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None:
                    return
                self._cancel_events.pop(job_id, None)
                if isinstance(exc, QueueStorageError):
                    self._halt_storage(exc)
                    return
                category = type(exc).__name__
                if category == "ExecutionBusy" and job.cancel_requested:
                    # No computation was launched, so a concurrent cancel can
                    # finish immediately instead of being requeued accidentally.
                    job.status, job.stage = "canceled", "canceled"
                    job.finished_at = _now_iso()
                    job.message = "等待执行资源时已取消，没有启动计算。"
                    self._persist_locked()
                    return
                if category == "ExecutionBusy":
                    self._busy_attempts += 1
                    self._busy_until = monotonic() + min(5.0, 0.5 * (2 ** min(self._busy_attempts - 1, 4)))
                    self._execution_error = None
                    job.status, job.stage = "queued", "preflight"
                    job.message = "正在等待其他本地任务释放执行资源，会自动继续。"
                    job.started_at = job.stage_started_at = None
                    self._persist_locked()
                    return
                if category == "ExecutionUncertain":
                    self._paused = True
                    self._execution_error = redact_text(str(exc))
                    job.interrupted_stage = job.stage
                    job.status, job.stage = "interrupted", "interrupted"
                    job.message = self._execution_error
                    if not job.run_key:
                        try:
                            linked = read_run_link(self._outputs_root, job.job_id)
                        except QueueStorageError as binding_error:
                            self._halt_storage(binding_error)
                            return
                        if linked is not None:
                            job.run_key = linked["run_key"]
                    if job.run_key:
                        raw_paths, _ = _retry_failure_artifacts(self._safe_run_dir(job.run_key), None)
                        job.artifacts.update(_artifact_links(job.run_key, raw_paths))
                        job.retry_actions = ["summarization"] if (self._safe_run_dir(job.run_key) / "transcript.json").is_file() else ["pipeline"]
                        self._refresh_run_metadata(job)
                    # This means identity/termination is uncertain, not that
                    # computation exited. Its metrics must remain unfinalized.
                    self._persist_locked()
                    return
                if isinstance(exc, JobCanceled) or category == "OperationCanceled":
                    _set_progress(job.progress, job.stage, "canceled")
                    job.status, job.stage = "canceled", "canceled"
                    job.message = "任务已取消，实际计算已停止；已完成内容保留。"
                    job.cancel_requested = True
                    if not job.run_key:
                        try:
                            linked = read_run_link(self._outputs_root, job.job_id)
                        except QueueStorageError as binding_error:
                            self._halt_storage(binding_error)
                            return
                        if linked is not None:
                            job.run_key = linked["run_key"]
                    if job.run_key:
                        run_dir = self._safe_run_dir(job.run_key)
                        raw_paths, _ = _retry_failure_artifacts(run_dir, None)
                        job.artifacts.update(_artifact_links(job.run_key, raw_paths))
                        job.retry_actions = ["summarization"] if (run_dir / "transcript.json").is_file() else ["pipeline"]
                    self._finalize_canceled_metrics(job)
                else:
                    job.status = "failed"
                    job.message = redact_text(str(exc))
                    if isinstance(exc, PipelineRunError):
                        if exc.run_key:
                            job.run_key = exc.run_key
                            job.artifacts = _artifact_links(exc.run_key, exc.artifact_paths)
                        job.warnings = list(exc.warnings)
                        job.retry_actions = retry_actions_for(job.stage, exc.artifact_paths)
                    elif job.kind == "retry" and job.run_key:
                        paths, warnings = _retry_failure_artifacts(
                            self._safe_run_dir(job.run_key), getattr(exc, "diagnostics_path", None)
                        )
                        job.artifacts = _artifact_links(job.run_key, paths)
                        job.warnings = warnings
                        job.retry_actions = retry_actions_for(job.stage, paths)
                    job.friendly_error = explain_failure(stage=job.stage, message=job.message, warnings=job.warnings)
                    _set_progress(job.progress, job.stage, "failed")
                job.finished_at = _now_iso()
                self._refresh_run_metadata(job)
                self._persist_locked()
            return
        with self._lock:
            job = self._find_locked(job_id)
            self._cancel_events.pop(job_id, None)
            if job is None:
                return
            self._mark_succeeded(job, result.run_key, result.artifact_paths, result.warnings)
            self._persist_locked()

    def _finalize_canceled_metrics(self, job: QueueJob) -> None:
        if not job.run_key:
            return
        from bilifan.metrics import finalize_abandoned
        try:
            updated = finalize_abandoned(self._safe_run_dir(job.run_key), "canceled", job.metrics.get("attempt_id"))
        except (OSError, ValueError) as exc:
            error = QueueStorageError("计算已停止，但指标收尾保存失败，已暂停后续调度。")
            self._halt_storage(error)
            raise error from exc
        if updated is not None:
            job.metrics.update(updated)

    def _mark_succeeded(self, job: QueueJob, run_key: str, artifact_paths: list[str], warnings: list[str]) -> None:
        self._busy_until = 0.0
        self._busy_attempts = 0
        self._execution_error = None
        job.status, job.stage = "succeeded", "render"
        job.message = "整理逐字稿已生成。" if not job.cancel_requested else "成果已发布；取消请求到达过晚。"
        job.run_key = run_key
        job.artifacts = _artifact_links(run_key, artifact_paths)
        job.warnings = list(dict.fromkeys(job.warnings + list(warnings)))
        job.friendly_error = None
        job.finished_at = _now_iso()
        for item in job.progress:
            item["status"] = "done"
        self._refresh_run_metadata(job)

    def _refresh_run_metadata(self, job: QueueJob) -> None:
        if job.run_key:
            run_dir = self._safe_run_dir(job.run_key)
            job.title = _read_metadata_title(run_dir) or job.title
            job.transcript_source_label = read_transcript_source_label(run_dir) or job.transcript_source_label
            job.quality = _read_quality(run_dir)

    def _state_locked(self) -> dict[str, Any]:
        counts = {status: 0 for status in ["queued", "running", "canceling", "interrupted", "succeeded", "failed", "canceled"]}
        for job in self._jobs:
            if job.status in counts:
                counts[job.status] += 1
        replaced_attempt_ids = self._replaced_attempt_ids_locked()
        recent_ids = {job.job_id for job in [job for job in self._jobs if job.status == "succeeded"][-RECENT_COMPLETED_LIMIT:]}
        visible = [job for job in self._jobs if job.job_id not in replaced_attempt_ids
                   and (job.status != "succeeded" or job.job_id in recent_ids)]
        visible_counts = {status: 0 for status in counts}
        for job in visible:
            visible_counts[job.status] += 1
        return {"schema_version": QUEUE_SCHEMA_VERSION, "paused": self._paused,
                "storage_error": self._storage_error, "execution_error": self._execution_error,
                "waiting_for_execution": self._busy_until > monotonic(),
                "counts": counts, "visible_counts": visible_counts, "total_items": len(self._jobs),
                "hidden_completed": max(0, counts["succeeded"] - RECENT_COMPLETED_LIMIT),
                "hidden_replaced": len(replaced_attempt_ids), "items": [job.as_dict() for job in visible]}

    def _replaced_attempt_ids_locked(self) -> set[str]:
        last_succeeded = {}
        succeeded_retry_of = set()
        for index, job in enumerate(self._jobs):
            if job.status == "succeeded":
                key = _queue_request_key(job)
                if key:
                    last_succeeded[key] = index
                if job.retry_of:
                    succeeded_retry_of.add(job.retry_of)
        return {job.job_id for index, job in enumerate(self._jobs)
                if job.status in {"failed", "canceled", "interrupted"}
                and (job.job_id in succeeded_retry_of or (_queue_request_key(job)
                     and last_succeeded.get(_queue_request_key(job), -1) > index))}

    def _find_locked(self, job_id: str) -> QueueJob | None:
        return next((job for job in self._jobs if job.job_id == job_id), None)

    def _next_queued_locked(self) -> QueueJob | None:
        return next((job for job in self._jobs if job.status == "queued"), None)

    def _should_start_worker_locked(self) -> bool:
        return (not self._paused and not self._worker_running and not self._closed
                and not self._storage_error and any(job.status == "queued" for job in self._jobs))

    def _load(self) -> None:
        data = self._store.load()
        if data is None:
            return
        self._paused = data.get("paused", self._paused)
        self._intake_batches = deepcopy(data.get("intake_batches", {}))
        jobs, ids = [], set()
        known = {item.name for item in fields(QueueJob)}
        for raw in data["jobs"]:
            if (not isinstance(raw, dict) or not isinstance(raw.get("job_id"), str)
                    or not raw["job_id"] or raw["job_id"] in ids or raw.get("status") not in ALL_STATUSES
                    or not isinstance(raw.get("request"), dict)):
                raise QueueStorageError("任务记录格式无效，已暂停调度，未丢弃任何历史记录。")
            ids.add(raw["job_id"])
            for name, expected in {"origin": dict, "options": dict, "metrics": dict, "quality": dict, "artifacts": dict,
                                   "warnings": list, "progress": list}.items():
                if name in raw and not isinstance(raw[name], expected):
                    raise QueueStorageError("任务记录字段无效，已暂停调度。")
            job = QueueJob(**{key: deepcopy(value) for key, value in raw.items() if key in known})
            if job.kind not in {"pipeline", "retry"}:
                raise QueueStorageError("任务操作类型未知，已暂停调度。")
            if data.get("schema_version", 1) == 1 and job.status == "queued":
                job.output_profile = OUTPUT_PROFILE
                job.warnings.append("升级后按逐字稿规则执行：保留原请求参数，不再生成解读主报告。")
            elif data.get("schema_version", 1) == 1 and "output_profile" not in raw:
                job.output_profile = "legacy_report"
            if job.status in {"running", "canceling", "interrupted"} and not job.run_key:
                linked = read_run_link(self._outputs_root, job.job_id)
                if linked is not None:
                    job.run_key = linked["run_key"]
            try:
                self._refresh_run_metadata(job)
            except ValueError as exc:
                raise QueueStorageError("任务结果路径无效，已暂停调度。") from exc
            if job.status in {"running", "canceling"}:
                receipt = read_completion_receipt(self._outputs_root, job.job_id, run_key=job.run_key)
                if receipt is not None:
                    from bilifan.delivery import promote_latest, successful_delivery
                    if receipt.get("recovered_from") == "completion_marker" or successful_delivery(self._safe_run_dir(receipt["run_key"])):
                        try:
                            promote_latest(self._safe_run_dir(receipt["run_key"]))
                        except (OSError, ValueError) as exc:
                            raise QueueStorageError("成果已恢复，但最新成功指针无法保存，已暂停调度。") from exc
                    self._mark_succeeded(job, receipt["run_key"], receipt["artifact_paths"], receipt.get("warnings", []))
                    job.message = "已从完成凭证恢复成功状态，没有重复执行。"
                else:
                    job.interrupted_stage = job.stage
                    job.status, job.stage = "interrupted", "interrupted"
                    job.message = "Service restarted：任务中断，已完成内容保留，请选择恢复。"
                    job.finished_at = _now_iso()
                    job.retry_actions = ["summarization"] if job.run_key and (self._safe_run_dir(job.run_key) / "transcript.json").exists() else ["pipeline"]
                    if job.run_key:
                        raw_paths, _ = _retry_failure_artifacts(self._safe_run_dir(job.run_key), None)
                        job.artifacts.update(_artifact_links(job.run_key, raw_paths))
            if job.status == "interrupted" and job.run_key:
                raw_paths, _ = _retry_failure_artifacts(self._safe_run_dir(job.run_key), None)
                job.artifacts.update(_artifact_links(job.run_key, raw_paths))
                job.retry_actions = ["summarization"] if (self._safe_run_dir(job.run_key) / "transcript.json").is_file() else ["pipeline"]
            jobs.append(job)
        self._jobs = jobs
        self._persist_locked()

    def _safe_run_dir(self, run_key: str) -> Path:
        if not isinstance(run_key, str) or not run_key or Path(run_key).is_absolute() or ".." in Path(run_key).parts:
            raise ValueError("Invalid run key")
        root = self._outputs_root.resolve()
        resolved = (root / run_key).resolve()
        if not resolved.is_relative_to(root) or resolved == root:
            raise ValueError("Invalid run key")
        return resolved

    def _checkpoint_locked(self):
        if self._closed:
            raise QueueStorageError("任务服务已关闭。")
        self._ensure_writable_locked()
        return deepcopy(self._jobs), deepcopy(self._intake_batches), self._paused

    def _commit_locked(self, checkpoint) -> None:
        try:
            self._persist_locked()
        except QueueStorageError:
            self._jobs, self._intake_batches, _old_paused = checkpoint
            self._paused = True
            raise

    def _ensure_writable_locked(self) -> None:
        if self._storage_error:
            raise QueueStorageError(self._storage_error)

    def _halt_storage(self, exc: Exception) -> None:
        self._storage_error = redact_text(str(exc))
        self._paused = True
        for event in self._cancel_events.values():
            event.set()

    def _persist_locked(self) -> None:
        self._ensure_writable_locked()
        try:
            self._store.save({"schema_version": QUEUE_SCHEMA_VERSION, "paused": self._paused,
                              "intake_batches": self._intake_batches,
                              "jobs": [asdict(job) for job in self._jobs]})
        except QueueStorageError as exc:
            self._halt_storage(exc)
            raise


def _invoke_runner(runner, argument, **kwargs):
    parameters = inspect.signature(runner).parameters
    if not any(parameter.kind == parameter.VAR_KEYWORD for parameter in parameters.values()):
        kwargs = {key: value for key, value in kwargs.items() if key in parameters}
    return runner(argument, **kwargs)


def _elapsed(start: str | None, finish: str | None) -> float:
    if not start:
        return 0.0
    try:
        begin = datetime.fromisoformat(start)
        end = datetime.fromisoformat(finish) if finish else datetime.now(timezone.utc)
        return max(0.0, (end - begin).total_seconds())
    except (ValueError, TypeError):
        return 0.0

def _request_to_payload(request: PipelineRequest) -> dict[str, Any]:
    # Persist new serializable request fields automatically; interactive callbacks
    # can never survive a service restart and are intentionally not a wire field.
    return {item.name: str(value) if isinstance(value, Path) else value
            for item in fields(PipelineRequest) if item.name != "confirm_long_video"
            for value in [getattr(request, item.name)]}


def _read_metadata_title(run_dir: Path) -> str | None:
    try:
        data = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    title = _optional_text(data.get("part_title")) or _optional_text(data.get("title"))
    return redact_text(title) if title else None


def _display_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    title = value.strip()
    return redact_text(title) if title else None


def _queue_request_key(job: QueueJob) -> str:
    request = job.request if isinstance(job.request, dict) else {}
    url = request.get("url")
    return str(url).strip() if url is not None else str(job.run_key or "")


def _accepted_job_payload(job: QueueJob) -> dict[str, Any]:
    request = job.request if isinstance(job.request, dict) else {}
    return {
        "url": str(request.get("url") or ""),
        "job_id": job.job_id,
        "status": "queued",
    }


def _intake_origin_payload(
    origin: dict[str, Any],
    *,
    batch_id: str,
    index: int,
) -> dict[str, Any]:
    payload = deepcopy(origin)
    payload["external_batch_id"] = batch_id
    if not payload.get("external_item_id"):
        payload["external_item_id"] = f"{batch_id}:{index}"
    return payload


def _payload_to_request(payload: dict[str, Any]) -> PipelineRequest:
    known = {item.name for item in fields(PipelineRequest)} - {"confirm_long_video"}
    values = {key: value for key, value in payload.items() if key in known}
    values["url"] = str(values.get("url") or "")
    values["out"] = Path(str(values.get("out") or "./outputs"))
    if values.get("cookies_file"):
        values["cookies_file"] = Path(str(values["cookies_file"]))
    return PipelineRequest(**values)


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _initial_progress() -> list[dict[str, str]]:
    return [{"stage": stage, "status": "pending"} for stage in STAGES]


def _set_progress(progress: list[dict[str, str]], stage: str, status: str) -> None:
    for item in progress:
        if item.get("stage") == stage:
            item["status"] = status
            return
    progress.append({"stage": stage, "status": status})


def _read_quality(run_dir: Path) -> dict[str, Any]:
    unknown = {"status": "unknown", "review_required": False, "reasons": []}
    try:
        path = run_dir / "quality.json"
        if path.is_symlink():
            return unknown
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return unknown
    if not isinstance(value, dict) or value.get("status") not in {"clean", "needs_review", "unusable", "unknown"}:
        return unknown
    return value


def _retry_failure_artifacts(run_dir: Path, diagnostics_path: Path | None) -> tuple[list[str], list[str]]:
    # The current exception identifies its attempt diagnostic. The preserved
    # previous delivery's diagnostics.json cannot explain this failed retry.
    paths = [name for name in ("metadata.json", "transcript.json", "transcript.txt", "transcript.srt",
                              "transcript_source.zip", "quality.json", "chunks.json", "transcript_article.json")
             if (run_dir / name).is_file() and not (run_dir / name).is_symlink()]
    if diagnostics_path is None:
        return paths, []
    diagnostic = Path(diagnostics_path)
    if diagnostic.is_symlink() or diagnostic.parent.resolve() != run_dir.resolve():
        return paths, []
    try:
        data = json.loads(diagnostic.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    candidate_paths = data.get("artifact_paths")
    if isinstance(candidate_paths, list):
        paths = [name for name in candidate_paths if isinstance(name, str)
                 and not Path(name).is_absolute() and ".." not in Path(name).parts
                 and (run_dir / name).resolve().is_relative_to(run_dir.resolve())
                 and (run_dir / name).is_file() and not (run_dir / name).is_symlink()]
    if diagnostic.is_file() and diagnostic.name not in paths:
        paths.insert(0, diagnostic.name)
    warnings = data.get("warnings")
    return paths, [value for value in warnings if isinstance(value, str)] if isinstance(warnings, list) else []
