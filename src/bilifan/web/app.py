from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

from bilifan.config import default_config_path, read_config, write_consent
from bilifan.pipeline import PipelineRequest, run_summarize_pipeline

from .files import list_latest_runs, list_run_files, resolve_run_file
from .jobs import JobManager
from .security import TokenAuth
from .ui import render_app_html

WEB_DEFAULTS = {
    "format": "html,pdf",
    "force_whisper": False,
    "require_pdf": False,
    "allow_long_video": False,
}


class JobCreatePayload(BaseModel):
    url: str
    format: str = WEB_DEFAULTS["format"]
    force_whisper: bool = WEB_DEFAULTS["force_whisper"]
    require_pdf: bool = WEB_DEFAULTS["require_pdf"]
    allow_long_video: bool = WEB_DEFAULTS["allow_long_video"]


def create_app(
    outputs: Path,
    token: str,
    open_browser: bool = True,
    pipeline_runner=run_summarize_pipeline,
    run_jobs_inline: bool = False,
) -> FastAPI:
    auth = TokenAuth(token)
    jobs = JobManager(runner=pipeline_runner, run_jobs_inline=run_jobs_inline)
    app = FastAPI()

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
        return render_app_html()

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
        return {"items": list_latest_runs(outputs)}

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

    return app
