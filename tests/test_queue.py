import json

from bilifan.pipeline import PipelineRequest, PipelineResult
from bilifan.web.queue import BatchQueueManager


def _request(tmp_path, url="https://www.bilibili.com/video/BV1abcDEF12G?p=1"):
    return PipelineRequest(url=url, out=tmp_path / "outputs", yes_i_understand=True)


def test_batch_queue_runs_jobs_sequentially_and_persists_state(tmp_path):
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        progress_callback("metadata", "running", "metadata")
        run_key = f"BV1abcDEF12G_p{len(calls)}/runs/2026-06-08_120000"
        return PipelineResult(
            run_key=run_key,
            run_dir=request.out / run_key,
            diagnostics_path=request.out / run_key / "diagnostics.json",
            artifact_paths=["diagnostics.json", "report.html"],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )

    state = manager.submit(
        [
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
        ]
    )

    assert calls == [
        "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    ]
    assert state["counts"]["succeeded"] == 2
    assert state["items"][0]["status"] == "succeeded"
    assert state["items"][0]["artifacts"]["html"].endswith("/report.html")
    persisted = json.loads((tmp_path / "outputs" / "_jobs" / "jobs.json").read_text())
    assert persisted["jobs"][0]["status"] == "succeeded"


def test_batch_queue_recovers_running_job_as_interrupted(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": False,
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "running",
                        "stage": "audio",
                        "message": "Downloading",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G",
                            "out": str(tmp_path / "outputs"),
                        },
                        "progress": [],
                        "artifacts": {},
                        "warnings": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        run_jobs_inline=True,
    )
    state = manager.state()

    assert state["items"][0]["status"] == "failed"
    assert state["items"][0]["stage"] == "interrupted"
    assert "restarted" in state["items"][0]["message"].lower()


def test_batch_queue_can_pause_cancel_pending_and_retry_failed(tmp_path):
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        raise RuntimeError("boom")

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
        paused=True,
    )
    state = manager.submit([_request(tmp_path)])
    queued_id = state["items"][0]["job_id"]

    canceled = manager.cancel_pending(queued_id)
    assert canceled["items"][0]["status"] == "canceled"
    assert calls == []

    retry_state = manager.retry(queued_id)
    retry_id = retry_state["items"][1]["job_id"]
    assert retry_id != queued_id
    assert retry_state["items"][1]["status"] == "queued"

    resumed = manager.resume()
    assert resumed["items"][1]["status"] == "failed"
    assert calls == ["https://www.bilibili.com/video/BV1abcDEF12G?p=1"]
