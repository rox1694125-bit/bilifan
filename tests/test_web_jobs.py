import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from bilifan.pipeline import PipelineResult, PipelineRunError
from bilifan.retry import RetryError, RetryResult
from bilifan.web import files as web_files
from bilifan.web.app import create_app
from bilifan.web.jobs import JobManager, explain_failure


def _headers(token="test-token"):
    return {"X-Bilifan-Token": token}


def _accept_consent(client):
    response = client.post("/api/consent", headers=_headers())
    assert response.status_code == 200


def _wait_for_status(client, status: str, *, timeout: float = 2.0):
    deadline = time.monotonic() + timeout
    state = client.get("/api/jobs/current", headers=_headers()).json()
    while state["status"] != status and time.monotonic() < deadline:
        time.sleep(0.01)
        state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == status
    return state


def _make_run(outputs, output_id="BV1abcDEF12G_p1", run_id="2026-06-08_120000"):
    video_dir = outputs / output_id
    run_dir = video_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (video_dir / "latest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": f"runs/{run_id}",
                "generated_at": "2026-06-08T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (run_dir / "transcript.txt").write_text("plain transcript", encoding="utf-8")
    (run_dir / "transcript.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\ncaption",
        encoding="utf-8",
    )
    (run_dir / "notes.md").write_text("# Notes", encoding="utf-8")
    (run_dir / "content_bundle.json").write_text('{"schema_version":1}', encoding="utf-8")
    (run_dir / "nabaichuan.jsonl").write_text('{"type":"video"}\n', encoding="utf-8")
    (run_dir / "diagnostics.json").write_text(
        json.dumps({"error_type": None, "stage": "render"}),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text('{"title":"Mock title"}', encoding="utf-8")
    partial_dir = run_dir / "partial_summaries"
    partial_dir.mkdir()
    (partial_dir / "chunk_001.json").write_text("{}", encoding="utf-8")
    return run_dir


def test_api_requires_token(tmp_path):
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get("/api/config")

    assert response.status_code == 403


def test_config_and_consent_endpoints(tmp_path, monkeypatch):
    config_home = tmp_path / "config"
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(config_home))
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    before = client.get("/api/config", headers=_headers()).json()
    assert before["consent"]["local_processing"] is False
    assert before["defaults"] == {
        "format": "html,pdf",
        "force_whisper": False,
        "language": "auto",
        "summary_template": "AI 自动判断",
        "with_frames": False,
        "with_diagrams": False,
        "require_pdf": False,
        "allow_long_video": False,
    }

    response = client.post("/api/consent", headers=_headers())
    assert response.status_code == 200

    after = client.get("/api/config", headers=_headers()).json()
    assert after["consent"]["local_processing"] is True
    assert after["consent"]["accepted_via"] == "web-ui"


def test_status_endpoint_reports_remote_entrypoint_and_current_job(tmp_path):
    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        public_url="https://bilifan.buyaoting.top",
    )
    client = TestClient(app)

    response = client.get("/api/status", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["service"] == "bilifan-web-ui"
    assert payload["access"]["token"] == "valid"
    assert payload["entrypoint"] == {
        "mode": "remote",
        "public_url": "https://bilifan.buyaoting.top",
    }
    assert payload["current_job"] == {
        "status": "idle",
        "stage": "preflight",
        "message": "",
    }
    assert isinstance(payload["started_at"], str)


def test_query_token_works_for_config_and_file_route(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    config_response = client.get("/api/config?token=test-token")
    file_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html?token=test-token"
    )

    assert config_response.status_code == 200
    assert file_response.status_code == 200
    assert file_response.text == "<html></html>"


def test_index_embeds_current_service_token(tmp_path):
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert '"test-token"' in response.text


def test_document_responses_send_no_referrer_policy(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    index_response = client.get("/")
    file_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html?token=test-token"
    )

    assert index_response.status_code == 200
    assert index_response.headers["referrer-policy"] == "no-referrer"
    assert index_response.headers["x-content-type-options"] == "nosniff"
    assert file_response.status_code == 200
    assert file_response.headers["referrer-policy"] == "no-referrer"
    assert file_response.headers["x-content-type-options"] == "nosniff"


def test_history_endpoint_returns_direct_artifact_links_with_query_token(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get("/api/history", headers=_headers())

    assert response.status_code == 200
    artifacts = response.json()["items"][0]["artifacts"]
    assert artifacts["html"].endswith("/report.html?token=test-token")
    assert artifacts["diagnostics"].endswith("/diagnostics.json?token=test-token")
    assert artifacts["txt"].endswith("/transcript.txt?token=test-token")
    assert artifacts["srt"].endswith("/transcript.srt?token=test-token")
    assert artifacts["md"].endswith("/notes.md?token=test-token")
    assert artifacts["bundle"].endswith("/content_bundle.json?token=test-token")
    assert artifacts["nabaichuan"].endswith("/nabaichuan.jsonl?token=test-token")
    assert artifacts["folder"].endswith("/open-folder?token=test-token")
    direct_response = client.get(artifacts["html"])
    assert direct_response.status_code == 200
    assert direct_response.text == "<html></html>"


def test_job_success_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request)
        run_dir = request.out / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
        run_dir.mkdir(parents=True)
        (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
        (run_dir / "diagnostics.json").write_text(
            '{"error_type": null, "stage": "render"}',
            encoding="utf-8",
        )
        progress_callback("metadata", "running", "Fetching metadata.")
        progress_callback("metadata", "done", "Metadata written.")
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=[
                "report.html",
                "diagnostics.json",
                "transcript.txt",
                "transcript.srt",
                "notes.md",
                "content_bundle.json",
                "media/audio.mp3",
            ],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "format": "html",
            "force_whisper": False,
            "language": "en",
            "summary_template": "教程步骤",
            "with_frames": True,
            "with_diagrams": True,
            "require_pdf": False,
            "allow_long_video": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == "succeeded"
    assert state["stage"] == "render"
    assert state["message"] == "Report ready."
    assert state["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert state["artifacts"] == {
        "html": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
        "txt": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt",
        "srt": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.srt",
        "md": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/notes.md",
        "bundle": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json",
        "audio": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/media/audio.mp3",
        "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
    }
    assert "job_started_at" in state
    assert "elapsed_seconds" in state
    assert all(item["status"] == "done" for item in state["progress"])
    assert calls[0].output_format == "html"
    assert calls[0].language == "en"
    assert calls[0].summary_template == "教程步骤"
    assert calls[0].with_frames is True
    assert calls[0].with_diagrams is True


def test_single_job_is_visible_in_task_center_queue_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    def fake_pipeline(request, *, progress_callback):
        run_dir = request.out / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps({"title": "单个入口视频标题"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["metadata.json", "report.html"],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    start_response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )
    task_center = client.get("/api/jobs/queue", headers=_headers()).json()

    assert start_response.status_code == 200
    assert task_center["visible_counts"]["succeeded"] == 1
    assert task_center["items"][0]["source"] == "current"
    assert task_center["items"][0]["title"] == "单个入口视频标题"
    assert task_center["items"][0]["request"]["url"] == "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
    assert isinstance(task_center["items"][0]["elapsed_seconds"], float)
    assert isinstance(task_center["items"][0]["stage_elapsed_seconds"], float)


def test_job_payload_uses_web_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request)
        run_dir = request.out / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert calls[0].output_format == "html,pdf"
    assert calls[0].language == "auto"
    assert calls[0].summary_template == "AI 自动判断"
    assert calls[0].with_frames is False
    assert calls[0].with_diagrams is False
    assert calls[0].force_whisper is False
    assert calls[0].require_pdf is False
    assert calls[0].allow_long_video is False


def test_batch_jobs_endpoint_runs_queue_and_persists_state(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request)
        progress_callback("metadata", "running", f"metadata {len(calls)}")
        run_key = f"BV1abcDEF12G_p{len(calls)}/runs/2026-06-08_120000"
        return PipelineResult(
            run_key=run_key,
            run_dir=request.out / run_key,
            diagnostics_path=request.out / run_key / "diagnostics.json",
            artifact_paths=["diagnostics.json", "report.html"],
            warnings=[],
        )

    outputs = tmp_path / "outputs"
    app = create_app(
        outputs=outputs,
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs/batch",
        headers=_headers(),
        json={
            "urls": [
                "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
            ],
            "format": "html",
            "summary_template": "教程步骤",
            "with_diagrams": True,
        },
    )
    queue_state = client.get("/api/jobs/queue", headers=_headers()).json()

    assert response.status_code == 200
    assert [call.url for call in calls] == [
        "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    ]
    assert calls[0].summary_template == "教程步骤"
    assert calls[0].with_diagrams is True
    assert queue_state["counts"]["succeeded"] == 2
    assert queue_state["items"][0]["artifacts"]["html"].endswith("/report.html")
    assert (outputs / "_jobs" / "jobs.json").is_file()


def test_batch_queue_pause_cancel_and_resume_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    calls = []

    def fake_pipeline(request, *, progress_callback):
        calls.append(request.url)
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=request.out / "BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1/runs/2026-06-08_120000/diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    paused = client.post("/api/jobs/queue/pause", headers=_headers())
    queued = client.post(
        "/api/jobs/batch",
        headers=_headers(),
        json={"urls": ["https://www.bilibili.com/video/BV1abcDEF12G?p=1"]},
    ).json()
    job_id = queued["items"][0]["job_id"]
    canceled = client.post(f"/api/jobs/queue/{job_id}/cancel", headers=_headers()).json()
    retry_state = client.post(f"/api/jobs/queue/{job_id}/retry", headers=_headers()).json()
    resumed = client.post("/api/jobs/queue/resume", headers=_headers()).json()

    assert paused.status_code == 200
    assert canceled["items"][0]["status"] == "canceled"
    assert retry_state["items"][1]["status"] == "queued"
    assert resumed["items"][0]["status"] == "succeeded"
    assert resumed["visible_counts"]["canceled"] == 0
    assert resumed["hidden_replaced"] == 1
    assert calls == ["https://www.bilibili.com/video/BV1abcDEF12G?p=1"]


def test_batch_queue_clear_completed_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    def fake_pipeline(request, *, progress_callback):
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=request.out / "BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1/runs/2026-06-08_120000/diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)
    client.post(
        "/api/jobs/batch",
        headers=_headers(),
        json={"urls": ["https://www.bilibili.com/video/BV1abcDEF12G?p=1"]},
    )

    cleared = client.post("/api/jobs/queue/clear-completed", headers=_headers())

    assert cleared.status_code == 200
    assert cleared.json()["counts"]["succeeded"] == 0
    assert cleared.json()["items"] == []


def test_job_requires_local_processing_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 409
    assert "consent" in response.json()["detail"]


def test_running_job_conflict(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    release = threading.Event()
    started = threading.Event()

    def fake_pipeline(request, *, progress_callback):
        progress_callback("metadata", "running", "still running")
        started.set()
        release.wait(timeout=5)
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
            diagnostics_path=tmp_path
            / "outputs"
            / "BV1abcDEF12G_p1"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=False,
    )
    client = TestClient(app)
    _accept_consent(client)

    payload = {
        "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "format": "html",
        "force_whisper": False,
        "require_pdf": False,
        "allow_long_video": False,
    }
    first = client.post("/api/jobs", headers=_headers(), json=payload)
    assert started.wait(timeout=2)
    second = client.post("/api/jobs", headers=_headers(), json=payload)
    release.set()

    assert first.status_code == 200
    assert second.status_code == 409
    _wait_for_status(client, "succeeded")


def test_running_job_can_be_canceled_from_web_api(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    release = threading.Event()
    started = threading.Event()

    def fake_pipeline(request, *, progress_callback):
        progress_callback("audio", "running", "Downloading audio.")
        started.set()
        release.wait(timeout=5)
        progress_callback("audio", "done", "Audio ready.")
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
            diagnostics_path=tmp_path
            / "outputs"
            / "BV1abcDEF12G_p1"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=False,
    )
    client = TestClient(app)
    _accept_consent(client)

    start_response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )
    assert start_response.status_code == 200
    assert started.wait(timeout=2)

    cancel_response = client.post("/api/jobs/current/cancel", headers=_headers())
    state_after_cancel = client.get("/api/jobs/current", headers=_headers()).json()
    release.set()
    final_state = _wait_for_status(client, "canceled")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "canceling"
    assert state_after_cancel["status"] == "canceling"
    assert state_after_cancel["stage"] == "audio"
    assert final_state["status"] == "canceled"
    assert final_state["progress"][2]["status"] == "canceled"
    assert "取消" in final_state["message"]


def test_cancel_current_job_returns_409_when_idle(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post("/api/jobs/current/cancel", headers=_headers())

    assert response.status_code == 409


def test_run_files_endpoint_returns_safe_file_list(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "secret.txt").write_text("hidden", encoding="utf-8")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "files": [
            "content_bundle.json",
            "diagnostics.json",
            "metadata.json",
            "nabaichuan.jsonl",
            "notes.md",
            "report.html",
            "transcript.srt",
            "transcript.txt",
            "partial_summaries/chunk_001.json",
        ]
    }


def test_run_files_endpoint_includes_visible_audio_artifact(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    audio_path = run_dir / "media" / "audio.mp3"
    audio_path.parent.mkdir()
    audio_path.write_bytes(b"audio")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    list_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files",
        headers=_headers(),
    )
    audio_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/media/audio.mp3",
        headers=_headers(),
    )
    hidden_cache_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/.bilifan/cache/audio.mp3",
        headers=_headers(),
    )

    assert list_response.status_code == 200
    assert "media/audio.mp3" in list_response.json()["files"]
    assert audio_response.status_code == 200
    assert audio_response.content == b"audio"
    assert hidden_cache_response.status_code == 400


