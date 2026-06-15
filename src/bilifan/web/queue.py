from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from uuid import uuid4

from bilifan.diagnostics import redact_text
from bilifan.pipeline import PipelineRequest, PipelineRunError

from .jobs import STAGES, _artifact_links, _now_iso, explain_failure

QUEUE_SCHEMA_VERSION = 1
RECENT_COMPLETED_LIMIT = 3


@dataclass
class QueueJob:
    job_id: str
    status: str
    request: dict[str, Any]
    title: str | None = None
    stage: str = "preflight"
    message: str = ""
    progress: list[dict[str, str]] = field(default_factory=list)
    run_key: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    friendly_error: dict[str, str] | None = None
    created_at: str = field(default_factory=_now_iso)
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if self.friendly_error is None:
            data.pop("friendly_error", None)
        return data


class BatchQueueManager:
    def __init__(
        self,
        *,
        runner,
        storage_path: Path,
        run_jobs_inline: bool = False,
        paused: bool = False,
    ) -> None:
        self._runner = runner
        self._storage_path = storage_path
        self._run_jobs_inline = run_jobs_inline
        self._lock = Lock()
        self._paused = paused
        self._worker_running = False
        self._jobs: list[QueueJob] = []
        self._load()

    def submit(self, requests: list[PipelineRequest]) -> dict[str, Any]:
        with self._lock:
            for request in requests:
                self._jobs.append(
                    QueueJob(
                        job_id=uuid4().hex,
                        status="queued",
                        request=_request_to_payload(request),
                        progress=_initial_progress(),
                    )
                )
            self._persist_locked()
            should_start = self._should_start_worker_locked()
        if should_start:
            self._start_worker()
        return self.state()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return self._state_locked()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            self._paused = True
            self._persist_locked()
            return self._state_locked()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            self._paused = False
            self._persist_locked()
            should_start = self._should_start_worker_locked()
        if should_start:
            self._start_worker()
        return self.state()

    def cancel_pending(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._find_locked(job_id)
            if job is not None and job.status == "queued":
                job.status = "canceled"
                job.stage = "canceled"
                job.message = "Pending queue job canceled."
                job.finished_at = _now_iso()
                self._persist_locked()
            return self._state_locked()

    def retry(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self._find_locked(job_id)
            if job is None or job.status not in {"failed", "canceled"}:
                return self._state_locked()
            self._jobs.append(
                QueueJob(
                    job_id=uuid4().hex,
                    status="queued",
                    request=dict(job.request),
                    progress=_initial_progress(),
                )
            )
            self._persist_locked()
            should_start = self._should_start_worker_locked()
        if should_start:
            self._start_worker()
        return self.state()

    def clear_completed(self) -> dict[str, Any]:
        with self._lock:
            replaced_attempt_ids = self._replaced_attempt_ids_locked()
            self._jobs = [
                job
                for job in self._jobs
                if job.status != "succeeded" and job.job_id not in replaced_attempt_ids
            ]
            self._persist_locked()
            return self._state_locked()

    def _start_worker(self) -> None:
        if self._run_jobs_inline:
            self._run_loop()
            return
        Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self) -> None:
        with self._lock:
            if self._worker_running:
                return
            self._worker_running = True
        try:
            while True:
                with self._lock:
                    if self._paused:
                        return
                    job = self._next_queued_locked()
                    if job is None:
                        return
                    job.status = "running"
                    job.stage = "preflight"
                    job.started_at = _now_iso()
                    job.message = "Queued job started."
                    self._persist_locked()

                self._run_job(job.job_id)
        finally:
            with self._lock:
                self._worker_running = False
                self._persist_locked()

    def _run_job(self, job_id: str) -> None:
        def progress_callback(stage: str, status: str, message: str) -> None:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None or job.status != "running":
                    return
                job.stage = stage
                job.message = redact_text(message)
                _set_progress(job.progress, stage, status)
                self._persist_locked()

        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return
            request = _payload_to_request(job.request)

        try:
            result = self._runner(request, progress_callback=progress_callback)
        except PipelineRunError as exc:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.stage = job.stage or "preflight"
                job.message = redact_text(str(exc))
                job.run_key = exc.run_key
                job.artifacts = _artifact_links(exc.run_key, exc.artifact_paths)
                job.title = _read_metadata_title(Path(str(request.out)) / exc.run_key) or job.title
                job.warnings = list(exc.warnings)
                job.friendly_error = explain_failure(
                    stage=job.stage,
                    message=job.message,
                    warnings=job.warnings,
                )
                job.finished_at = _now_iso()
                _set_progress(job.progress, job.stage, "failed")
                self._persist_locked()
            return
        except Exception as exc:
            with self._lock:
                job = self._find_locked(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.message = redact_text(str(exc))
                job.friendly_error = explain_failure(
                    stage=job.stage,
                    message=job.message,
                    warnings=[],
                )
                job.finished_at = _now_iso()
                _set_progress(job.progress, job.stage, "failed")
                self._persist_locked()
            return

        with self._lock:
            job = self._find_locked(job_id)
            if job is None:
                return
            job.status = "succeeded"
            job.stage = "render"
            job.message = "Report ready."
            job.run_key = result.run_key
            job.artifacts = _artifact_links(result.run_key, result.artifact_paths)
            job.title = _read_metadata_title(result.run_dir) or job.title
            job.warnings = list(result.warnings)
            job.friendly_error = None
            job.finished_at = _now_iso()
            for item in job.progress:
                item["status"] = "done"
            self._persist_locked()

    def _state_locked(self) -> dict[str, Any]:
        counts = {status: 0 for status in ["queued", "running", "succeeded", "failed", "canceled"]}
        for job in self._jobs:
            if job.status in counts:
                counts[job.status] += 1
        replaced_attempt_ids = self._replaced_attempt_ids_locked()
        recent_completed = [job for job in self._jobs if job.status == "succeeded"][-RECENT_COMPLETED_LIMIT:]
        recent_completed_ids = {job.job_id for job in recent_completed}
        visible_jobs = [
            job
            for job in self._jobs
            if job.job_id not in replaced_attempt_ids
            and (job.status != "succeeded" or job.job_id in recent_completed_ids)
        ]
        visible_counts = {status: 0 for status in counts}
        for job in visible_jobs:
            if job.status in visible_counts:
                visible_counts[job.status] += 1
        return {
            "paused": self._paused,
            "counts": counts,
            "visible_counts": visible_counts,
            "total_items": len(self._jobs),
            "hidden_completed": max(0, counts["succeeded"] - RECENT_COMPLETED_LIMIT),
            "hidden_replaced": len(replaced_attempt_ids),
            "items": [job.as_dict() for job in visible_jobs],
        }

    def _replaced_attempt_ids_locked(self) -> set[str]:
        last_succeeded_index_by_request: dict[str, int] = {}
        for index, job in enumerate(self._jobs):
            if job.status == "succeeded":
                request_key = _queue_request_key(job)
                if request_key:
                    last_succeeded_index_by_request[request_key] = index
        replaced_ids: set[str] = set()
        for index, job in enumerate(self._jobs):
            if job.status not in {"failed", "canceled"}:
                continue
            request_key = _queue_request_key(job)
            if request_key and last_succeeded_index_by_request.get(request_key, -1) > index:
                replaced_ids.add(job.job_id)
        return replaced_ids

    def _find_locked(self, job_id: str) -> QueueJob | None:
        for job in self._jobs:
            if job.job_id == job_id:
                return job
        return None

    def _next_queued_locked(self) -> QueueJob | None:
        for job in self._jobs:
            if job.status == "queued":
                return job
        return None

    def _should_start_worker_locked(self) -> bool:
        return (
            not self._paused
            and not self._worker_running
            and any(job.status == "queued" for job in self._jobs)
        )

    def _load(self) -> None:
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self._paused = bool(data.get("paused", self._paused))
        raw_jobs = data.get("jobs")
        if not isinstance(raw_jobs, list):
            return
        jobs: list[QueueJob] = []
        outputs_root = self._storage_path.parent.parent
        for raw_job in raw_jobs:
            if not isinstance(raw_job, dict):
                continue
            run_key = raw_job.get("run_key") if isinstance(raw_job.get("run_key"), str) else None
            job = QueueJob(
                job_id=str(raw_job.get("job_id") or uuid4().hex),
                status=str(raw_job.get("status") or "queued"),
                request=raw_job.get("request") if isinstance(raw_job.get("request"), dict) else {},
                title=_optional_text(raw_job.get("title")),
                stage=str(raw_job.get("stage") or "preflight"),
                message=str(raw_job.get("message") or ""),
                progress=raw_job.get("progress") if isinstance(raw_job.get("progress"), list) else _initial_progress(),
                run_key=run_key,
                artifacts=raw_job.get("artifacts") if isinstance(raw_job.get("artifacts"), dict) else {},
                warnings=raw_job.get("warnings") if isinstance(raw_job.get("warnings"), list) else [],
                friendly_error=raw_job.get("friendly_error") if isinstance(raw_job.get("friendly_error"), dict) else None,
                created_at=str(raw_job.get("created_at") or _now_iso()),
                started_at=raw_job.get("started_at") if isinstance(raw_job.get("started_at"), str) else None,
                finished_at=raw_job.get("finished_at") if isinstance(raw_job.get("finished_at"), str) else None,
            )
            if job.title is None and run_key:
                job.title = _read_metadata_title(outputs_root / run_key)
            if job.status in {"running", "canceling"}:
                job.status = "failed"
                job.stage = "interrupted"
                job.message = "Service restarted before this queue job finished."
                job.finished_at = _now_iso()
            jobs.append(job)
        self._jobs = jobs
        self._persist_locked()

    def _persist_locked(self) -> None:
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._storage_path.write_text(
            json.dumps(
                {
                    "schema_version": QUEUE_SCHEMA_VERSION,
                    "paused": self._paused,
                    "jobs": [job.as_dict() for job in self._jobs],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


def _request_to_payload(request: PipelineRequest) -> dict[str, Any]:
    return {
        "url": request.url,
        "out": str(request.out),
        "cookies_from_browser": request.cookies_from_browser,
        "cookies_file": str(request.cookies_file) if request.cookies_file is not None else None,
        "output_format": request.output_format,
        "transcriber": request.transcriber,
        "language": request.language,
        "force_whisper": request.force_whisper,
        "llm_provider": request.llm_provider,
        "llm_model": request.llm_model,
        "summary_template": request.summary_template,
        "with_frames": request.with_frames,
        "with_diagrams": request.with_diagrams,
        "require_pdf": request.require_pdf,
        "allow_long_video": request.allow_long_video,
        "yes_i_understand": request.yes_i_understand,
        "overwrite": request.overwrite,
    }


def _read_metadata_title(run_dir: Path) -> str | None:
    try:
        data = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    title = _optional_text(data.get("title")) or _optional_text(data.get("part_title"))
    return redact_text(title) if title else None


def _queue_request_key(job: QueueJob) -> str:
    request = job.request if isinstance(job.request, dict) else {}
    url = request.get("url")
    return str(url).strip() if url is not None else ""


def _payload_to_request(payload: dict[str, Any]) -> PipelineRequest:
    return PipelineRequest(
        url=str(payload.get("url") or ""),
        out=Path(str(payload.get("out") or "./outputs")),
        cookies_from_browser=_optional_text(payload.get("cookies_from_browser")),
        cookies_file=(
            Path(str(payload["cookies_file"]))
            if isinstance(payload.get("cookies_file"), str) and payload.get("cookies_file")
            else None
        ),
        output_format=str(payload.get("output_format") or "html,pdf"),
        transcriber=str(payload.get("transcriber") or "auto"),
        language=str(payload.get("language") or "auto"),
        force_whisper=bool(payload.get("force_whisper")),
        llm_provider=str(payload.get("llm_provider") or "codex-exec"),
        llm_model=str(payload.get("llm_model") or "gpt-5.5"),
        summary_template=str(payload.get("summary_template") or "学习笔记"),
        with_frames=bool(payload.get("with_frames")),
        with_diagrams=bool(payload.get("with_diagrams")),
        require_pdf=bool(payload.get("require_pdf")),
        allow_long_video=bool(payload.get("allow_long_video")),
        yes_i_understand=bool(payload.get("yes_i_understand")),
        overwrite=bool(payload.get("overwrite")),
    )


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
