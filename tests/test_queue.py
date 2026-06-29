import json
import threading

import pytest

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


def test_batch_queue_submit_items_omit_empty_origin(tmp_path):
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        paused=True,
    )

    state = manager.submit([_request(tmp_path)])

    assert "origin" not in state["items"][0]


def test_batch_queue_prefers_metadata_part_title_for_completed_job_label(tmp_path):
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

    assert state["items"][0]["title"] == "第一 P"
    persisted = json.loads((tmp_path / "outputs" / "_jobs" / "jobs.json").read_text())
    assert persisted["jobs"][0]["title"] == "第一 P"


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


def test_batch_queue_refreshes_existing_persisted_job_title_from_part_title(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    run_key = "BV1abcDEF12G_p2/runs/2026-06-08_120000"
    run_dir = tmp_path / "outputs" / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(
        json.dumps({"title": "合集标题", "part_title": "第二课"}, ensure_ascii=False),
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
                        "request": {"url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2"},
                        "run_key": run_key,
                        "title": "合集标题",
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

    assert state["items"][0]["title"] == "第二课"
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["title"] == "第二课"


def test_batch_queue_refreshes_existing_persisted_transcript_source_label(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    run_dir = tmp_path / "outputs" / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "transcript.json").write_text(
        json.dumps({"source": "whisper", "model": "turbo"}, ensure_ascii=False),
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
                        "transcript_source_label": "Whisper small.en",
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

    assert state["items"][0]["transcript_source_label"] == "Whisper turbo"
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert persisted["jobs"][0]["transcript_source_label"] == "Whisper turbo"


def test_batch_queue_refreshes_corrected_transcript_source_label(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    run_dir = tmp_path / "outputs" / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "transcript.json").write_text(
        json.dumps(
            {
                "source": "whisper",
                "model": "turbo",
                "transcription_attempts": [
                    {"model": "small.en", "language": "en", "selected": False},
                    {"model": "turbo", "language": "zh", "selected": True},
                ],
                "transcript_quality_check": {"status": "ok"},
            },
            ensure_ascii=False,
        ),
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
                        "transcript_source_label": "Whisper small.en",
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

    assert (
        state["items"][0]["transcript_source_label"]
        == "Whisper turbo · 已自动纠偏"
    )
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert (
        persisted["jobs"][0]["transcript_source_label"]
        == "Whisper turbo · 已自动纠偏"
    )


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


def test_batch_queue_clear_completed_removes_terminal_jobs(tmp_path):
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
    manager.pause()
    queued_job_id = manager.submit(
        [_request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?cancel")]
    )["items"][-1]["job_id"]
    manager.cancel_pending(queued_job_id)
    manager.submit([_request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?queued")])

    state = manager.clear_completed()

    assert state["counts"]["succeeded"] == 0
    assert state["counts"]["failed"] == 0
    assert state["counts"]["canceled"] == 0
    assert state["counts"]["queued"] == 1
    assert [item["status"] for item in state["items"]] == ["queued"]
    persisted = json.loads((tmp_path / "outputs" / "_jobs" / "jobs.json").read_text())
    assert [job["status"] for job in persisted["jobs"]] == ["queued"]


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


def test_intake_batch_persists_origin_metadata_and_replays_idempotent_result(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )
    requests = [
        _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
        _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
    ]
    origins = [
        {"label": "Alpha", "external_item_id": "item-1"},
        {"label": "Beta", "external_item_id": "item-2"},
    ]
    rejected = [{"url": "https://example.com/rejected", "reason": "unsupported"}]
    duplicates = [{"url": "https://example.com/duplicate", "external_item_id": "item-0"}]

    first = manager.submit_intake_batch(
        batch_id="batch-1",
        requests=requests,
        origins=origins,
        rejected=rejected,
        duplicates=duplicates,
    )
    second = manager.submit_intake_batch(
        batch_id="batch-1",
        requests=requests,
        origins=origins,
    )

    assert first["ok"] is True
    assert first["batch_id"] == "batch-1"
    assert first["idempotent"] is False
    assert second["idempotent"] is True
    assert [item["job_id"] for item in second["accepted"]] == [
        item["job_id"] for item in first["accepted"]
    ]
    assert second["rejected"] == rejected
    assert second["duplicates"] == duplicates
    assert first["accepted"] == [
        {
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "job_id": first["accepted"][0]["job_id"],
            "status": "queued",
        },
        {
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
            "job_id": first["accepted"][1]["job_id"],
            "status": "queued",
        },
    ]
    assert first["rejected"] == rejected
    assert first["duplicates"] == duplicates
    assert manager.state()["total_items"] == 2

    reloaded = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )
    items = reloaded.state()["items"]

    assert len(items) == 2
    assert items[0]["origin"]["label"] == "Alpha"
    assert items[0]["origin"]["external_batch_id"] == "batch-1"
    assert items[0]["origin"]["external_item_id"] == "item-1"
    assert items[1]["origin"]["label"] == "Beta"
    assert items[1]["origin"]["external_batch_id"] == "batch-1"
    assert items[1]["origin"]["external_item_id"] == "item-2"

    replayed_after_reload = reloaded.submit_intake_batch(
        batch_id="batch-1",
        requests=requests,
        origins=origins,
    )

    assert replayed_after_reload["idempotent"] is True
    assert [item["job_id"] for item in replayed_after_reload["accepted"]] == [
        item["job_id"] for item in first["accepted"]
    ]
    assert reloaded.state()["total_items"] == 2


def test_intake_batch_run_inline_completes_and_preserves_origin(tmp_path):
    def fake_runner(request, *, progress_callback):
        run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
        return PipelineResult(
            run_key=run_key,
            run_dir=request.out / run_key,
            diagnostics_path=request.out / run_key / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        run_jobs_inline=True,
    )

    manager.submit_intake_batch(
        batch_id="batch-inline",
        requests=[_request(tmp_path)],
        origins=[
            {
                "external_batch_id": "batch-inline",
                "external_item_id": "item-inline",
                "label": "Inline source",
            }
        ],
    )
    state = manager.state()

    assert state["counts"]["succeeded"] == 1
    assert state["items"][0]["status"] == "succeeded"
    assert state["items"][0]["origin"] == {
        "external_batch_id": "batch-inline",
        "external_item_id": "item-inline",
        "label": "Inline source",
    }


def test_intake_batch_existing_replay_starts_persisted_queued_job_inline(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": False,
                "intake_batches": {
                    "batch-replay-start": {
                        "ok": True,
                        "batch_id": "batch-replay-start",
                        "idempotent": False,
                        "accepted": [
                            {
                                "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                                "job_id": "job-replay-start",
                                "status": "queued",
                            }
                        ],
                        "rejected": [],
                        "duplicates": [],
                    }
                },
                "jobs": [
                    {
                        "job_id": "job-replay-start",
                        "status": "queued",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                            "out": str(tmp_path / "outputs"),
                            "yes_i_understand": True,
                        },
                        "origin": {
                            "external_batch_id": "batch-replay-start",
                            "external_item_id": "item-replay-start",
                        },
                        "progress": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    calls = []

    def fake_runner(request, *, progress_callback):
        calls.append(request.url)
        run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
        return PipelineResult(
            run_key=run_key,
            run_dir=request.out / run_key,
            diagnostics_path=request.out / run_key / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=storage_path,
        run_jobs_inline=True,
    )

    replay = manager.submit_intake_batch(
        batch_id="batch-replay-start",
        requests=[_request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1")],
        origins=[
            {
                "external_batch_id": "batch-replay-start",
                "external_item_id": "item-replay-start",
            }
        ],
    )
    state = manager.state()

    assert replay["idempotent"] is True
    assert calls == ["https://www.bilibili.com/video/BV1abcDEF12G?p=1"]
    assert state["counts"]["queued"] == 0
    assert state["counts"]["succeeded"] == 1
    assert state["items"][0]["status"] == "succeeded"


def test_intake_batch_jobs_only_replay_after_batch_index_loss(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )
    first = manager.submit_intake_batch(
        batch_id="batch-index-loss",
        requests=[
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
        ],
        origins=[
            {"label": "Missing external ids"},
            {"label": "Explicit item", "external_item_id": "given-item"},
        ],
    )
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))

    assert persisted["jobs"][0]["origin"]["external_batch_id"] == "batch-index-loss"
    assert persisted["jobs"][0]["origin"]["external_item_id"] == "batch-index-loss:1"
    assert persisted["jobs"][1]["origin"]["external_batch_id"] == "batch-index-loss"
    assert persisted["jobs"][1]["origin"]["external_item_id"] == "given-item"

    persisted.pop("intake_batches")
    storage_path.write_text(json.dumps(persisted), encoding="utf-8")
    reloaded = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )

    replay = reloaded.submit_intake_batch(
        batch_id="batch-index-loss",
        requests=[
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
        ],
        origins=[
            {"label": "Missing external ids"},
            {"label": "Explicit item", "external_item_id": "given-item"},
        ],
    )

    assert replay["idempotent"] is True
    assert [item["job_id"] for item in replay["accepted"]] == [
        item["job_id"] for item in first["accepted"]
    ]
    assert reloaded.state()["total_items"] == 2
    repaired = json.loads(storage_path.read_text(encoding="utf-8"))
    assert "batch-index-loss" in repaired["intake_batches"]


def test_intake_batch_rejects_mismatched_request_and_origin_lengths(tmp_path):
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        paused=True,
    )

    with pytest.raises(ValueError, match="requests and origins must have the same length"):
        manager.submit_intake_batch(
            batch_id="batch-1",
            requests=[_request(tmp_path)],
            origins=[],
        )


def test_retry_job_preserves_origin_metadata(tmp_path):
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        paused=True,
    )
    submitted = manager.submit_intake_batch(
        batch_id="batch-retry",
        requests=[_request(tmp_path)],
        origins=[
            {
                "external_batch_id": "batch-retry",
                "external_item_id": "item-retry",
                "label": "Retry source",
            }
        ],
    )
    job_id = submitted["accepted"][0]["job_id"]

    manager.cancel_pending(job_id)
    retried = manager.retry(job_id)

    assert retried["items"][1]["origin"] == {
        "external_batch_id": "batch-retry",
        "external_item_id": "item-retry",
        "label": "Retry source",
    }


def test_intake_batch_copies_inputs_and_replay_result(tmp_path):
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
        paused=True,
    )
    origins = [
        {
            "external_batch_id": "caller-supplied-wrong-batch",
            "external_item_id": "item-copy",
            "label": "Original",
            "nested": {"value": "kept"},
        }
    ]
    rejected = [{"url": "https://example.com/rejected", "reason": "unsupported"}]
    duplicates = [{"url": "https://example.com/duplicate", "meta": {"source": "sheet"}}]

    first = manager.submit_intake_batch(
        batch_id="batch-copy",
        requests=[_request(tmp_path)],
        origins=origins,
        rejected=rejected,
        duplicates=duplicates,
    )
    original_job_id = first["accepted"][0]["job_id"]
    origins[0]["label"] = "Mutated"
    origins[0]["nested"]["value"] = "changed"
    rejected[0]["reason"] = "changed"
    duplicates[0]["meta"]["source"] = "changed"
    first["accepted"][0]["job_id"] = "mutated-job"
    first["rejected"][0]["reason"] = "mutated"
    first["duplicates"][0]["meta"]["source"] = "mutated"

    replay = manager.submit_intake_batch(
        batch_id="batch-copy",
        requests=[_request(tmp_path)],
        origins=origins,
    )

    assert replay["accepted"][0]["job_id"] == original_job_id
    assert replay["rejected"] == [
        {"url": "https://example.com/rejected", "reason": "unsupported"}
    ]
    assert replay["duplicates"] == [
        {"url": "https://example.com/duplicate", "meta": {"source": "sheet"}}
    ]
    assert manager.state()["items"][0]["origin"] == {
        "external_batch_id": "batch-copy",
        "external_item_id": "item-copy",
        "label": "Original",
        "nested": {"value": "kept"},
    }


def test_intake_batch_replays_from_persisted_jobs_when_batch_index_missing(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": True,
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "queued",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                            "out": str(tmp_path / "outputs"),
                        },
                        "origin": {
                            "external_batch_id": "batch-persisted",
                            "external_item_id": "item-1",
                        },
                        "progress": [],
                    },
                    {
                        "job_id": "job-2",
                        "status": "queued",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
                            "out": str(tmp_path / "outputs"),
                        },
                        "origin": {
                            "external_batch_id": "batch-persisted",
                            "external_item_id": "item-2",
                        },
                        "progress": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )

    replay = manager.submit_intake_batch(
        batch_id="batch-persisted",
        requests=[
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
        ],
        origins=[
            {"external_batch_id": "batch-persisted", "external_item_id": "item-1"},
            {"external_batch_id": "batch-persisted", "external_item_id": "item-2"},
        ],
    )

    assert replay["idempotent"] is True
    assert replay["accepted"] == [
        {
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "job_id": "job-1",
            "status": "queued",
        },
        {
            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
            "job_id": "job-2",
            "status": "queued",
        },
    ]
    assert manager.state()["total_items"] == 2
    persisted = json.loads(storage_path.read_text(encoding="utf-8"))
    assert persisted["intake_batches"]["batch-persisted"]["accepted"] == replay["accepted"]


def test_intake_batch_jobs_only_replay_keeps_accepted_status_queued_for_terminal_jobs(tmp_path):
    storage_path = tmp_path / "outputs" / "_jobs" / "jobs.json"
    storage_path.parent.mkdir(parents=True)
    storage_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "paused": True,
                "jobs": [
                    {
                        "job_id": "job-succeeded",
                        "status": "succeeded",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                            "out": str(tmp_path / "outputs"),
                        },
                        "origin": {
                            "external_batch_id": "batch-terminal",
                            "external_item_id": "item-succeeded",
                        },
                        "progress": [],
                    },
                    {
                        "job_id": "job-failed",
                        "status": "failed",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
                            "out": str(tmp_path / "outputs"),
                        },
                        "origin": {
                            "external_batch_id": "batch-terminal",
                            "external_item_id": "item-failed",
                        },
                        "progress": [],
                    },
                    {
                        "job_id": "job-canceled",
                        "status": "canceled",
                        "request": {
                            "url": "https://www.bilibili.com/video/BV1abcDEF12G?p=3",
                            "out": str(tmp_path / "outputs"),
                        },
                        "origin": {
                            "external_batch_id": "batch-terminal",
                            "external_item_id": "item-canceled",
                        },
                        "progress": [],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = BatchQueueManager(
        runner=lambda request, *, progress_callback: None,
        storage_path=storage_path,
        paused=True,
    )

    replay = manager.submit_intake_batch(
        batch_id="batch-terminal",
        requests=[
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=1"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=2"),
            _request(tmp_path, "https://www.bilibili.com/video/BV1abcDEF12G?p=3"),
        ],
        origins=[
            {"external_batch_id": "batch-terminal", "external_item_id": "item-succeeded"},
            {"external_batch_id": "batch-terminal", "external_item_id": "item-failed"},
            {"external_batch_id": "batch-terminal", "external_item_id": "item-canceled"},
        ],
    )

    assert replay["idempotent"] is True
    assert [item["job_id"] for item in replay["accepted"]] == [
        "job-succeeded",
        "job-failed",
        "job-canceled",
    ]
    assert [item["status"] for item in replay["accepted"]] == ["queued", "queued", "queued"]
    assert manager.state()["total_items"] == 3


