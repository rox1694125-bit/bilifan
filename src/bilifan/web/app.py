from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from bilifan.bilibili_collection import preview_bilibili_collection
from bilifan.config import default_config_path, read_config, write_consent
from bilifan.exports import ExportError, QualityReviewRequired, write_nabaichuan_jsonl
from bilifan.delivery import successful_delivery
from bilifan.metadata import MetadataIngestError
from bilifan.pipeline import (
    PipelineRequest,
    PipelineRunError,
    run_summarize_pipeline,
    validate_output_format,
)
from bilifan.retry import RETRY_STAGES, RetryError, retry_run
from bilifan.sources import SourceAdapterError, resolve_source_adapter
from bilifan.summarizer import SummarizationError, validate_summary_style

from .files import (
    list_all_runs,
    list_latest_runs,
    list_run_files,
    open_run_folder,
    resolve_run_file,
    resolve_run_dir,
)
from .queue_storage import QueueStorageError
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
    "allow_long_video": True,
}
EXPORT_FILE_PATTERN = re.compile(
    r"nabaichuan_batch_[0-9]{8}_[0-9]{6}_[0-9]{6}(?:\.jsonl|\.report\.json)"
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
    force_article: bool = False
    allow_long_video: bool | None = None
    format: str = WEB_DEFAULTS["format"]
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]


class BatchJobItemPayload(BaseModel):
    url: str
    title: str | None = None


class BatchJobCreatePayload(BaseModel):
    urls: list[str] = Field(default_factory=list)
    items: list[BatchJobItemPayload] = Field(default_factory=list)
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str = WEB_DEFAULTS["language"]
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


class BilibiliCollectionPreviewPayload(BaseModel):
    url: str


class FeishuIntakeSubmittedByPayload(BaseModel):
    display_name: str | None = None


class FeishuIntakeReplyTargetPayload(BaseModel):
    platform: str = "feishu"
    chat_id_ref: str | None = None
    thread_id_ref: str | None = None
    message_id_ref: str | None = None


