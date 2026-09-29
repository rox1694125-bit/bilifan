import json
import threading
from pathlib import Path

import pytest

from bilifan.pipeline import PipelineRequest, PipelineResult
from bilifan.web.jobs import JobCanceled
from bilifan.web.queue import BatchQueueManager, OUTPUT_PROFILE
from bilifan.web.queue_storage import QueueStorageError, write_completion_receipt


def request(tmp_path, index=1):
    return PipelineRequest(url=f"https://www.bilibili.com/video/BV1abcDEF12G?p={index}",
                           out=tmp_path / "outputs", yes_i_understand=True)


def result(tmp_path, index=1):
    key = f"BV1abcDEF12G_p{index}/runs/2026-09-29_120000"
    run = tmp_path / "outputs" / key
    run.mkdir(parents=True, exist_ok=True)
    (run / "transcript.html").write_text("article")
    return PipelineResult(key, run, run / "diagnostics.json", ["transcript.html"], [])


def manager(tmp_path, **kwargs):
    return BatchQueueManager(storage_path=tmp_path / "outputs/_jobs/jobs.json", **kwargs)


def seed(tmp_path, jobs, **extra):
    path = tmp_path / "outputs/_jobs/jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "paused": False, "jobs": jobs, **extra}))
    return path


def entry(tmp_path, job_id="old-job", status="queued", **extra):
    return {"job_id": job_id, "status": status, "request": {"url": request(tmp_path).url,
            "out": str(tmp_path / "outputs"), "summary_template": "legacy-template"}, **extra}


def test_waiting_jobs_auto_resume_but_paused_queue_stays_paused(tmp_path):
    calls = []
    path = seed(tmp_path, [entry(tmp_path)])
    runner = lambda req, **kw: calls.append(req.url) or result(tmp_path)
    queue = manager(tmp_path, runner=runner, run_jobs_inline=True, auto_start=False)
    assert calls == []
    queue.start()
    assert calls == [request(tmp_path).url]
    assert queue.get("old-job").output_profile == OUTPUT_PROFILE
    assert "升级" in json.loads(path.read_text())["jobs"][0]["warnings"][0]
    assert queue.get("old-job").request["summary_template"] == "legacy-template"
    queue.close()
    seed(tmp_path, [entry(tmp_path)], paused=True)
    queue = manager(tmp_path, runner=runner, run_jobs_inline=True)
    assert queue.state()["counts"]["queued"] == 1
    assert len(calls) == 1
    queue.close()


def test_completion_receipt_reconciles_without_reexecuting(tmp_path):
    completed = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="running", stage="render")])
    write_completion_receipt(tmp_path / "outputs", "old-job", completed)
    calls = []
    queue = manager(tmp_path, runner=lambda req, **kw: calls.append(req), run_jobs_inline=True)
    assert calls == []
    assert queue.get("old-job").status == "succeeded"
    assert queue.get("old-job").run_key == completed.run_key
    queue.close()


def test_receipt_with_missing_artifacts_stops_scheduling(tmp_path):
    completed = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="running"), entry(tmp_path, job_id="next")])
    write_completion_receipt(tmp_path / "outputs", "old-job", completed)
    (completed.run_dir / "transcript.html").unlink()
    calls = []
    queue = manager(tmp_path, runner=lambda req, **kw: calls.append(req), run_jobs_inline=True)
    assert calls == []
    assert queue.state()["paused"]
    assert queue.state()["storage_error"]
    queue.close()


@pytest.mark.parametrize("corrupt", ['{broken', '{"schema_version":2,"jobs":{}}',
                                     '{"schema_version":2,"jobs":[{"job_id":"x","request":{}}]}'])
def test_corruption_is_visible_and_never_overwritten(tmp_path, corrupt):
    path = seed(tmp_path, [])
    path.write_text(corrupt)
    queue = manager(tmp_path, runner=lambda *args: None)
    assert queue.state()["storage_error"]
    assert queue.state()["paused"]
    with pytest.raises(QueueStorageError):
        queue.submit([request(tmp_path)])
    assert path.read_text() == corrupt
    queue.close()


