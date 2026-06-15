from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from bilifan.config import default_config_path, read_config, write_consent
from bilifan.exports import ExportError, write_nabaichuan_jsonl
from bilifan.pipeline import (
    PipelineRequest,
    PipelineRunError,
    run_summarize_pipeline,
    validate_output_format,
)
from bilifan.retry import RETRY_STAGES, RetryError, retry_run
from bilifan.summarizer import SummarizationError, validate_summary_style

from .files import (
    list_all_runs,
    list_latest_runs,
    list_run_files,
    open_run_folder,
    resolve_run_file,
    resolve_run_dir,
)
from .jobs import JobManager
from .queue import BatchQueueManager
from .security import TokenAuth
from .ui import render_app_html

WEB_DEFAULTS = {
    "format": "html,pdf",
    "force_whisper": False,
    "language": "auto",
    "summary_template": "AI 自动判断",
    "with_frames": False,
    "with_diagrams": False,
    "require_pdf": False,
    "allow_long_video": False,
}
EXPORT_FILE_PATTERN = re.compile(
    r"nabaichuan_batch_[0-9]{8}_[0-9]{6}_[0-9]{6}\.jsonl"
)


class JobCreatePayload(BaseModel):
    url: str
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str = WEB_DEFAULTS["language"]
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


class RetryCreatePayload(BaseModel):
    from_stage: str
    format: str = WEB_DEFAULTS["format"]
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]


class BatchJobCreatePayload(BaseModel):
    urls: list[str]
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str = WEB_DEFAULTS["language"]
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