def test_run_files_endpoint_missing_run_returns_404(tmp_path):
    app = create_app(outputs=tmp_path / "outputs", token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files",
        headers=_headers(),
    )

    assert response.status_code == 404


def test_run_file_endpoint_serves_artifacts_with_token(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    responses = {
        file_path: client.get(
            f"/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/{file_path}",
            headers=_headers(),
        )
        for file_path in [
            "report.html",
            "transcript.txt",
            "transcript.srt",
            "notes.md",
            "content_bundle.json",
            "nabaichuan.jsonl",
        ]
    }

    assert responses["report.html"].status_code == 200
    assert responses["report.html"].text == "<html></html>"
    assert responses["transcript.txt"].status_code == 200
    assert responses["transcript.txt"].text == "plain transcript"
    assert responses["transcript.srt"].status_code == 200
    assert "caption" in responses["transcript.srt"].text
    assert responses["notes.md"].status_code == 200
    assert responses["notes.md"].text == "# Notes"
    assert responses["content_bundle.json"].status_code == 200
    assert "schema_version" in responses["content_bundle.json"].text
    nabaichuan_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl",
        headers=_headers(),
    )
    assert nabaichuan_response.status_code == 200
    assert "video" in nabaichuan_response.text


def test_run_file_endpoint_maps_not_found_and_invalid_paths(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    missing = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.pdf",
        headers=_headers(),
    )
    traversal = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/%2E%2E/secret.txt",
        headers=_headers(),
    )
    non_whitelisted = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/secret.txt",
        headers=_headers(),
    )

    assert missing.status_code == 404
    assert traversal.status_code == 400
    assert non_whitelisted.status_code == 400


