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


def test_batch_queue_uses_metadata_title_for_completed_job_label(tmp_path):
    def fake_runner(request, *, progress_callback):
        run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
        run_dir = request.out / run_key
        run_dir.mkdir(parents=True)
        (run_dir / "metadata.json").write_text(
            json.dumps({"title": "真正的视频标题", "part_title": "第一 P"}, ensure_ascii=False),
            encoding="utf-8",
        )
        return PipelineResult(
            run_key=run_key,
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["metadata.json", "report.html"],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )

    state = manager.submit([_request(tmp_path)])

    assert state["items"][0]["title"] == "真正的视频标题"
    persisted = json.loads((tmp_path / "outputs" / "_jobs" / "jobs.json").read_text())
    assert persisted["jobs"][0]["title"] == "真正的视频标题"


def test_batch_queue_backfills_title_for_existing_persisted_job(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    run_dir = tmp_path / "outputs" / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"title": "历史任务标题"}, ensure_ascii=False),
        encoding="utf-8",
    )
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": False,
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "succeeded",
                        "request": {"url": "https://www.bilibili.com/video/BV1abcDEF12G"},
                        "run_key": run_key,
                        "stage": "render",
                        "progress": [],
                        "artifacts": {},
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

    assert state["items"][0]["title"] == "历史任务标题"
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["title"] == "历史任务标题"


def test_batch_queue_state_shows_only_recent_completed_jobs(tmp_path):
    def fake_runner(request, *, progress_callback):
        run_key = request.url.rsplit("=", 1)[-1]
        return PipelineResult(
            run_key=f"{run_key}/runs/2026-06-08_120000",
            run_dir=request.out / run_key / "runs" / "2026-06-08_120000",
            diagnostics_path=request.out / run_key / "runs" / "2026-06-08_120000" / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )
    state = manager.submit(
        [_request(tmp_path, f"https://www.bilibili.com/video/BV1abcDEF12G?p={index}") for index in range(1, 6)]
    )

    assert state["counts"]["succeeded"] == 5
    assert state["total_items"] == 5
    assert state["hidden_completed"] == 2
    assert [item["request"]["url"] for item in state["items"]] == [
        "https://www.bilibili.com/video/BV1abcDEF12G?p=3",
        "https://www.bilibili.com/video/BV1abcDEF12G?p=4",
        "https://www.bilibili.com/video/BV1abcDEF12G?p=5",
    ]


def test_batch_queue_clear_completed_removes_successful_jobs_only(tmp_path):
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        if request.url.endswith("fail"):
            raise RuntimeError("boom")
        return PipelineResult(
            run_key=f"BV1abcDEF12G_p{len(calls)}/runs/2026-06-08_120000",
            run_dir=request.out / f"BV1abcDEF12G_p{len(calls)}" / "runs" / "2026-06-08_120000",
            diagnostics_path=request.out
            / f"BV1abcDEF12G_p{len(calls)}"
            / "runs"
            / "2026-06-08_120000"
            / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )
    manager.submit(
        [
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?fail"),
        ]
    )

    state = manager.clear_completed()

    assert state["counts"]["succeeded"] == 0
    assert state["counts"]["failed"] == 1
    assert [item["status"] for item in state["items"]] == ["failed"]
    persisted = json.loads((tmp_path / "outputs" / "_jobs" / "jobs.json").read_text())
    assert [job["status"] for job in persisted["jobs"]] == ["failed"]


def test_batch_queue_hides_failed_attempt_after_same_url_retry_succeeds(tmp_path):
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=request.out / "BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1/runs/2026-06-08_120000/diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )
    failed = manager.submit([_request(tmp_path)])
    failed_job_id = failed["items"][0]["job_id"]

    retried = manager.retry(failed_job_id)

    assert retried["counts"]["failed"] == 1
    assert retried["counts"]["succeeded"] == 1
    assert retried["visible_counts"]["failed"] == 0
    assert retried["visible_counts"]["succeeded"] == 1
    assert retried["hidden_replaced"] == 1
    assert [item["status"] for item in retried["items"]] == ["succeeded"]


def test_batch_queue_clear_completed_removes_replaced_failed_attempts(tmp_path):
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return PipelineResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
            run_dir=request.out / "BV1abcDEF12G_p1/runs/2026-06-08_120000",
            diagnostics_path=request.out
            / "BV1abcDEF12G_p1/runs/2026-06-08_120000/diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )
    failed = manager.submit([_request(tmp_path)])
    manager.retry(failed["items"][0]["job_id"])

    cleared = manager.clear_completed()

    assert cleared["counts"]["failed"] == 0
    assert cleared["counts"]["succeeded"] == 0
    assert cleared["items"] == []


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