def create_app(
    outputs: Path,
    token: str,
    open_browser: bool = True,
    pipeline_runner=run_summarize_pipeline,
    retry_runner=retry_run,
    run_jobs_inline: bool = False,
) -> FastAPI:
    auth = TokenAuth(token)
    jobs = JobManager(runner=pipeline_runner, run_jobs_inline=run_jobs_inline)
    queue = BatchQueueManager(
        runner=pipeline_runner,
        storage_path=outputs / "_jobs" / "jobs.json",
        run_jobs_inline=run_jobs_inline,
    )
    app = FastAPI()

    @app.middleware("http")
    async def add_security_headers(request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        return response

    def require_token(
        header_token: str | None = Header(default=None, alias="X-Bilifan-Token"),
        query_token: str | None = Query(default=None, alias="token"),
    ) -> None:
        try:
            auth.require(header_token=header_token, query_token=query_token)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render_app_html(token=token)

    @app.get("/api/config")
    def get_config(_: None = Depends(require_token)) -> dict[str, object]:
        config = read_config(default_config_path())
        return {
            "consent": {
                "local_processing": config.local_processing_notice_accepted_at is not None,
                "cookies": config.cookies_notice_accepted_at is not None,
                "accepted_via": config.accepted_via,
                "notice_version": config.notice_version,
            },
            "defaults": dict(WEB_DEFAULTS),
        }

    @app.post("/api/consent")
    def accept_consent(_: None = Depends(require_token)) -> dict[str, bool]:
        write_consent(
            default_config_path(),
            local_processing=True,
            accepted_via="web-ui",
        )
        return {"ok": True}

    @app.get("/api/history")
    def history(_: None = Depends(require_token)) -> dict[str, object]:
        return {"items": _add_token_to_artifact_links(list_latest_runs(outputs), token)}

    @app.post("/api/jobs")
    def create_job(
        payload: JobCreatePayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before starting a job.",
            )
        request = PipelineRequest(
            url=payload.url,
            out=outputs,
            output_format=payload.format,
            force_whisper=payload.force_whisper,
            language=payload.language,
            summary_template=_validated_summary_template(payload.summary_template),
            with_frames=payload.with_frames,
            with_diagrams=payload.with_diagrams,
            require_pdf=payload.require_pdf,
            allow_long_video=payload.allow_long_video,
            yes_i_understand=True,
            overwrite=False,
        )
        state = jobs.start(request)
        if state is None:
            raise HTTPException(status_code=409, detail="A job is already running.")
        return {"job_id": state.job_id, "status": "running"}

    @app.get("/api/jobs/current")
    def current_job(_: None = Depends(require_token)) -> dict[str, object]:
        return jobs.current().as_dict()

    @app.get("/api/jobs/queue")
    def queue_state(_: None = Depends(require_token)) -> dict[str, object]:
        return _task_center_state(
            current_job=jobs.current().as_dict(),
            queue_state=queue.state(),
        )

    @app.post("/api/jobs/batch")
    def create_batch_jobs(
        payload: BatchJobCreatePayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before starting a batch.",
            )
        urls = [url.strip() for url in payload.urls if url.strip()]
        if not urls:
            raise HTTPException(status_code=400, detail="Batch requires at least one URL.")
        summary_template = _validated_summary_template(payload.summary_template)
        requests = [
            PipelineRequest(
                url=url,
                out=outputs,
                output_format=payload.format,
                force_whisper=payload.force_whisper,
                language=payload.language,
                summary_template=summary_template,
                with_frames=payload.with_frames,
                with_diagrams=payload.with_diagrams,
                require_pdf=payload.require_pdf,
                allow_long_video=payload.allow_long_video,
                yes_i_understand=True,
                overwrite=False,
            )
            for url in urls
        ]
        return queue.submit(requests)

    @app.post("/api/jobs/queue/pause")
    def pause_queue(_: None = Depends(require_token)) -> dict[str, object]:
        return queue.pause()

    @app.post("/api/jobs/queue/resume")
    def resume_queue(_: None = Depends(require_token)) -> dict[str, object]:
        return queue.resume()

    @app.post("/api/jobs/queue/clear-completed")
    def clear_completed_queue(_: None = Depends(require_token)) -> dict[str, object]:
        return queue.clear_completed()

    @app.post("/api/jobs/queue/{job_id}/cancel")
    def cancel_queued_job(
        job_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        return queue.cancel_pending(job_id)

    @app.post("/api/jobs/queue/{job_id}/retry")
    def retry_queued_job(
        job_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        return queue.retry(job_id)

    @app.post("/api/jobs/current/cancel")
    def cancel_current_job(_: None = Depends(require_token)) -> dict[str, object]:
        state = jobs.cancel_current()
        if state is None:
            raise HTTPException(status_code=409, detail="No running job to cancel.")
        return {"job_id": state.job_id, "status": state.status}

    @app.post("/api/runs/{output_id}/runs/{run_id}/retry")
    def retry_run_job(
        output_id: str,
        run_id: str,
        payload: RetryCreatePayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        from_stage = payload.from_stage.strip().lower()
        if from_stage not in RETRY_STAGES:
            raise HTTPException(
                status_code=400,
                detail="Retry stage must be summarization, render, or bundle.",
            )
        try:
            validate_output_format(payload.format)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if payload.llm_provider != "codex-exec":
            raise HTTPException(
                status_code=400,
                detail="Retry llm_provider must be codex-exec.",
            )
        if not payload.llm_model.strip():
            raise HTTPException(status_code=400, detail="Retry llm_model is required.")
        summary_template = _validated_summary_template(payload.summary_template)
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before retrying a job.",
            )
        try:
            run_dir = resolve_run_dir(outputs, output_id, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"{output_id}/runs/{run_id}")

        def run_retry(_request, *, progress_callback):
            progress_callback(from_stage, "running", f"Retrying {from_stage}.")
            try:
                result = retry_runner(
                    run_dir,
                    from_stage=from_stage,
                    output_format=payload.format,
                    llm_provider=payload.llm_provider,
                    llm_model=payload.llm_model,
                    summary_template=summary_template,
                    with_frames=payload.with_frames,
                    with_diagrams=payload.with_diagrams,
                    require_pdf=payload.require_pdf,
                )
            except RetryError as exc:
                retry_artifacts, retry_warnings = _retry_failure_context(run_dir)
                raise PipelineRunError(
                    str(exc),
                    run_key=f"{output_id}/runs/{run_id}",
                    diagnostics_path=run_dir / "diagnostics.json",
                    artifact_paths=retry_artifacts,
                    warnings=retry_warnings,
                ) from exc
            progress_callback("render" if from_stage != "bundle" else "render", "done", "Retry completed.")
            return result

        state = jobs.start(object(), runner=run_retry, initial_stage=from_stage)
        if state is None:
            raise HTTPException(status_code=409, detail="A job is already running.")
        return {"job_id": state.job_id, "status": "running"}

    @app.post("/api/runs/{output_id}/runs/{run_id}/exports/nabaichuan")
    def export_run_nabaichuan(
        output_id: str,
        run_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before exporting a run.",
            )
        try:
            run_dir = resolve_run_dir(outputs, output_id, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not run_dir.is_dir():
            raise HTTPException(status_code=404, detail=f"{output_id}/runs/{run_id}")
        if not _is_successful_run_dir(run_dir):
            raise HTTPException(
                status_code=409,
                detail="Nabaichuan export requires a successful run.",
            )
        try:
            artifact = write_nabaichuan_jsonl(run_dir)
        except ExportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "artifact": f"/api/runs/{output_id}/runs/{run_id}/files/{artifact}",
        }

    @app.post("/api/exports/nabaichuan/batch")
    def export_batch_nabaichuan(_: None = Depends(require_token)) -> dict[str, object]:
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before exporting runs.",
            )
        export_dir = outputs / "_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        file_name = datetime.now(timezone.utc).strftime(
            "nabaichuan_batch_%Y%m%d_%H%M%S_%f.jsonl"
        )
        output_path = export_dir / file_name
        exported_runs = 0
        skipped_runs = 0
        lines: list[str] = []
        for item in list_all_runs(outputs):
            if item.get("status") != "succeeded":
                skipped_runs += 1
                continue
            run_key = item.get("run_key")
            if not isinstance(run_key, str):
                skipped_runs += 1
                continue
            try:
                output_id, marker, run_id = run_key.split("/")
                if marker != "runs":
                    raise ValueError
                run_dir = resolve_run_dir(outputs, output_id, run_id)
                if not _is_successful_run_dir(run_dir):
                    raise ValueError
                artifact = write_nabaichuan_jsonl(run_dir)
                lines.extend(
                    (run_dir / artifact).read_text(encoding="utf-8").splitlines()
                )
            except (ValueError, FileNotFoundError, OSError, ExportError):
                skipped_runs += 1
                continue
            exported_runs += 1
        output_path.write_text(
            "".join(line + "\n" for line in lines),
            encoding="utf-8",
        )
        return {
            "ok": True,
            "artifact": f"/api/exports/{file_name}",
            "exported_runs": exported_runs,
            "skipped_runs": skipped_runs,
        }

    @app.get("/api/exports/{file_name}")
    def export_file(
        file_name: str,
        _: None = Depends(require_token),
    ) -> FileResponse:
        if EXPORT_FILE_PATTERN.fullmatch(file_name) is None:
            raise HTTPException(status_code=400, detail="Invalid export file.")
        path = (outputs / "_exports" / file_name).resolve(strict=False)
        export_root = (outputs / "_exports").resolve(strict=False)
        if not path.is_relative_to(export_root):
            raise HTTPException(status_code=400, detail="Invalid export file.")
        if not path.is_file():
            raise HTTPException(status_code=404, detail=file_name)
        return FileResponse(path)

    @app.get("/api/runs/{output_id}/runs/{run_id}/files")
    def run_files(
        output_id: str,
        run_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, list[str]]:
        try:
            files = list_run_files(outputs, output_id, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"files": files}

    @app.get("/api/runs/{output_id}/runs/{run_id}/files/{file_path:path}")
    def run_file(
        output_id: str,
        run_id: str,
        file_path: str,
        _: None = Depends(require_token),
    ) -> FileResponse:
        try:
            path = resolve_run_file(outputs, output_id, run_id, file_path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FileResponse(path)

    @app.post("/api/runs/{output_id}/runs/{run_id}/open-folder")
    def run_open_folder(
        output_id: str,
        run_id: str,
        _: None = Depends(require_token),
    ) -> dict[str, bool]:
        try:
            open_run_folder(outputs, output_id, run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True}

    return app


def _retry_failure_context(run_dir: Path) -> tuple[list[str], list[str]]:
    diagnostics_path = run_dir / "diagnostics.json"
    artifact_paths = ["diagnostics.json"]
    warnings: list[str] = []
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, ValueError):
        diagnostics = {}
    if isinstance(diagnostics, dict):
        raw_artifacts = diagnostics.get("artifact_paths")
        if isinstance(raw_artifacts, list):
            artifact_paths = [item for item in raw_artifacts if isinstance(item, str)]
            if "diagnostics.json" not in artifact_paths:
                artifact_paths.insert(0, "diagnostics.json")
        raw_warnings = diagnostics.get("warnings")
        if isinstance(raw_warnings, list):
            warnings = [item for item in raw_warnings if isinstance(item, str)]
    return artifact_paths, warnings


def _validated_summary_template(value: str) -> str:
    try:
        return validate_summary_style(value)
    except SummarizationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _is_successful_run_dir(run_dir: Path) -> bool:
    diagnostics_path = run_dir / "diagnostics.json"
    if not diagnostics_path.is_file():
        return False
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(diagnostics, dict)
        and "error_type" in diagnostics
        and diagnostics.get("error_type") is None
    )


