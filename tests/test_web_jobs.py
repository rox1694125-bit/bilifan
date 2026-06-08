import json
import threading

from fastapi.testclient import TestClient

from bilifan.pipeline import PipelineResult
from bilifan.web.app import create_app


def _headers(token="test-token"):
    return {"X-Bilifan-Token": token}


def _make_run(outputs, output_id="BV1abcDEF12G_p1", run_id="2026-06-08_120000"):
    run_dir = outputs / output_id / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
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
        "require_pdf": False,
        "allow_long_video": False,
    }

    response = client.post("/api/consent", headers=_headers())
    assert response.status_code == 200

    after = client.get("/api/config", headers=_headers()).json()
    assert after["consent"]["local_processing"] is True
    assert after["consent"]["accepted_via"] == "web-ui"


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


def test_job_success_lifecycle(tmp_path):
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
            artifact_paths=["report.html", "diagnostics.json"],
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
    assert state["status"] == "succeeded"
    assert state["stage"] == "render"
    assert state["message"] == "Report ready."
    assert state["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert state["artifacts"] == {
        "html": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
    }
    assert state["progress"][0] == {"stage": "preflight", "status": "pending"}
    assert calls[0].output_format == "html"


def test_job_payload_uses_web_defaults(tmp_path):
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

    response = client.post(
        "/api/jobs",
        headers=_headers(),
        json={"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert calls[0].output_format == "html,pdf"
    assert calls[0].force_whisper is False
    assert calls[0].require_pdf is False
    assert calls[0].allow_long_video is False


def test_running_job_conflict(tmp_path):
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
            "diagnostics.json",
            "metadata.json",
            "report.html",
            "partial_summaries/chunk_001.json",
        ]
    }


def test_run_file_endpoint_serves_artifact_with_token(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    app = create_app(outputs=outputs, token="test-token", open_browser=False)
    client = TestClient(app)

    response = client.get(
        "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
        headers=_headers(),
    )

    assert response.status_code == 200
    assert response.text == "<html></html>"


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


def test_job_failure_lifecycle_sanitizes_error_message_and_marks_stage_failed(tmp_path):
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


def test_job_progress_message_is_sanitized(tmp_path):
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