def test_run_file_endpoint_rejects_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "transcript.txt"
    outside_file.write_text("outside", encoding="utf-8")
    (run_dir / "transcript.txt").unlink()
    try:
        (run_dir / "transcript.txt").symlink_to(outside_file)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink creation is unsupported on this platform.")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt",
        headers=_headers(),
    )

    assert response.status_code == 400


def test_open_folder_requires_token(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder"
    )

    assert response.status_code == 403


def test_open_folder_on_darwin_calls_open_with_resolved_run_dir(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    calls = []

    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")

    class Result:
        returncode = 0

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr(web_files.subprocess, "run", fake_run)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls == [
        (
            ["open", str(run_dir.resolve())],
            {
                "check": False,
                "capture_output": True,
                "text": True,
                "timeout": 10,
            },
        )
    ]


def test_open_folder_non_darwin_returns_500(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    monkeypatch.setattr(web_files.platform, "system", lambda: "Linux")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 500


def test_open_folder_open_command_failure_returns_500(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    class Result:
        returncode = 1

    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(web_files.subprocess, "run", lambda *args, **kwargs: Result())
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 500


def test_open_folder_open_command_timeout_returns_500(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(
        web_files.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            web_files.subprocess.TimeoutExpired("open", timeout=10)
        ),
    )
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 500


def test_open_folder_missing_run_returns_404(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 404


@pytest.mark.parametrize(
    ("output_id", "run_id"),
    [
        ("not-a-bv", "2026-06-08_120000"),
        ("BV1abcDEF12G_p1", "2026-06-08-120000"),
    ],
)
def test_open_folder_invalid_key_returns_400(tmp_path, monkeypatch, output_id, run_id):
    outputs = tmp_path / "outputs"
    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        f"/api/runs/{output_id}/runs/{run_id}/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 400


def test_open_folder_rejects_run_dir_symlink_escape(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    run_dir.rename(tmp_path / "original-run")
    try:
        run_dir.symlink_to(outside_dir, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink creation is unsupported on this platform.")
    monkeypatch.setattr(web_files.platform, "system", lambda: "Darwin")
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
        headers=_headers(),
    )

    assert response.status_code == 400


def test_job_failure_lifecycle_sanitizes_error_message_and_marks_stage_failed(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    secret = "sk-test-secret-token"

    def fake_pipeline(request, *, progress_callback):
        progress_callback("metadata", "running", "Fetching metadata.")
        raise RuntimeError(f"failed with {secret} at {tmp_path}/cookies.txt")

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "format": "html",
            "force_whisper": False,
            "require_pdf": False,
            "allow_long_video": False,
        },
    )

    assert response.status_code == 200
    state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == "failed"
    assert state["stage"] == "metadata"
    assert state["progress"][1] == {"stage": "metadata", "status": "failed"}
    assert secret not in state["message"]
    assert str(tmp_path) not in state["message"]
    assert "<redacted>" in state["message"] or "<redacted-path>" in state["message"]


def test_job_pipeline_run_error_exposes_diagnostics_link(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    def fake_pipeline(request, *, progress_callback):
        progress_callback("metadata", "running", "Fetching metadata.")
        raise PipelineRunError(
            "metadata failed",
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=["diagnostics.json"],
            warnings=["metadata_failed"],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 200
    state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == "failed"
    assert state["artifacts"] == {
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
        "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
    }
    assert state["warnings"] == ["metadata_failed"]


def test_job_pipeline_run_error_exposes_friendly_error(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))

    def fake_pipeline(request, *, progress_callback):
        progress_callback("summarization", "running", "Summarizing chunks.")
        raise PipelineRunError(
            "codex exec failed to start: [Errno 2] No such file or directory: 'codex'",
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=[
                "diagnostics.json",
                "metadata.json",
                "transcript.json",
                "chunks.json",
            ],
            warnings=["summarization_failed"],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 200
    state = client.get("/api/jobs/current", headers=_headers()).json()
    assert state["status"] == "failed"
    assert state["friendly_error"]["title"] == "Codex CLI 未找到"
    assert "codex" in state["friendly_error"]["cause"].lower()
    assert "Terminal" in state["friendly_error"]["next_action"]
    assert state["retry_actions"] == ["summarization"]


@pytest.mark.parametrize(
    ("stage", "message", "warnings", "title", "next_action_fragment"),
    [
        (
            "audio",
            "Bilibili audio stream download failed.",
            [],
            "音频下载超时或中断",
            "cookies",
        ),
        (
            "media",
            "yt-dlp audio download failed with exit code 1.",
            ["media_failed"],
            "音频下载超时或中断",
            "cookies",
        ),
        (
            "media",
            "playurl API returned no audio streams.",
            ["media_failed"],
            "音频下载超时或中断",
            "cookies",
        ),
        (
            "media",
            "ffprobe failed to read audio duration.",
            ["media_failed"],
            "音频下载超时或中断",
            "cookies",
        ),
        (
            "render",
            "Chrome PDF export timed out after 60s.",
            ["pdf_failed"],
            "PDF 生成失败",
            "必须 PDF",
        ),
        (
            "summarization",
            "codex exec failed with exit code 1: 401 Unauthorized",
            ["summarization_failed"],
            "Codex 账号认证失败",
            "Codex",
        ),
        (
            "summarization",
            "codex exec failed with exit code 1: max tokens exceeded",
            ["summarization_failed"],
            "Codex 总结失败",
            "重试总结",
        ),
        (
            "summarization",
            "Codex CLI executable not found: /bad/codex",
            [],
            "Codex CLI 未找到",
            "Terminal",
        ),
        (
            "transcript",
            "openai-whisper is not installed.",
            ["transcript_failed"],
            "Whisper 未安装",
            "安装",
        ),
        (
            "transcript",
            "Bilibili subtitle download failed and transcript appears incomplete.",
            ["transcript_failed"],
            "逐字稿获取失败",
            "Whisper",
        ),
        (
            "summarization",
            "chunk summary chapter start was not anchored to a transcript segment.",
            [],
            "总结时间戳校验失败",
            "重试总结",
        ),
        (
            "bundle",
            "nabaichuan export failed while writing content bundle.",
            ["pdf_failed", "bundle_failed"],
            "结构化导出失败",
            "HTML/PDF",
        ),
    ],
)
def test_explain_failure_classifies_common_recoverable_failures(
    stage,
    message,
    warnings,
    title,
    next_action_fragment,
):
    explanation = explain_failure(stage=stage, message=message, warnings=warnings)

    assert explanation["title"] == title
    assert next_action_fragment.lower() in explanation["next_action"].lower()


def test_retry_failed_run_from_web_api(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "diagnostics.json").write_text(
        json.dumps({"error_type": "SummarizationError", "stage": "summarization"}),
        encoding="utf-8",
    )
    calls = []

    def fake_retry_runner(
        retry_run_dir,
        *,
        from_stage,
        output_format,
        llm_provider,
        llm_model,
        summary_template,
        with_frames,
        with_diagrams,
        require_pdf,
    ):
        calls.append(
            {
                "run_dir": retry_run_dir,
                "from_stage": from_stage,
                "output_format": output_format,
                "llm_provider": llm_provider,
                "llm_model": llm_model,
                "summary_template": summary_template,
                "with_frames": with_frames,
                "with_diagrams": with_diagrams,
                "require_pdf": require_pdf,
            }
        )
        (retry_run_dir / "report.html").write_text("<html>retried</html>", encoding="utf-8")
        return RetryResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=retry_run_dir,
            diagnostics_path=retry_run_dir / "diagnostics.json",
            artifact_paths=["diagnostics.json", "report.html", "content_bundle.json"],
            warnings=[],
        )

    app = create_app(
        outputs=outputs,
        token="test-token",
        open_browser=False,
        retry_runner=fake_retry_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry",
        headers=_headers(),
        json={
            "from_stage": "summarization",
            "format": "html",
            "summary_template": "观点提炼",
            "with_frames": True,
            "with_diagrams": True,
        },
    )
    state = client.get("/api/jobs/current", headers=_headers()).json()

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert calls == [
        {
            "run_dir": run_dir.resolve(strict=False),
            "from_stage": "summarization",
            "output_format": "html",
            "llm_provider": "codex-exec",
            "llm_model": "gpt-5.5",
            "summary_template": "观点提炼",
            "with_frames": True,
            "with_diagrams": True,
            "require_pdf": False,
        }
    ]
    assert state["status"] == "succeeded"
    assert state["artifacts"]["html"].endswith("/report.html")


def test_retry_requires_local_processing_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry",
        headers=_headers(),
        json={"from_stage": "summarization"},
    )

    assert response.status_code == 409
    assert "consent" in response.json()["detail"]


def test_retry_invalid_stage_returns_400(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry",
        headers=_headers(),
        json={"from_stage": "audio"},
    )

    assert response.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {"from_stage": "summarization", "format": "docx"},
        {"from_stage": "summarization", "llm_provider": "unknown"},
    ],
)
def test_retry_invalid_options_return_400(tmp_path, monkeypatch, payload):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry",
        headers=_headers(),
        json=payload,
    )

    assert response.status_code == 400


def test_retry_failure_preserves_run_context_and_diagnostics_link(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "transcript.json").write_text("{}", encoding="utf-8")
    (run_dir / "chunks.json").write_text("{}", encoding="utf-8")

    def fake_retry_runner(
        retry_run_dir,
        *,
        from_stage,
        output_format,
        llm_provider,
        llm_model,
        summary_template,
        with_frames,
        with_diagrams,
        require_pdf,
    ):
        (retry_run_dir / "diagnostics.json").write_text(
            json.dumps(
                {
                    "error_type": "SummarizationError",
                    "stage": "summarization",
                    "sanitized_message": "codex exec failed",
                    "artifact_paths": [
                        "diagnostics.json",
                        "metadata.json",
                        "transcript.json",
                        "chunks.json",
                    ],
                    "warnings": ["summarization_retry_failed"],
                }
            ),
            encoding="utf-8",
        )
        raise RetryError("codex exec failed")

    app = create_app(
        outputs=outputs,
        token="test-token",
        open_browser=False,
        retry_runner=fake_retry_runner,
        run_jobs_inline=True,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry",
        headers=_headers(),
        json={"from_stage": "summarization"},
    )
    state = client.get("/api/jobs/current", headers=_headers()).json()

    assert response.status_code == 200
    assert state["status"] == "failed"
    assert state["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert state["artifacts"]["diagnostics"].endswith("/diagnostics.json")
    assert state["artifacts"]["folder"].endswith("/open-folder")
    assert state["retry_actions"] == ["summarization"]


def test_export_single_run_nabaichuan_jsonl_from_web_api(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "nabaichuan.jsonl").unlink()
    (run_dir / "content_bundle.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_id": "bilibili:BV1abcDEF12G:p1",
                "source": {
                    "platform": "bilibili",
                    "id": "BV1abcDEF12G",
                    "part_id": "p1",
                    "canonical_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                    "title": "Title",
                },
                "summary": {"chapters": []},
                "transcript": {"segments": []},
            }
        ),
        encoding="utf-8",
    )
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/exports/nabaichuan",
        headers=_headers(),
    )
    file_response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["export_id"] == "BV1abcDEF12G_p1-runs-2026-06-08_120000"
    assert payload["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert payload["record_count"] == 1
    assert payload["artifact"].endswith("/nabaichuan.jsonl")
    assert file_response.status_code == 200
    assert json.loads(file_response.text.splitlines()[0])["type"] == "video"


def test_export_single_run_nabaichuan_rejects_failed_run(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "nabaichuan.jsonl").unlink()
    (run_dir / "diagnostics.json").write_text(
        json.dumps({"error_type": "SummarizationError", "stage": "summarization"}),
        encoding="utf-8",
    )
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/exports/nabaichuan",
        headers=_headers(),
    )

    assert response.status_code == 409
    assert "successful run" in response.json()["detail"]