def _add_token_to_artifact_links(
    items: list[dict[str, object]],
    token: str,
) -> list[dict[str, object]]:
    query = urlencode({"token": token})
    linked_items: list[dict[str, object]] = []
    for item in items:
        artifacts = item.get("artifacts")
        linked_item = dict(item)
        if isinstance(artifacts, dict):
            linked_item["artifacts"] = {
                str(name): f"{url}?{query}"
                for name, url in artifacts.items()
                if isinstance(url, str)
            }
        linked_items.append(linked_item)
    return linked_items


def _task_center_state(
    *,
    current_job: dict[str, object],
    queue_state: dict[str, object],
) -> dict[str, object]:
    state = dict(queue_state)
    raw_items = queue_state.get("items")
    queue_items = [
        {**item, "source": "queue"}
        for item in raw_items
        if isinstance(item, dict)
    ] if isinstance(raw_items, list) else []
    current_item = _current_task_item(current_job)
    items = [current_item, *queue_items] if current_item is not None else queue_items
    state["items"] = items
    state["queue_counts"] = dict(queue_state.get("counts")) if isinstance(queue_state.get("counts"), dict) else {}
    state["counts"] = _combined_counts(queue_state.get("counts"), current_item)
    state["visible_counts"] = _combined_counts(
        queue_state.get("visible_counts") or queue_state.get("counts"),
        current_item,
    )
    state["total_items"] = int(queue_state.get("total_items") or 0) + (
        1 if current_item is not None else 0
    )
    return state


