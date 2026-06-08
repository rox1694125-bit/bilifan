from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock, Thread
from uuid import uuid4

from bilifan.diagnostics import redact_text
from bilifan.pipeline import PipelineResult, PipelineRunError

STAGES = [
    "preflight",
    "metadata",
    "audio",
    "transcript",
    "chunking",
    "summarization",
    "render",
]


@dataclass
class JobState:
    job_id: str
    status: str = "idle"
    stage: str = "preflight"
    message: str = ""
    progress: list[dict[str, str]] = field(
        default_factory=lambda: [{"stage": stage, "status": "pending"} for stage in STAGES]
    )
    run_key: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "progress": [dict(item) for item in self.progress],
            "run_key": self.run_key,
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings),
        }


class JobManager:
    def __init__(self, *, runner, run_jobs_inline: bool = False):
        self._runner = runner
        self._run_jobs_inline = run_jobs_inline
        self._lock = Lock()
        self._current = JobState(job_id="")

    def start(self, request) -> JobState | None:
        state = JobState(job_id=uuid4().hex, status="running", stage="preflight")
        with self._lock:
            if self._current.status == "running":
                return None
            self._current = state

        if self._run_jobs_inline:
            self._run(state, request)
        else:
            Thread(target=self._run, args=(state, request), daemon=True).start()
        return self.current()

    def current(self) -> JobState:
        with self._lock:
            return JobState(
                job_id=self._current.job_id,
                status=self._current.status,
                stage=self._current.stage,
                message=self._current.message,
                progress=[dict(item) for item in self._current.progress],
                run_key=self._current.run_key,
                artifacts=dict(self._current.artifacts),
                warnings=list(self._current.warnings),
            )

    def _progress(self, job_id: str, stage: str, status: str, message: str) -> None:
        with self._lock:
            if self._current.job_id != job_id or self._current.status != "running":
                return
            self._current.stage = stage
            self._current.message = redact_text(message)
            if status == "failed":
                self._current.status = "failed"
            for item in self._current.progress:
                if item["stage"] == stage:
                    item["status"] = status
                    break

    def _run(self, state: JobState, request) -> None:
        def progress_callback(stage: str, status: str, message: str) -> None:
            self._progress(state.job_id, stage, status, message)

        try:
            result = self._runner(request, progress_callback=progress_callback)
            if not isinstance(result, PipelineResult):
                raise RuntimeError("Pipeline runner returned no result.")
        except PipelineRunError as exc:
            with self._lock:
                if self._current.job_id != state.job_id:
                    return
                self._current.message = redact_text(str(exc))
                self._current.status = "failed"
                failed_stage = self._current.stage or "preflight"
                self._current.stage = failed_stage
                self._current.run_key = exc.run_key
                self._current.artifacts = _artifact_links(exc.run_key, exc.artifact_paths)
                self._current.warnings = list(exc.warnings)
                for item in self._current.progress:
                    if item["stage"] == failed_stage:
                        item["status"] = "failed"
                        break
            return
        except Exception as exc:
            message = redact_text(str(exc))
            with self._lock:
                if self._current.job_id != state.job_id:
                    return
                self._current.message = message
                self._current.status = "failed"
                failed_stage = self._current.stage or "preflight"
                self._current.stage = failed_stage
                for item in self._current.progress:
                    if item["stage"] == failed_stage:
                        item["status"] = "failed"
                        break
            return

        artifacts = _artifact_links(result.run_key, result.artifact_paths)
        with self._lock:
            if self._current.job_id != state.job_id:
                return
            self._current.status = "succeeded"
            self._current.stage = "render"
            self._current.message = "Report ready."
            self._current.run_key = result.run_key
            self._current.artifacts = artifacts
            self._current.warnings = list(result.warnings)
            for item in self._current.progress:
                item["status"] = "done"


def _artifact_links(run_key: str, artifact_paths: list[str]) -> dict[str, str]:
    prefix = f"/api/runs/{run_key}/files"
    artifacts: dict[str, str] = {}
    if "report.html" in artifact_paths:
        artifacts["html"] = f"{prefix}/report.html"
    if "report.pdf" in artifact_paths:
        artifacts["pdf"] = f"{prefix}/report.pdf"
    if "diagnostics.json" in artifact_paths:
        artifacts["diagnostics"] = f"{prefix}/diagnostics.json"
    if "transcript.txt" in artifact_paths:
        artifacts["txt"] = f"{prefix}/transcript.txt"
    if "transcript.srt" in artifact_paths:
        artifacts["srt"] = f"{prefix}/transcript.srt"
    if "notes.md" in artifact_paths:
        artifacts["md"] = f"{prefix}/notes.md"
    if "content_bundle.json" in artifact_paths:
        artifacts["bundle"] = f"{prefix}/content_bundle.json"
    if artifact_paths:
        artifacts["folder"] = f"/api/runs/{run_key}/open-folder"
    return artifacts