def test_second_writer_cannot_rewrite_or_schedule(tmp_path):
    one = manager(tmp_path, runner=lambda *args: None, paused=True)
    one.submit([request(tmp_path)])
    before = one._storage_path.read_bytes()
    two = manager(tmp_path, runner=lambda *args: pytest.fail("second writer ran"))
    assert two.state()["storage_error"]
    with pytest.raises(QueueStorageError):
        two.submit([request(tmp_path, 2)])
    assert one._storage_path.read_bytes() == before
    two.close()
    one.close()
    three = manager(tmp_path, runner=lambda *args: None, paused=True)
    assert three.state()["storage_error"] is None
    three.close()


def test_submit_and_intake_failure_roll_back_memory_and_idempotency(tmp_path, monkeypatch):
    queue = manager(tmp_path, runner=lambda *args: None, paused=True)
    queue.submit([request(tmp_path)])
    before = queue._storage_path.read_bytes()

    def fail(_):
        raise QueueStorageError("disk full")

    monkeypatch.setattr(queue._store, "save", fail)
    with pytest.raises(QueueStorageError):
        queue.submit_intake_batch(batch_id="not-accepted", requests=[request(tmp_path, 2)], origins=[{}])
    assert queue.state()["total_items"] == 1
    assert "not-accepted" not in queue._intake_batches
    assert queue._storage_path.read_bytes() == before
    assert queue.state()["storage_error"] == "disk full"
    queue.close()


def test_atomic_replace_failure_preserves_previous_ledger_and_good_backup(tmp_path, monkeypatch):
    import bilifan.web.queue_storage as storage
    queue = manager(tmp_path, runner=lambda *args: None, paused=True)
    queue.submit([request(tmp_path)])
    previous = queue._storage_path.read_bytes()
    replace = storage.os.replace

    def fail_main(source, destination):
        if Path(destination) == queue._storage_path:
            raise OSError("disk full during replace")
        return replace(source, destination)

    monkeypatch.setattr(storage.os, "replace", fail_main)
    with pytest.raises(QueueStorageError):
        queue.submit([request(tmp_path, 2)])
    assert queue._storage_path.read_bytes() == previous
    assert queue._store.backup_path.read_bytes() == previous
    assert queue.state()["total_items"] == 1
    assert not list(queue._storage_path.parent.glob("*.tmp"))
    queue.close()


def test_canceling_keeps_slot_until_runner_exits(tmp_path):
    started = threading.Event()
    allow_exit = threading.Event()
    second = threading.Event()

    def run(req, *, cancel_event, **kwargs):
        if req.url.endswith("=1"):
            started.set()
            assert cancel_event.wait(2)
            assert allow_exit.wait(2)
            raise JobCanceled()
        second.set()
        return result(tmp_path, 2)

    queue = manager(tmp_path, runner=run, paused=True)
    state = queue.submit([request(tmp_path), request(tmp_path, 2)])
    queue.resume()
    assert started.wait(2)
    first_id = state["submitted_job_ids"][0]
    queue.cancel(first_id)
    assert queue.get(first_id).status == "canceling"
    assert not second.is_set()
    allow_exit.set()
    assert second.wait(2)
    assert queue.get(first_id).status == "canceled"
    queue.close()


def test_late_cancel_after_publication_records_success(tmp_path):
    started, published = threading.Event(), threading.Event()

    def run(req, **kwargs):
        answer = result(tmp_path)
        started.set()
        assert published.wait(2)
        return answer

    queue = manager(tmp_path, runner=run)
    submitted = queue.submit([request(tmp_path)])
    assert started.wait(2)
    job_id = submitted["submitted_job_ids"][0]
    queue.cancel(job_id)
    published.set()
    queue._thread.join(2)
    assert queue.get(job_id).status == "succeeded"
    assert "到达过晚" in queue.get(job_id).message
    queue.close()


