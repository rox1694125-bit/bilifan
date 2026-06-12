from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from bilifan.config import default_config_path, read_config, write_consent
from bilifan.pipeline import (
    PipelineRequest,
    PipelineRunError,
    run_summarize_pipeline,
    validate_output_format,
)
from bilifan.retry import RETRY_STAGES, RetryError, retry_run

from .files import (
    list_latest_runs,
    list_run_files,
    open_run_folder,
    resolve_run_file,
    resolve_run_dir,
)
from .jobs import JobManager
from .security import TokenAuth
from .ui import render_app_html

WEB_DEFAULTS = {
    "format": "html,pdf",
    "force_whisper": False,
    "language": "auto",
    "require_pdf": False,
    "allow_long_video": False,
}


class JobCreatePayload(BaseModel):
    url: str
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    language: str = WEB_DEFAULTS["language"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


class RetryCreatePayload(BaseModel):
    from_stage: str
    format: str = WEB_DEFAULTS["format"]
    llm_provider: str = "codex-exec"
    llm_model: str = "gpt-5.5"
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]


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
        import json

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