def test_batch_export_all_successful_history_runs_to_nabaichuan_jsonl(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    outputs = tmp_path / "outputs"
    first = _make_run(outputs, output_id="BV1abcDEF12G_p1", run_id="2026-06-08_120000")
    older_same_output = _make_run(
        outputs,
        output_id="BV1abcDEF12G_p1",
        run_id="2026-06-07_120000",
    )
    second = _make_run(outputs, output_id="BV1abcDEF12H_p1", run_id="2026-06-08_120001")
    failed = _make_run(outputs, output_id="BV1abcDEF12I_p1", run_id="2026-06-08_120002")
    (failed / "diagnostics.json").write_text(
        json.dumps({"error_type": "MetadataIngestError", "stage": "metadata"}),
        encoding="utf-8",
    )
    for run_dir, source_id in [
        (first, "BV1abcDEF12G"),
        (older_same_output, "BV1abcDEF12G"),
        (second, "BV1abcDEF12H"),
    ]:
        (run_dir / "content_bundle.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "bundle_id": f"bilibili:{source_id}:p1",
                    "source": {
                        "platform": "bilibili",
                        "id": source_id,
                        "part_id": "p1",
                        "canonical_url": f"https://www.bilibili.com/video/{source_id}?p=1",
                        "title": source_id,
                    },
                    "summary": {"chapters": []},
                    "transcript": {"segments": []},
                }
            ),
            encoding="utf-8",
        )
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)
    _accept_consent(client)

    response = client.post("/api/exports/nabaichuan/batch", headers=_headers())

    assert response.status_code == 200
    payload = response.json()
    assert payload["export_id"].startswith("nabaichuan_batch_")
    assert payload["exported_runs"] == 3
    assert payload["skipped_runs"] == 1
    assert payload["records_written"] == 3
    assert payload["report"].endswith(".report.json")
    export_response = client.get(payload["artifact"], headers=_headers())
    report_response = client.get(payload["report"], headers=_headers())
    assert export_response.status_code == 200
    assert report_response.status_code == 200
    rows = [json.loads(line) for line in export_response.text.splitlines()]
    report = report_response.json()
    assert report["export_id"] == payload["export_id"]
    assert len(report["items"]) == 4
    assert [item["status"] for item in report["items"]].count("exported") == 3
    assert [item["status"] for item in report["items"]].count("skipped") == 1
    assert sorted(row["source"]["id"] for row in rows) == [
        "BV1abcDEF12G",
        "BV1abcDEF12G",
        "BV1abcDEF12H",
    ]