def test_mixed_submit_intake_retry_uses_same_fifo_worker(tmp_path):
    calls = []
    raw = result(tmp_path, 3)
    def run(req, **kw):
        calls.append(req.url)
        return result(tmp_path, 1 if req.url.endswith("=1") else 2)
    def rerun(run_dir, *, from_stage, **kw):
        calls.append((str(run_dir), from_stage))
        return raw
    queue = manager(tmp_path, runner=run, retry_runner=rerun, paused=True, run_jobs_inline=True)
    one = queue.submit_one(request(tmp_path))
    queue.submit_intake_batch(batch_id="b", requests=[request(tmp_path, 2)], origins=[{"label": "Feishu"}])
    retry = queue.submit_retry(raw.run_key, {"from_stage": "summarization"})
    queue.resume()
    assert calls == [request(tmp_path).url, request(tmp_path, 2).url, (str(raw.run_dir), "summarization")]
    assert queue.get(one.job_id).status == "succeeded"
    assert queue.get(retry.job_id).kind == "retry"
    assert queue.state()["counts"]["succeeded"] == 3
    queue.close()


def test_interrupted_raw_transcript_retry_reuses_run_and_preserves_origin(tmp_path):
    original = result(tmp_path)
    (original.run_dir / "transcript.json").write_text('{"segments":[]}')
    seed(tmp_path, [entry(tmp_path, status="running", stage="summarization", run_key=original.run_key,
                         origin={"external_batch_id": "b", "external_item_id": "item"})], paused=True)
    queue = manager(tmp_path, runner=lambda *args: pytest.fail("full pipeline repeated"), paused=True)
    assert queue.get("old-job").interrupted_stage == "summarization"
    state = queue.retry("old-job")
    retry = queue.get(state["submitted_job_ids"][0])
    assert retry.kind == "retry"
    assert retry.run_key == original.run_key
    assert retry.retry_of == "old-job"
    assert retry.options["from_stage"] == "summarization"
    assert retry.origin == queue.get("old-job").origin
    queue.close()


def test_run_event_saved_immediately_and_metrics_visible(tmp_path):
    raw = result(tmp_path)
    def run(req, *, event_callback, **kwargs):
        event_callback({"type": "run_created", "run_key": raw.run_key})
        disk = json.loads((tmp_path / "outputs/_jobs/jobs.json").read_text())
        assert disk["jobs"][0]["run_key"] == raw.run_key
        event_callback({"type": "metrics", "metrics": {"model_calls": 2, "token_usage": None}})
        return raw
    queue = manager(tmp_path, runner=run, run_jobs_inline=True)
    job = queue.submit_one(request(tmp_path))
    assert job.metrics == {"model_calls": 2, "token_usage": None}
    assert job.as_dict()["queue_seconds"] >= 0
    queue.close()


def test_completion_status_write_failure_recovers_from_receipt(tmp_path, monkeypatch):
    queue = manager(tmp_path, runner=lambda req, **kw: result(tmp_path), run_jobs_inline=True)
    original_save = queue._store.save
    def save(payload):
        if payload["jobs"][0]["status"] == "succeeded":
            raise QueueStorageError("status write failed after publication")
        original_save(payload)
    monkeypatch.setattr(queue._store, "save", save)
    job = queue.submit_one(request(tmp_path))
    assert queue.state()["storage_error"]
    queue.close()
    new = manager(tmp_path, runner=lambda req, **kw: pytest.fail("repeat execution"), run_jobs_inline=True)
    assert new.get(job.job_id).status == "succeeded"
    new.close()


def test_normal_retry_does_not_force_new_cache_generation(tmp_path):
    raw = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="failed", kind="retry", run_key=raw.run_key,
                         options={"from_stage": "summarization", "force_article": True})], paused=True)
    queue = manager(tmp_path, runner=lambda *a: None)
    state = queue.retry("old-job")
    recovered = queue.get(state["submitted_job_ids"][0])
    assert recovered.options["force_article"] is False
    assert queue.get("old-job").options["force_article"] is True
    queue.close()


def test_busy_cli_waits_with_backoff_then_resumes_without_user_action(tmp_path, monkeypatch):
    from bilifan import execution
    calls = []
    first = threading.Event()
    done = threading.Event()
    def execute(*args, **kwargs):
        calls.append(__import__("time").monotonic())
        if len(calls) == 1:
            first.set()
            raise execution.ExecutionBusy("CLI owns execution")
        done.set()
        return result(tmp_path)
    monkeypatch.setattr(execution, "execute_operation", execute)
    queue = manager(tmp_path)
    try:
        job = queue.submit_one(request(tmp_path))
        assert first.wait(2)
        assert not queue.state()["paused"]
        assert done.wait(3)
        queue._thread.join(2)
        assert len(calls) == 2
        assert calls[1] - calls[0] >= .45
        assert queue.get(job.job_id).status == "succeeded"
        assert queue.state()["execution_error"] is None
    finally:
        queue.close()