class FeishuIntakeDefaultsPayload(BaseModel):
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str = WEB_DEFAULTS["language"]
    summary_template: str = WEB_DEFAULTS["summary_template"]
    with_frames: bool = WEB_DEFAULTS["with_frames"]
    with_diagrams: bool = WEB_DEFAULTS["with_diagrams"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


class FeishuIntakePayload(BaseModel):
    source: str = "feishu"
    external_batch_id: str
    submitted_by: FeishuIntakeSubmittedByPayload | None = None
    reply_target: FeishuIntakeReplyTargetPayload | None = None
    urls: list[str]
    defaults: FeishuIntakeDefaultsPayload = Field(
        default_factory=FeishuIntakeDefaultsPayload
    )


def create_app(
    outputs: Path,
    token: str,
    open_browser: bool = True,
    public_url: str | None = None,
    pipeline_runner=run_summarize_pipeline,
    retry_runner=retry_run,
    collection_previewer=preview_bilibili_collection,
    run_jobs_inline: bool = False,
) -> FastAPI:
    auth = TokenAuth(token)
    started_at = datetime.now(timezone.utc).isoformat()
    # Production goes through the supervised executor; test runners remain injectable.
    production = pipeline_runner is run_summarize_pipeline and retry_runner is retry_run and not run_jobs_inline
    queue = BatchQueueManager(
        runner=None if production else pipeline_runner,
        retry_runner=None if production else retry_runner,
        storage_path=outputs / "_jobs" / "jobs.json",
        run_jobs_inline=run_jobs_inline, auto_start=False,
    )
    jobs = queue

    @asynccontextmanager
    async def lifespan(app):
        queue.start()
        try:
            yield
        finally:
            queue.close()

    app = FastAPI(lifespan=lifespan)
    app.state.queue = queue

    @app.exception_handler(QueueStorageError)
    async def storage_error(_request, exc):
        return JSONResponse(status_code=503, content={"detail": str(exc), "storage_error": True})

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

    @app.get("/api/status")
    def status(_: None = Depends(require_token)) -> dict[str, object]:
        current = jobs.current().as_dict()
        return {
            "ok": True,
            "service": "bilifan-web-ui",
            "started_at": started_at,
            "access": {"token": "valid"},
            "entrypoint": {
                "mode": "remote" if public_url else "local",
                "public_url": public_url,
            },
            "current_job": {
                "status": current.get("status") or "idle",
                "stage": current.get("stage") or "preflight",
                "message": current.get("message") or "",
            },
        }

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
            "output_profile": "transcript_article_v1",
            "report_generation_enabled": False,
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
        latest = list_latest_runs(outputs)
        current_keys = {item["run_key"] for item in latest}
        legacy = [item for item in list_all_runs(outputs)
                  if item["run_key"] not in current_keys and item.get("status") == "succeeded"
                  and (item.get("artifacts", {}).get("html") or item.get("artifacts", {}).get("pdf"))]
        return {"items": _add_token_to_artifact_links(latest, token),
                "legacy_reports": _add_token_to_artifact_links(legacy, token)}

    @app.post("/api/bilibili/collection/preview")
    def preview_collection(
        payload: BilibiliCollectionPreviewPayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        _require_local_processing_consent(
            "Local processing consent is required before previewing a Bilibili collection."
        )
        try:
            result = collection_previewer(payload.url, work_dir=outputs)
        except (MetadataIngestError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=500,
                detail="Bilibili collection preview returned invalid data.",
            )
        return result

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
        state = queue.submit_one(request)
        return {"job_id": state.job_id, "status": state.status, "output_profile": "transcript_article_v1",
                "notice": "本版本只生成原始稿和整理逐字稿，旧主报告选项不再执行。"}

    @app.get("/api/jobs/current")
    def current_job(_: None = Depends(require_token)) -> dict[str, object]:
        return jobs.current().as_dict()

    @app.get("/api/jobs/queue")
    def queue_state(_: None = Depends(require_token)) -> dict[str, object]:
        return queue.state()

    @app.post("/api/jobs/batch")
    def create_batch_jobs(
        payload: BatchJobCreatePayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        _require_local_processing_consent(
            "Local processing consent is required before starting a batch."
        )
        batch_items = _batch_items_from_payload(payload)
        if not batch_items:
            raise HTTPException(status_code=400, detail="Batch requires at least one URL.")
        summary_template = _validated_summary_template(payload.summary_template)
        requests = [
            _pipeline_request_from_defaults(
                url=item["url"],
                outputs=outputs,
                defaults=payload,
                summary_template=summary_template,
            )
            for item in batch_items
        ]
        result = queue.submit(requests, titles=[item["title"] for item in batch_items])
        result["notices"] = _legacy_option_notices(payload)
        return result

    @app.post("/api/intake/feishu")
    def create_feishu_intake(
        payload: FeishuIntakePayload,
        _: None = Depends(require_token),
    ) -> dict[str, object]:
        if payload.source != "feishu":
            raise HTTPException(
                status_code=400,
                detail="Only source=feishu is supported.",
            )
        batch_id = payload.external_batch_id.strip()
        if not batch_id:
            raise HTTPException(status_code=400, detail="external_batch_id is required.")
        _require_local_processing_consent(
            "Local processing consent is required before starting a Feishu intake."
        )
        if not payload.urls:
            raise HTTPException(status_code=400, detail="At least one URL is required.")

        summary_template = _validated_summary_template(payload.defaults.summary_template)
        requests: list[PipelineRequest] = []
        origins: list[dict[str, object]] = []
        rejected: list[dict[str, object]] = []
        duplicates: list[dict[str, object]] = []
        seen_video_keys: dict[str, int] = {}

        for index, raw_url in enumerate(payload.urls, start=1):
            url = raw_url.strip()
            if not url:
                rejected.append({"url": "", "index": index, "reason": "empty_url"})
                continue

            try:
                adapter = resolve_source_adapter(url)
                ref = adapter.parse_url(url)
            except (SourceAdapterError, ValueError):
                rejected.append(
                    {"url": url, "index": index, "reason": "unsupported_url"}
                )
                continue

            video_key = f"{ref.platform}:{ref.source_id}:{ref.part_id}"
            first_index = seen_video_keys.get(video_key)
            if first_index is not None:
                duplicates.append(
                    {
                        "url": url,
                        "index": index,
                        "first_index": first_index,
                        "reason": "duplicate_in_batch",
                    }
                )
                continue
            seen_video_keys[video_key] = index

            requests.append(
                _pipeline_request_from_defaults(
                    url=url,
                    outputs=outputs,
                    defaults=payload.defaults,
                    summary_template=summary_template,
                )
            )
            origins.append(
                {
                    "source": "feishu",
                    "label": "来自飞书",
                    "external_batch_id": batch_id,
                    "external_item_id": f"{batch_id}:{index}",
                    "submitted_by": (
                        payload.submitted_by.display_name
                        if payload.submitted_by is not None
                        else None
                    ),
                    "reply_target_ref": _feishu_reply_target_ref(payload.reply_target),
                }
            )

        result = queue.submit_intake_batch(
            batch_id=batch_id,
            requests=requests,
            origins=origins,
            rejected=rejected,
            duplicates=duplicates,
        )
        result["notices"] = _legacy_option_notices(payload.defaults)
        return result

    @app.post("/api/jobs/queue/pause")
    def pause_queue(_: None = Depends(require_token)) -> dict[str, object]:
        return queue.pause()

    @app.post("/api/jobs/queue/resume")
    def resume_queue(_: None = Depends(require_token)) -> dict[str, object]:
        if queue.state().get("execution_error"):
            from bilifan.execution import reconcile_execution, ExecutionBusy, ExecutionUncertain
            try:
                reconcile_execution(outputs)
            except (ExecutionBusy, ExecutionUncertain, OSError) as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
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

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, _: None = Depends(require_token)):
        item = queue.get(job_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Task not found.")
        return item.as_dict()

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

        state = queue.submit_retry(f"{output_id}/runs/{run_id}", {
            "from_stage": from_stage, "output_format": payload.format,
            "llm_provider": payload.llm_provider, "llm_model": payload.llm_model,
            "summary_template": summary_template, "with_frames": payload.with_frames,
            "with_diagrams": payload.with_diagrams, "require_pdf": payload.require_pdf,
            "force_article": payload.force_article,
            "allow_long_video": payload.allow_long_video,
        })
        return {"job_id": state.job_id, "status": state.status}

    @app.post("/api/runs/{output_id}/runs/{run_id}/exports/nabaichuan")
    def export_run_nabaichuan(
        output_id: str,
        run_id: str,
        include_review_required: bool = Query(default=False),
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
        run_key = f"{output_id}/runs/{run_id}"
        try:
            artifact = write_nabaichuan_jsonl(run_dir, run_key=run_key, include_review_required=include_review_required)
        except QualityReviewRequired as exc:
            return JSONResponse(status_code=409, content={"detail": str(exc), "review_required": True, "quality": exc.quality})
        except ExportError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        record_count = _jsonl_record_count(run_dir / artifact)
        return {
            "ok": True,
            "status": "ready",
            "export_id": run_key.replace("/", "-"),
            "run_key": run_key,
            "artifact": f"/api/runs/{output_id}/runs/{run_id}/files/{artifact}",
            "record_count": record_count,
        }

    @app.post("/api/exports/nabaichuan/batch")
    def export_batch_nabaichuan(include_review_required: bool = Query(default=False), _: None = Depends(require_token)) -> dict[str, object]:
        config = read_config(default_config_path())
        if config.local_processing_notice_accepted_at is None:
            raise HTTPException(
                status_code=409,
                detail="Local processing consent is required before exporting runs.",
            )
        export_dir = outputs / "_exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        export_id = datetime.now(timezone.utc).strftime(
            "nabaichuan_batch_%Y%m%d_%H%M%S_%f"
        )
        file_name = f"{export_id}.jsonl"
        report_name = f"{export_id}.report.json"
        output_path = export_dir / file_name
        report_path = export_dir / report_name
        exported_runs = 0
        skipped_runs = 0
        records_written = 0
        lines: list[str] = []
        report_items: list[dict[str, object]] = []
        for item in list_all_runs(outputs):
            run_key = item.get("run_key")
            if item.get("status") != "succeeded":
                skipped_runs += 1
                report_items.append(
                    {
                        "run_key": run_key if isinstance(run_key, str) else "",
                        "status": "skipped",
                        "reason": "run_not_succeeded",
                    }
                )
                continue
            if not isinstance(run_key, str):
                skipped_runs += 1
                report_items.append(
                    {
                        "run_key": "",
                        "status": "skipped",
                        "reason": "missing_run_key",
                    }
                )
                continue
            try:
                output_id, marker, run_id = run_key.split("/")
                if marker != "runs":
                    raise ValueError
                run_dir = resolve_run_dir(outputs, output_id, run_id)
                if not _is_successful_run_dir(run_dir):
                    raise ValueError
                artifact = write_nabaichuan_jsonl(run_dir, run_key=run_key, include_review_required=include_review_required)
                run_lines = (run_dir / artifact).read_text(encoding="utf-8").splitlines()
                lines.extend(run_lines)
            except (ValueError, FileNotFoundError, OSError, ExportError) as exc:
                skipped_runs += 1
                report_items.append(
                    {
                        "run_key": run_key,
                        "status": "skipped",
                        "reason": "quality_review_required" if isinstance(exc, QualityReviewRequired) else type(exc).__name__,
                        "message": str(exc),
                    }
                )
                continue
            exported_runs += 1
            records_written += len(run_lines)
            report_items.append(
                {
                    "run_key": run_key,
                    "status": "exported",
                    "artifact": f"/api/runs/{output_id}/runs/{run_id}/files/{artifact}",
                    "record_count": len(run_lines),
                }
            )
        output_path.write_text(
            "".join(line + "\n" for line in lines),
            encoding="utf-8",
        )
        report_path.write_text(
            json.dumps(
                {
                    "export_id": export_id,
                    "artifact": f"/api/exports/{file_name}",
                    "records_written": records_written,
                    "exported_runs": exported_runs,
                    "skipped_runs": skipped_runs,
                    "items": report_items,
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "ok": True,
            "export_id": export_id,
            "artifact": f"/api/exports/{file_name}",
            "report": f"/api/exports/{report_name}",
            "exported_runs": exported_runs,
            "skipped_runs": skipped_runs,
            "records_written": records_written,
            "items": report_items,
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
        if file_path == "transcript.html":
            content = path.read_text(encoding="utf-8")
            for name in ("transcript.txt", "transcript_source.zip"):
                content = content.replace(f'href="{name}"', f'href="{name}?{urlencode({"token": token})}"')
            return HTMLResponse(content)
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


def _retry_failure_context(
    run_dir: Path, *, diagnostics_path: Path | None = None
) -> tuple[list[str], list[str]]:
    # Read only this attempt's diagnostic; never reuse a prior outcome.
    artifact_paths = [name for name in (
        "metadata.json", "transcript.json", "chunks.json", "transcript_article.json", "chapters.json"
    ) if (run_dir / name).is_file()]
    warnings: list[str] = []
    if diagnostics_path is None:
        return artifact_paths, warnings
    artifact_paths.insert(0, diagnostics_path.name)
    try:
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, ValueError):
        diagnostics = {}
    if isinstance(diagnostics, dict):
        raw_artifacts = diagnostics.get("artifact_paths")
        if isinstance(raw_artifacts, list):
            artifact_paths = [item for item in raw_artifacts if isinstance(item, str)]
            if diagnostics_path.name not in artifact_paths:
                artifact_paths.insert(0, diagnostics_path.name)
        raw_warnings = diagnostics.get("warnings")
        if isinstance(raw_warnings, list):
            warnings = [item for item in raw_warnings if isinstance(item, str)]
    return artifact_paths, warnings


def _legacy_option_notices(payload: BaseModel) -> list[str]:
    if {"summary_template", "with_frames", "with_diagrams"} & payload.model_fields_set:
        return ["旧主报告模板、图解和截图选项已停用，本次只保存原稿并生成整理逐字稿。"]
    return []


def _validated_summary_template(value: str) -> str:
    # Kept solely for older clients; the value is persisted, never executed.
    return str(value)


def _require_local_processing_consent(detail: str) -> None:
    config = read_config(default_config_path())
    if config.local_processing_notice_accepted_at is None:
        raise HTTPException(status_code=409, detail=detail)


def _batch_items_from_payload(payload: BatchJobCreatePayload) -> list[dict[str, str | None]]:
    if payload.items:
        return [
            {
                "url": item.url.strip(),
                "title": item.title.strip() if isinstance(item.title, str) and item.title.strip() else None,
            }
            for item in payload.items
            if item.url.strip()
        ]
    return [
        {"url": url.strip(), "title": None}
        for url in payload.urls
        if url.strip()
    ]


def _pipeline_request_from_defaults(
    *,
    url: str,
    outputs: Path,
    defaults: BatchJobCreatePayload | FeishuIntakeDefaultsPayload,
    summary_template: str,
) -> PipelineRequest:
    return PipelineRequest(
        url=url,
        out=outputs,
        output_format=defaults.format,
        force_whisper=defaults.force_whisper,
        language=defaults.language,
        summary_template=summary_template,
        with_frames=defaults.with_frames,
        with_diagrams=defaults.with_diagrams,
        require_pdf=defaults.require_pdf,
        allow_long_video=defaults.allow_long_video,
        yes_i_understand=True,
        overwrite=False,
    )


def _feishu_reply_target_ref(
    reply_target: FeishuIntakeReplyTargetPayload | None,
) -> str | None:
    if reply_target is None:
        return None
    return (
        reply_target.message_id_ref
        or reply_target.thread_id_ref
        or reply_target.chat_id_ref
    )


def _is_successful_run_dir(run_dir: Path) -> bool:
    return successful_delivery(run_dir)


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


def _jsonl_record_count(path: Path) -> int:
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


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
        "transcript_source_label": current_job.get("transcript_source_label")
        if isinstance(current_job.get("transcript_source_label"), str)
        else "",
        "request": dict(request),
        "progress": current_job.get("progress") if isinstance(current_job.get("progress"), list) else [],
        "elapsed_seconds": float(current_job.get("elapsed_seconds") or 0),
        "stage_elapsed_seconds": float(current_job.get("stage_elapsed_seconds") or 0),
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
