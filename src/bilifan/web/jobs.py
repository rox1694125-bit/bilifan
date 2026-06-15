from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from typing import Any
from uuid import uuid4

from bilifan.diagnostics import redact_text
from bilifan.pipeline import PipelineResult, PipelineRunError

from .run_info import read_metadata_title, read_transcript_source_label

STAGES = [
    "preflight",
    "metadata",
    "audio",
    "transcript",
    "chunking",
    "summarization",
    "render",
]


class JobCanceled(RuntimeError):
    """Raised inside a worker when a cooperative cancel request is observed."""


@dataclass
class JobState:
    job_id: str
    status: str = "idle"
    stage: str = "preflight"
    message: str = ""
    title: str | None = None
    transcript_source_label: str | None = None
    request: dict[str, object] = field(default_factory=dict)
    progress: list[dict[str, str]] = field(
        default_factory=lambda: [{"stage": stage, "status": "pending"} for stage in STAGES]
    )
    run_key: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    job_started_at: str | None = None
    stage_started_at: str | None = None
    elapsed_seconds: float = 0
    stage_elapsed_seconds: float = 0
    friendly_error: dict[str, str] | None = None
    retry_actions: list[str] = field(default_factory=list)
    cancel_requested: bool = False
    _job_started_monotonic: float | None = field(default=None, repr=False)
    _stage_started_monotonic: float | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "job_id": self.job_id,
            "status": self.status,
            "stage": self.stage,
            "message": self.message,
            "title": self.title,
            "transcript_source_label": self.transcript_source_label,
            "request": dict(self.request),
            "progress": [dict(item) for item in self.progress],
            "run_key": self.run_key,
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings),
            "job_started_at": self.job_started_at,
            "stage_started_at": self.stage_started_at,
            "elapsed_seconds": self.elapsed_seconds,
            "stage_elapsed_seconds": self.stage_elapsed_seconds,
            "retry_actions": list(self.retry_actions),
        }
        if self.friendly_error is not None:
            data["friendly_error"] = dict(self.friendly_error)
        return data