def test_busy_dispatch_and_concurrent_cancel_never_runs_the_job(tmp_path, monkeypatch):
    from bilifan import execution
    dispatching, allow_reply = threading.Event(), threading.Event()
    calls = []
    def execute(*args, **kwargs):
        calls.append(1)
        dispatching.set()
        assert allow_reply.wait(2)
        raise execution.ExecutionBusy("CLI owns execution")
    monkeypatch.setattr(execution, "execute_operation", execute)
    queue = manager(tmp_path)
    try:
        job = queue.submit_one(request(tmp_path))
        assert dispatching.wait(2)
        queue.cancel(job.job_id)
        allow_reply.set()
        queue._thread.join(2)
        assert queue.get(job.job_id).status == "canceled"
        assert calls == [1]
    finally:
        allow_reply.set()
        queue.close()


@pytest.mark.parametrize("identity", ["old-job", "unrelated-previous-attempt"])
def test_completion_marker_fills_receipt_gap_only_for_matching_job(tmp_path, identity):
    from test_retry import _run_dir
    from bilifan.retry import retry_run
    run = _run_dir(tmp_path)
    retry_run(run, from_stage="render", output_format="html")
    marker = json.loads((run / "completion.json").read_text())
    marker["execution"] = {"job_id": identity, "nonce": "owned-execution-nonce"}
    (run / "completion.json").write_text(json.dumps(marker))
    key = str(run.relative_to(tmp_path / "outputs"))
    (run.parent.parent / "latest.json").unlink()
    seed(tmp_path, [entry(tmp_path, status="running", run_key=key, stage="render")])
    calls = []
    queue = manager(tmp_path, runner=lambda req, **kw: calls.append(req), run_jobs_inline=True)
    assert queue.state()["storage_error"] is None
    assert queue.get("old-job").status == ("succeeded" if identity == "old-job" else "interrupted")
    assert (run.parent.parent / "latest.json").exists() == (identity == "old-job")
    assert calls == []
    queue.close()


def test_marker_fallback_rejects_matching_job_with_changed_published_bytes(tmp_path):
    from test_retry import _run_dir
    from bilifan.retry import retry_run
    run = _run_dir(tmp_path)
    retry_run(run, from_stage="render", output_format="html")
    marker = json.loads((run / "completion.json").read_text())
    marker["execution"] = {"job_id": "old-job", "nonce": "owned-execution-nonce"}
    (run / "completion.json").write_text(json.dumps(marker))
    (run / "transcript.html").write_text("changed content")
    key = str(run.relative_to(tmp_path / "outputs"))
    seed(tmp_path, [entry(tmp_path, status="running", run_key=key)])
    queue = manager(tmp_path, runner=lambda *a: pytest.fail("must not execute"))
    assert queue.state()["storage_error"]
    assert queue.state()["paused"]
    queue.close()


def test_confirmed_cancel_finalizes_only_the_job_attempt(tmp_path):
    from bilifan.article_cache import sidecar_directory
    raw = result(tmp_path)
    attempt = "a" * 32
    other = "b" * 32
    base = sidecar_directory(raw.run_dir) / "attempts"
    base.mkdir(parents=True)
    for ident in (attempt, other):
        (base / f"{ident}.json").write_text(json.dumps({
            "schema_version": 1, "attempt_id": ident, "status": "running",
            "started_at": "2026-09-29T00:00:00+00:00", "stages": {},
            "model_calls": 1, "model_failures": 0, "inflight_calls": {"c": {}},
            "usage": {"input_tokens": None},
        }))
    def run(req, *, event_callback, **kwargs):
        event_callback({"type": "run_created", "run_key": raw.run_key})
        event_callback({"type": "metrics", "metrics": {"attempt_id": attempt}})
        raise JobCanceled()
    queue = manager(tmp_path, runner=run, run_jobs_inline=True)
    job = queue.submit_one(request(tmp_path))
    assert job.status == "canceled"
    assert job.metrics["status"] == "canceled"
    assert job.metrics["model_calls"] == job.metrics["model_failures"] == 1
    assert job.metrics["usage"]["input_tokens"] is None
    assert json.loads((base / f"{other}.json").read_text())["status"] == "running"
    queue.close()


