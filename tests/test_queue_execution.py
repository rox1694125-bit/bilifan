"""Queue/executor boundary tests use real child processes, never model/network calls."""
import json
import sys
import time
from pathlib import Path

from bilifan import execution
from bilifan.pipeline import PipelineRequest
from bilifan.web.queue import BatchQueueManager


WORKER = r'''
import os,sys,time
from pathlib import Path
from bilifan import execution_worker
from bilifan.execution import ExecutionResult,emit_event,process_table,publish_guard,record_completion

def run(operation, root):
    evidence=Path(operation['evidence']);evidence.mkdir(parents=True,exist_ok=True)
    key='BV1abcDEF12G_p1/runs/2026-09-29_120000'
    (root/key).mkdir(parents=True,exist_ok=True)
    emit_event({'type':'run_created','run_key':key})
    if operation['request']['url'].endswith('=1'):
        (evidence/'first_pid').write_text(str(os.getpid()))
        time.sleep(60)
    old_pid=int((evidence/'first_pid').read_text())
    assert old_pid not in process_table(), 'Next task started while old computation survived'
    (evidence/'second_started').touch()
    directory=root/key;directory.mkdir(parents=True,exist_ok=True)
    result=ExecutionResult(key,directory,directory/'diagnostics.json',['transcript.html'],[])
    with publish_guard():
        (directory/'transcript.html').write_text('finished')
        record_completion(result)
    return result
execution_worker.run_operation=run
raise SystemExit(execution_worker.main_worker(Path(sys.argv[1]),sys.argv[2]))
'''


def wait(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.025)
    raise AssertionError("Timed out waiting for controlled worker")


def test_real_queue_cancel_waits_for_process_exit_before_next_task(tmp_path, monkeypatch):
    worker = tmp_path / "queue_worker.py"
    worker.write_text(WORKER)
    evidence = tmp_path / "evidence"
    original_execute = execution.execute_operation

    def execute(operation, **kwargs):
        return original_execute({**operation, "evidence": str(evidence)}, **kwargs,
                                _worker_command=[sys.executable, str(worker)])

    monkeypatch.setattr(execution, "execute_operation", execute)
    root = tmp_path / "outputs"
    queue = BatchQueueManager(storage_path=root / "_jobs/jobs.json", paused=True)
    try:
        submitted = queue.submit([PipelineRequest(url=f"https://www.bilibili.com/video/BV1abcDEF12G?p={i}", out=root)
                                  for i in (1, 2)])
        first_id, second_id = submitted["submitted_job_ids"]
        queue.resume()
        wait(lambda: (evidence / "first_pid").exists())
        started = time.monotonic()
        queue.cancel(first_id)
        assert queue.get(first_id).status == "canceling"
        wait(lambda: queue.get(first_id).status == "canceled")
        assert time.monotonic() - started < 10
        wait(lambda: queue.get(second_id).status == "succeeded")
        assert (evidence / "second_started").exists()
        assert queue.state()["storage_error"] is None
        assert queue.state()["execution_error"] is None
        disk = json.loads((root / "_jobs/jobs.json").read_text())
        assert [item["status"] for item in disk["jobs"]] == ["canceled", "succeeded"]
    finally:
        queue.close()