def _current_task_item(current_job: dict[str, object]) -> dict[str, object] | None:
    status = current_job.get("status")
    if status in {None, "", "idle"}:
        return None
    request = current_job.get("request") if isinstance(current_job.get("request"), dict) else {}
    title = current_job.get("title")
    return {
        "source": "current",
        "job_id": current_job.get("job_id") or "current",
        "status": status,
        "stage": current_job.get("stage") or "preflight",
        "message": current_job.get("message") or "",
        "title": title if isinstance(title, str) and title.strip() else "当前任务",
        "request": dict(request),
        "progress": current_job.get("progress") if isinstance(current_job.get("progress"), list) else [],
        "run_key": current_job.get("run_key"),
        "artifacts": current_job.get("artifacts") if isinstance(current_job.get("artifacts"), dict) else {},
        "warnings": current_job.get("warnings") if isinstance(current_job.get("warnings"), list) else [],
        "friendly_error": current_job.get("friendly_error")
        if isinstance(current_job.get("friendly_error"), dict)
        else None,
        "retry_actions": current_job.get("retry_actions")
        if isinstance(current_job.get("retry_actions"), list)
        else [],
    }


def _combined_counts(
    raw_counts: object,
    current_item: dict[str, object] | None,
) -> dict[str, int]:
    counts = {status: 0 for status in ["queued", "running", "succeeded", "failed", "canceled"]}
    if isinstance(raw_counts, dict):
        for status in counts:
            counts[status] = int(raw_counts.get(status) or 0)
    if current_item is not None:
        status = current_item.get("status")
        if status == "canceling":
            status = "running"
        if isinstance(status, str) and status in counts:
            counts[status] += 1
    return counts