@pytest.mark.parametrize("has_current_diagnostic", [True, False])
def test_retry_failure_uses_only_this_attempt_diagnostic(tmp_path, has_current_diagnostic):
    from bilifan.retry import RetryError
    raw = result(tmp_path)
    (raw.run_dir / "transcript.json").write_text('{}')
    (raw.run_dir / "transcript.txt").write_text('original raw')
    (raw.run_dir / "report.html").write_text('old successful report')
    (raw.run_dir / "diagnostics.json").write_text(json.dumps({"artifact_paths": ["report.html"], "warnings": ["stale_warning"]}))
    diagnostic = raw.run_dir / "retry_diagnostics.json"
    def fail(run_dir, **kwargs):
        if has_current_diagnostic:
            diagnostic.write_text(json.dumps({"artifact_paths": ["transcript.txt"], "warnings": ["current_warning"]}))
        raise RetryError("this retry failed", diagnostics_path=diagnostic if has_current_diagnostic else None)
    queue = manager(tmp_path, retry_runner=fail, run_jobs_inline=True)
    job = queue.submit_retry(raw.run_key, {"from_stage": "summarization"})
    assert job.status == "failed"
    assert job.run_key == raw.run_key
    assert job.warnings == (["current_warning"] if has_current_diagnostic else [])
    assert not any(value.endswith("/report.html") for value in job.artifacts.values())
    assert any(value.endswith("/transcript.txt") for value in job.artifacts.values())
    queue.close()


def test_queue_quality_reads_saved_projection_once_and_missing_is_unknown(tmp_path, monkeypatch):
    raw = result(tmp_path)
    quality = {"status": "needs_review", "review_required": True, "reasons": [{"code": "fixture"}]}
    (raw.run_dir / "quality.json").write_text(json.dumps(quality))
    queue = manager(tmp_path, runner=lambda req, **kw: raw, run_jobs_inline=True)
    job = queue.submit_one(request(tmp_path))
    assert job.quality == quality
    import bilifan.web.queue as module
    monkeypatch.setattr(module, "_read_quality", lambda _: pytest.fail("state polling recalculated quality"))
    assert queue.state()["items"][0]["quality"] == quality
    assert queue.get(job.job_id).quality == quality
    queue.close()


@pytest.mark.parametrize("pointer_failure", [False, True])
def test_valid_completion_receipt_repairs_latest_gap_or_stops_on_write_failure(tmp_path, monkeypatch, pointer_failure):
    from test_retry import _run_dir
    from bilifan.retry import retry_run
    from bilifan import delivery
    run = _run_dir(tmp_path)
    completed = retry_run(run, from_stage="render", output_format="html")
    write_completion_receipt(tmp_path / "outputs", "old-job", completed)
    (run.parent.parent / "latest.json").unlink()
    seed(tmp_path, [entry(tmp_path, status="running", run_key=completed.run_key)])
    if pointer_failure:
        def fail(_):
            raise OSError("disk full")
        monkeypatch.setattr(delivery, "promote_latest", fail)
    queue = manager(tmp_path, runner=lambda *a, **kw: pytest.fail("completion was already published"), run_jobs_inline=True)
    if pointer_failure:
        assert queue.state()["storage_error"]
        assert queue.state()["paused"]
        assert not (run.parent.parent / "latest.json").exists()
    else:
        assert queue.get("old-job").status == "succeeded"
        assert json.loads((run.parent.parent / "latest.json").read_text())["run_id"] == run.name
    queue.close()