def test_worker_exit_window_starts_replacement_for_queued_intake_job(tmp_path):
    class GateLock:
        def __init__(self):
            self._lock = threading.Lock()
            self._guard = threading.Lock()
            self._blocked_thread_id = None
            self.finalizer_waiting = threading.Event()
            self.release_finalizer = threading.Event()

        def block_next_acquire_for_thread(self, thread_id):
            with self._guard:
                self._blocked_thread_id = thread_id

        def acquire(self):
            with self._guard:
                should_block = self._blocked_thread_id == threading.get_ident()
                if should_block:
                    self._blocked_thread_id = None
            if should_block:
                self.finalizer_waiting.set()
                self.release_finalizer.wait(timeout=2)
            self._lock.acquire()
            return True

        def release(self):
            self._lock.release()

        def __enter__(self):
            self.acquire()
            return self

        def __exit__(self, exc_type, exc, tb):
            self.release()

    consumed = threading.Event()

    def fake_runner(request, *, progress_callback):
        consumed.set()
        run_key = "BV1abcDEF12G_p1/runs/2026-06-08_120000"
        return PipelineResult(
            run_key=run_key,
            run_dir=request.out / run_key,
            diagnostics_path=request.out / run_key / "diagnostics.json",
            artifact_paths=[],
            warnings=[],
        )

    manager = BatchQueueManager(
        runner=fake_runner,
        storage_path=tmp_path / "outputs" / "_jobs" / "jobs.json",
    )
    gate_lock = GateLock()
    manager._lock = gate_lock
    original_next_queued = manager._next_queued_locked

    def gated_next_queued():
        job = original_next_queued()
        if job is None:
            gate_lock.block_next_acquire_for_thread(threading.get_ident())
        return job

    manager._next_queued_locked = gated_next_queued

    try:
        manager._start_worker()
        assert gate_lock.finalizer_waiting.wait(timeout=2)

        manager.submit_intake_batch(
            batch_id="batch-race",
            requests=[_request(tmp_path)],
            origins=[{"external_batch_id": "batch-race", "external_item_id": "item-race"}],
        )
        gate_lock.release_finalizer.set()

        assert consumed.wait(timeout=2)
    finally:
        gate_lock.release_finalizer.set()