def test_job_ignores_late_progress_from_previous_job(tmp_path):
    callbacks = []

    def fake_pipeline(request, *, progress_callback):
        callbacks.append(progress_callback)
        progress_callback("metadata", "running", "running")
        return PipelineResult(
            run_key=f"BV1abcDEF12G_p1/runs/2026-06-08_12000{len(callbacks)}",
            run_dir=tmp_path,
            diagnostics_path=tmp_path / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = JobManager(runner=fake_pipeline, run_jobs_inline=True)
    manager.start(object())
    manager.start(object())

    callbacks[0]("metadata", "running", "late first job")

    state = manager.current().as_dict()
    assert state["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120002"
    assert state["message"] == "Report ready."


def test_job_progress_message_is_sanitized(tmp_path, monkeypatch):
    monkeypatch.setenv("BILIFAN_CONFIG_HOME", str(tmp_path / "config"))
    secret = "SESSDATA=secret"
    release = threading.Event()
    started = threading.Event()

    def fake_pipeline(request, *, progress_callback):
        progress_callback("metadata", "running", f"using {secret} at {tmp_path}/cookies.txt")
        started.set()
        release.wait(timeout=5)
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
            diagnostics_path=tmp_path
            / "outputs"
            / "BV1abcDEF12G_p1"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    app = create_app(
        outputs=tmp_path / "outputs",
        token="test-token",
        open_browser=False,
        pipeline_runner=fake_pipeline,
        run_jobs_inline=False,
    )
    client = TestClient(app)
    _accept_consent(client)

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 200
    assert started.wait(timeout=2)
    state = client.get("/api/jobs/current", headers=_headers()).json()
    release.set()
    assert secret not in state["message"]
    assert str(tmp_path) not in state["message"]
    _wait_for_status(client, "succeeded")