@pytest.mark.parametrize("status", ["running", "canceling"])
def test_run_created_binding_survives_before_parent_receives_ipc(tmp_path, status):
    from bilifan.web.queue_storage import write_run_link
    raw = result(tmp_path)
    (raw.run_dir / "transcript.json").write_text('{"segments":[]}')
    (raw.run_dir / "transcript.txt").write_text('raw transcript preserved')
    seed(tmp_path, [entry(tmp_path, status=status, stage="transcript")])
    write_run_link(tmp_path / "outputs", "old-job", nonce="worker-before-ipc", run_key=raw.run_key)
    queue = manager(tmp_path, runner=lambda *args, **kw: pytest.fail("must not restart whole processing"), run_jobs_inline=True)
    job = queue.get("old-job")
    assert job.status == "interrupted"
    assert job.run_key == raw.run_key
    assert job.interrupted_stage == "transcript"
    assert job.retry_actions == ["summarization"]
    assert job.artifacts["raw"].endswith("/transcript.txt")
    queue.close()


def test_run_binding_then_completion_receipt_recovers_without_run_key_in_ledger(tmp_path):
    from bilifan.web.queue_storage import write_run_link
    raw = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="running")])
    write_run_link(tmp_path / "outputs", "old-job", nonce="worker-before-ipc", run_key=raw.run_key)
    write_completion_receipt(tmp_path / "outputs", "old-job", raw)
    queue = manager(tmp_path, runner=lambda *args, **kw: pytest.fail("must not repeat completed task"), run_jobs_inline=True)
    assert queue.get("old-job").status == "succeeded"
    assert queue.get("old-job").run_key == raw.run_key
    queue.close()


def test_terminal_job_is_not_overwritten_by_a_late_run_binding(tmp_path):
    from bilifan.web.queue_storage import write_run_link
    raw = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="canceled")])
    write_run_link(tmp_path / "outputs", "old-job", nonce="late-worker", run_key=raw.run_key)
    queue = manager(tmp_path, runner=lambda *args, **kw: pytest.fail("must not restart terminal task"), run_jobs_inline=True)
    assert queue.get("old-job").status == "canceled"
    assert queue.get("old-job").run_key is None
    queue.close()


@pytest.mark.parametrize("invalid", ["different_job", "escape", "missing_directory", "bad_json"])
def test_invalid_run_binding_halts_recovery_without_guessing_a_directory(tmp_path, invalid):
    raw = result(tmp_path)
    seed(tmp_path, [entry(tmp_path, status="running")])
    links = tmp_path / "outputs/_jobs/run_links"
    links.mkdir()
    value = {"schema_version": 1, "job_id": "old-job", "nonce": "nonce", "run_key": raw.run_key}
    if invalid == "different_job":
        value["job_id"] = "different-job"
    elif invalid == "escape":
        value["run_key"] = "../outside"
    elif invalid == "missing_directory":
        value["run_key"] = "missing/runs/2026-09-29_120000"
    (links / "old-job.json").write_text("{broken" if invalid == "bad_json" else json.dumps(value))
    queue = manager(tmp_path, runner=lambda *args, **kw: pytest.fail("untrusted binding must stop"), run_jobs_inline=True)
    assert queue.state()["storage_error"]
    assert queue.state()["paused"]
    assert (raw.run_dir / "transcript.html").exists()
    queue.close()


def test_run_binding_is_idempotent_and_cannot_rebind_job(tmp_path):
    from bilifan.web.queue_storage import write_run_link, read_run_link
    raw = result(tmp_path)
    root = tmp_path / "outputs"
    write_run_link(root, "job", nonce="first", run_key=raw.run_key)
    write_run_link(root, "job", nonce="first", run_key=raw.run_key)
    with pytest.raises(ValueError, match="rebind"):
        write_run_link(root, "job", nonce="second", run_key=raw.run_key)
    assert read_run_link(root, "job")["nonce"] == "first"