class JobManager:
    def __init__(self, *, runner, run_jobs_inline: bool = False):
        self._runner = runner
        self._run_jobs_inline = run_jobs_inline
        self._lock = Lock()
        self._current = JobState(job_id="")

    def start(self, request, *, runner=None, initial_stage: str = "preflight") -> JobState | None:
        now_iso = _now_iso()
        now_mono = monotonic()
        state = JobState(
            job_id=uuid4().hex,
            status="running",
            stage=initial_stage,
            request=_request_payload(request),
            progress=_initial_progress(initial_stage),
            job_started_at=now_iso,
            stage_started_at=now_iso,
            _job_started_monotonic=now_mono,
            _stage_started_monotonic=now_mono,
        )
        with self._lock:
            if self._current.status in {"running", "canceling"}:
                return None
            self._current = state

        job_runner = runner or self._runner
        if self._run_jobs_inline:
            self._run(state, request, job_runner)
        else:
            Thread(target=self._run, args=(state, request, job_runner), daemon=True).start()
        return self.current()

    def cancel_current(self) -> JobState | None:
        with self._lock:
            if self._current.status != "running":
                return None
            self._current.cancel_requested = True
            self._current.status = "canceling"
            self._current.message = "正在取消任务，等待当前步骤安全退出。"
            for item in self._current.progress:
                if item["stage"] == self._current.stage:
                    item["status"] = "canceling"
                    break
            self._refresh_elapsed_locked()
            return self._copy_current_locked()

    def current(self) -> JobState:
        with self._lock:
            self._refresh_elapsed_locked()
            return self._copy_current_locked()

    def _progress(self, job_id: str, stage: str, status: str, message: str) -> None:
        with self._lock:
            if self._current.job_id != job_id or self._current.status not in {"running", "canceling"}:
                return
            if self._current.cancel_requested:
                raise JobCanceled
            if stage != self._current.stage and status == "running":
                self._current.stage_started_at = _now_iso()
                self._current._stage_started_monotonic = monotonic()
            self._current.stage = stage
            self._current.message = redact_text(message)
            if status == "failed":
                self._current.status = "failed"
            for item in self._current.progress:
                if item["stage"] == stage:
                    item["status"] = status
                    break
            self._refresh_elapsed_locked()
            if self._current.cancel_requested:
                raise JobCanceled

    def _run(self, state: JobState, request, runner) -> None:
        def progress_callback(stage: str, status: str, message: str) -> None:
            self._progress(state.job_id, stage, status, message)

        try:
            result = runner(request, progress_callback=progress_callback)
            if not _is_job_result(result):
                raise RuntimeError("Pipeline runner returned no result.")
        except JobCanceled:
            self._mark_canceled(state.job_id)
            return
        except PipelineRunError as exc:
            with self._lock:
                if self._current.job_id != state.job_id:
                    return
                if self._current.cancel_requested:
                    self._mark_canceled_locked()
                    return
                self._current.message = redact_text(str(exc))
                self._current.status = "failed"
                failed_stage = self._current.stage or "preflight"
                self._current.stage = failed_stage
                self._current.run_key = exc.run_key
                self._current.artifacts = _artifact_links(exc.run_key, exc.artifact_paths)
                self._current.warnings = list(exc.warnings)
                self._current.title = read_metadata_title(exc.diagnostics_path.parent)
                self._current.transcript_source_label = read_transcript_source_label(
                    exc.diagnostics_path.parent
                )
                self._current.friendly_error = explain_failure(
                    stage=failed_stage,
                    message=self._current.message,
                    warnings=exc.warnings,
                )
                self._current.retry_actions = retry_actions_for(
                    failed_stage,
                    exc.artifact_paths,
                )
                for item in self._current.progress:
                    if item["stage"] == failed_stage:
                        item["status"] = "failed"
                        break
                self._refresh_elapsed_locked()
            return
        except Exception as exc:
            message = redact_text(str(exc))
            with self._lock:
                if self._current.job_id != state.job_id:
                    return
                if self._current.cancel_requested:
                    self._mark_canceled_locked()
                    return
                self._current.message = message
                self._current.status = "failed"
                failed_stage = self._current.stage or "preflight"
                self._current.stage = failed_stage
                self._current.friendly_error = explain_failure(
                    stage=failed_stage,
                    message=message,
                    warnings=[],
                )
                for item in self._current.progress:
                    if item["stage"] == failed_stage:
                        item["status"] = "failed"
                        break
                self._refresh_elapsed_locked()
            return

        artifacts = _artifact_links(result.run_key, result.artifact_paths)
        with self._lock:
            if self._current.job_id != state.job_id:
                return
            if self._current.cancel_requested:
                self._mark_canceled_locked()
                return
            self._current.status = "succeeded"
            self._current.stage = "render"
            self._current.message = "Report ready."
            self._current.run_key = result.run_key
            self._current.artifacts = artifacts
            self._current.warnings = list(result.warnings)
            self._current.title = read_metadata_title(result.run_dir)
            self._current.transcript_source_label = read_transcript_source_label(result.run_dir)
            self._current.friendly_error = None
            self._current.retry_actions = []
            for item in self._current.progress:
                item["status"] = "done"
            self._refresh_elapsed_locked()

    def _mark_canceled(self, job_id: str) -> None:
        with self._lock:
            if self._current.job_id != job_id:
                return
            self._mark_canceled_locked()

    def _mark_canceled_locked(self) -> None:
        self._current.status = "canceled"
        self._current.message = "任务已取消。"
        self._current.friendly_error = None
        self._current.retry_actions = []
        for item in self._current.progress:
            if item["stage"] == self._current.stage:
                item["status"] = "canceled"
                break
        self._refresh_elapsed_locked()

    def _refresh_elapsed_locked(self) -> None:
        now = monotonic()
        if self._current._job_started_monotonic is not None:
            self._current.elapsed_seconds = round(
                max(0, now - self._current._job_started_monotonic),
                3,
            )
        if self._current._stage_started_monotonic is not None:
            self._current.stage_elapsed_seconds = round(
                max(0, now - self._current._stage_started_monotonic),
                3,
            )

    def _copy_current_locked(self) -> JobState:
        return JobState(
            job_id=self._current.job_id,
            status=self._current.status,
            stage=self._current.stage,
            message=self._current.message,
            title=self._current.title,
            transcript_source_label=self._current.transcript_source_label,
            request=dict(self._current.request),
            progress=[dict(item) for item in self._current.progress],
            run_key=self._current.run_key,
            artifacts=dict(self._current.artifacts),
            warnings=list(self._current.warnings),
            job_started_at=self._current.job_started_at,
            stage_started_at=self._current.stage_started_at,
            elapsed_seconds=self._current.elapsed_seconds,
            stage_elapsed_seconds=self._current.stage_elapsed_seconds,
            friendly_error=(
                None
                if self._current.friendly_error is None
                else dict(self._current.friendly_error)
            ),
            retry_actions=list(self._current.retry_actions),
            cancel_requested=self._current.cancel_requested,
            _job_started_monotonic=self._current._job_started_monotonic,
            _stage_started_monotonic=self._current._stage_started_monotonic,
        )


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
    if "nabaichuan.jsonl" in artifact_paths:
        artifacts["nabaichuan"] = f"{prefix}/nabaichuan.jsonl"
    if "media/audio.mp3" in artifact_paths:
        artifacts["audio"] = f"{prefix}/media/audio.mp3"
    if artifact_paths:
        artifacts["folder"] = f"/api/runs/{run_key}/open-folder"
    return artifacts