def test_uncertain_supervisor_recovers_child_binding_before_persisting_interrupted(tmp_path, monkeypatch):
    from bilifan import execution
    from bilifan.web.queue_storage import write_run_link
    raw = result(tmp_path)
    (raw.run_dir / "transcript.json").write_text('{"segments":[]}')
    (raw.run_dir / "transcript.txt").write_text('preserved before lost IPC')
    def die_before_ipc(operation, *, job_id, outputs_root, **kwargs):
        write_run_link(outputs_root, job_id, nonce="worker-before-lost-ipc", run_key=raw.run_key)
        raise execution.ExecutionUncertain("supervisor died before forwarding run_created")
    monkeypatch.setattr(execution, "execute_operation", die_before_ipc)
    queue = manager(tmp_path, run_jobs_inline=True)
    job = queue.submit_one(request(tmp_path))
    assert job.status == "interrupted"
    assert job.run_key == raw.run_key
    assert job.retry_actions == ["summarization"]
    assert job.artifacts["raw"].endswith("transcript.txt")
    disk = json.loads(queue._storage_path.read_text())["jobs"][0]
    assert disk["run_key"] == raw.run_key
    assert queue.state()["paused"]
    queue.close()


def test_previously_interrupted_missing_run_key_is_repaired_from_own_binding(tmp_path):
    from bilifan.web.queue_storage import write_run_link
    raw = result(tmp_path)
    (raw.run_dir / "transcript.json").write_text('{"segments":[]}')
    seed(tmp_path, [entry(tmp_path, status="interrupted", stage="interrupted")], paused=True)
    write_run_link(tmp_path / "outputs", "old-job", nonce="lost-ipc", run_key=raw.run_key)
    queue = manager(tmp_path, runner=lambda *a, **kw: pytest.fail("must wait for explicit recovery"))
    assert queue.get("old-job").status == "interrupted"
    assert queue.get("old-job").run_key == raw.run_key
    assert queue.get("old-job").retry_actions == ["summarization"]
    queue.close()


@pytest.mark.parametrize("mismatch", ["nonce", "run_key"])
def test_marker_fallback_rejects_mismatched_durable_execution_binding(tmp_path, mismatch):
    from test_retry import _run_dir
    from bilifan.retry import retry_run
    from bilifan.web.queue_storage import read_completion_receipt, write_run_link
    run = _run_dir(tmp_path)
    completed = retry_run(run, from_stage="render", output_format="html")
    marker = json.loads((run / "completion.json").read_text())
    marker["execution"] = {"job_id": "old-job", "nonce": "published-nonce"}
    (run / "completion.json").write_text(json.dumps(marker))
    key = completed.run_key
    if mismatch == "run_key":
        other = result(tmp_path, 2)
        key = other.run_key
    write_run_link(tmp_path / "outputs", "old-job", nonce="different-nonce" if mismatch == "nonce" else "published-nonce", run_key=key)
    with pytest.raises(QueueStorageError, match="绑定不一致"):
        read_completion_receipt(tmp_path / "outputs", "old-job", run_key=completed.run_key)


def test_migration_does_not_relabel_historical_outcomes_as_new_article_deliveries(tmp_path):
    seed(tmp_path, [entry(tmp_path, job_id=f"old-{status}", status=status)
                    for status in ("succeeded", "failed", "canceled", "queued")], paused=True)
    queue = manager(tmp_path, paused=True)
    for status in ("succeeded", "failed", "canceled"):
        assert queue.get(f"old-{status}").output_profile == "legacy_report"
        assert queue.get(f"old-{status}").status == status
    assert queue.get("old-queued").output_profile == "transcript_article_v1"
    queue.close()


def test_canceled_task_exposes_preserved_original_without_claiming_delivery(tmp_path):
    from bilifan.execution import OperationCanceled
    saved = result(tmp_path)
    (saved.run_dir / "transcript.json").write_text('{"segments":[]}')
    (saved.run_dir / "transcript.txt").write_text('原始转录保留')
    entered = threading.Event()
    def run(req, *, event_callback, cancel_event, **kwargs):
        event_callback({"type": "run_created", "run_key": saved.run_key})
        entered.set()
        assert cancel_event.wait(2)
        raise OperationCanceled("fixture stopped")
    queue = manager(tmp_path, runner=run)
    item = queue.submit_one(request(tmp_path))
    assert entered.wait(2)
    queue.cancel(item.job_id)
    queue.close(timeout=2)
    canceled = queue.get(item.job_id)
    assert canceled.status == "canceled"
    assert canceled.artifacts["raw"].endswith('/files/transcript.txt')
    assert canceled.retry_actions == ["summarization"]
    assert "html" not in canceled.artifacts and "transcript_html" not in canceled.artifacts
    queue.close()