def _request_payload(request: Any) -> dict[str, object]:
    payload: dict[str, object] = {}
    for name in [
        "url",
        "output_format",
        "transcriber",
        "language",
        "force_whisper",
        "summary_template",
        "with_frames",
        "with_diagrams",
        "require_pdf",
        "allow_long_video",
    ]:
        if hasattr(request, name):
            value = getattr(request, name)
            if isinstance(value, Path):
                value = str(value)
            payload[name] = value
    if hasattr(request, "out"):
        payload["out"] = str(getattr(request, "out"))
    return payload


def explain_failure(
    *,
    stage: str,
    message: str,
    warnings: list[str],
) -> dict[str, str]:
    normalized = f"{stage} {message} {' '.join(warnings)}".lower()
    if "codex exec failed to start" in normalized or "no such file or directory: 'codex'" in normalized:
        return {
            "title": "Codex CLI 未找到",
            "cause": "系统找不到 codex 命令，当前无法调用 Codex 做总结。",
            "next_action": "在 Terminal 里确认 codex 已安装并能直接运行，然后重启 Bilifan Web UI。",
        }
    if "duration differs" in normalized or "duration_mismatch" in normalized:
        return {
            "title": "音频时长校验失败",
            "cause": "下载到的音频时长和视频元数据差异超过阈值。",
            "next_action": "换一个公开视频重试；如果视频需要登录或被风控，先配置 cookies 后再跑。",
        }
    if "stream download failed" in normalized or "timed out" in normalized:
        return {
            "title": "音频下载超时或中断",
            "cause": "B 站音频流读取失败，可能是网络、风控或视频访问限制。",
            "next_action": "稍后重试；如果一直失败，尝试使用浏览器 cookies。",
        }
    if "timestamp" in normalized or "anchored" in normalized:
        return {
            "title": "总结时间戳校验失败",
            "cause": "模型返回的章节时间戳没有落在逐字稿片段范围内。",
            "next_action": "使用重试总结；如果反复失败，换短一点的视频或减少并发操作。",
        }
    if "unsupported" in normalized or "invalid" in normalized and "url" in normalized:
        return {
            "title": "视频链接不支持",
            "cause": "当前链接不是 Bilifan 支持的 B 站当前 P 或公开视频链接。",
            "next_action": "复制浏览器地址栏里的 B 站视频页 URL 后重新开始。",
        }
    return {
        "title": "任务失败",
        "cause": message or "当前阶段失败，具体原因见 diagnostics.json。",
        "next_action": "先打开 diagnostics 查看原始错误；如果是总结或渲染阶段，可尝试下游重试。",
    }


def retry_actions_for(stage: str, artifact_paths: list[str]) -> list[str]:
    artifacts = set(artifact_paths)
    actions: list[str] = []
    if stage == "summarization" and {"metadata.json", "transcript.json", "chunks.json"} <= artifacts:
        actions.append("summarization")
    if stage in {"render", "bundle"} and {"metadata.json", "transcript.json", "chapters.json"} <= artifacts:
        actions.append("render")
    if {"metadata.json", "transcript.json", "chapters.json"} <= artifacts:
        actions.append("bundle")
    return actions


def _initial_progress(active_stage: str) -> list[dict[str, str]]:
    try:
        active_index = STAGES.index(active_stage)
    except ValueError:
        active_index = 0
    progress: list[dict[str, str]] = []
    for index, stage in enumerate(STAGES):
        if index < active_index:
            status = "done"
        elif index == active_index:
            status = "running"
        else:
            status = "pending"
        progress.append({"stage": stage, "status": status})
    return progress


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_job_result(result: Any) -> bool:
    return (
        isinstance(result, PipelineResult)
        or all(hasattr(result, name) for name in ("run_key", "artifact_paths", "warnings"))
    )
