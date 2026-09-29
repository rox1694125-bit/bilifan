from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from bilifan.execution import (
    ExecutionBusy, ExecutionUncertain, OperationCanceled, _acquire_lock,
    cancellable_run, execute_operation, execution_lock, process_identity,
    process_table, reconcile_execution,
)


WORKER = r'''
import json, os, signal, subprocess, sys, time
from pathlib import Path
from bilifan import execution_worker
from bilifan.execution import ExecutionResult, atomic_json, cancellable_run, emit_event, publish_guard, record_completion

def fake(operation, root):
    mode = operation['mode']
    state = Path(operation['evidence'])
    state.mkdir(exist_ok=True, parents=True)
    (root/'video/runs/2026-09-29_000000').mkdir(parents=True,exist_ok=True)
    emit_event({'type':'run_created','run_key':'video/runs/2026-09-29_000000'})
    (state/'worker_pid').write_text(str(os.getpid()))
    if mode in ('hang', 'stubborn', 'escaped'):
        code = "import os,signal,subprocess,sys,time; from pathlib import Path; p=Path(sys.argv[1]); (p/'command_pid').write_text(str(os.getpid())); "
        if mode == 'stubborn':
            code += "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        grandchild = "import os,signal,sys,time; from pathlib import Path; signal.signal(signal.SIGTERM,signal.SIG_IGN); Path(sys.argv[1]).write_text(str(os.getpid())); time.sleep(60)"
        code += "subprocess.Popen([sys.executable,'-c'," + repr(grandchild) + ",str(p/'grandchild_pid')],close_fds=False,start_new_session=" + str(mode == 'escaped') + "); time.sleep(60)"
        cancellable_run([sys.executable,'-c',code,str(state)],capture_output=True,text=True)
    if mode == 'python_hang':
        time.sleep(60)
    if mode == 'failure':
        raise ValueError('fixture failed')
    if mode in ('retry_fresh','retry_without_diagnostic'):
        from bilifan.retry import RetryError
        run=root/'video/runs/2026-09-29_000000';run.mkdir(parents=True,exist_ok=True)
        (run/'diagnostics.json').write_text(json.dumps({'artifact_paths':['old.html'],'warnings':['old']}))
        fresh=run/'retry_diagnostics.json'
        fresh.write_text(json.dumps({'artifact_paths':['transcript.txt'],'warnings':['original_saved']}))
        raise RetryError('fixture retry failed',diagnostics_path=fresh if mode=='retry_fresh' else None)
    run = root/'video/runs/2026-09-29_000000'
    run.mkdir(parents=True,exist_ok=True)
    result = ExecutionResult('video/runs/2026-09-29_000000',run,run/'diagnostics.json',['transcript.html'],[])
    with publish_guard():
        (state/'publishing').touch()
        if mode == 'publish':
            time.sleep(0.5)
        (run/'transcript.html').write_text('published')
        (run/'diagnostics.json').write_text('{}')
        if mode == 'receipt_fail':
            from bilifan.web import queue_storage
            def fail(*args):
                raise OSError('fixture disk full')
            queue_storage.write_completion_receipt = fail
        record_completion(result)
        if mode == 'crash_after_receipt':
            os._exit(0)
    return result
execution_worker.run_operation = fake
raise SystemExit(execution_worker.main_worker(Path(sys.argv[1]),sys.argv[2]))
'''


@pytest.fixture
def worker_file(tmp_path):
    path = tmp_path / 'fake_worker.py'
    path.write_text(WORKER)
    yield path
    # Only process groups captured by this test's nonce-bound owner records.
    for owner_path in tmp_path.glob('outputs/_execution/*/owner.json'):
        owner = json.loads(owner_path.read_text())
        pid = owner.get('worker_pid')
        if pid:
            table = process_table()
            if any(info['pgid'] == pid for info in table.values()):
                try:
                    os.killpg(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.03)
    raise AssertionError('condition was not met')


def start_operation(tmp_path, worker_file, mode, *, operation_extra=None):
    event = threading.Event()
    values = {}
    evidence = tmp_path / 'evidence'
    root = tmp_path / 'outputs'
    def run():
        try:
            values['result'] = execute_operation({'kind':'fixture','mode':mode,'evidence':str(evidence),**(operation_extra or {})},outputs_root=root,progress_callback=lambda *a:None,event_callback=lambda value:values.setdefault('events',[]).append(value),cancel_event=event,job_id='job_test',_worker_command=[sys.executable,str(worker_file)])
        except BaseException as exc:
            values['error'] = exc
    thread = threading.Thread(target=run)
    thread.start()
    return thread,event,values,evidence,root


def test_success_receipt_and_run_created_are_durable(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'success')
    thread.join(10)
    assert not thread.is_alive()
    assert 'error' not in values, values
    assert values['events'][0]['type'] == 'run_created'
    assert values['result'].run_dir.joinpath('transcript.html').is_file()
    receipt = json.loads((root/'_jobs/receipts/job_test.json').read_text())
    assert receipt['run_key'] == values['result'].run_key
    assert json.loads((root/'_execution/claim.json').read_text())['status'] == 'completed'
    with execution_lock(root):
        pass


@pytest.mark.parametrize("attempt", range(2))
def test_cancel_stubborn_child_and_grandchild_before_return(tmp_path, worker_file, attempt):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'stubborn')
    wait_for(lambda:(evidence/'grandchild_pid').exists())
    pids = [int((evidence/name).read_text()) for name in ('worker_pid','command_pid','grandchild_pid')]
    started = time.monotonic()
    event.set()
    thread.join(10)
    assert not thread.is_alive()
    assert isinstance(values.get('error'),OperationCanceled), values
    assert time.monotonic()-started < 10
    table = process_table()
    assert not set(pids).intersection(table)
    assert not (root/'video/runs/2026-09-29_000000/transcript.html').exists()
    with execution_lock(root):
        pass


def test_cancel_python_hang(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'python_hang')
    wait_for(lambda:(evidence/'worker_pid').exists())
    event.set()
    thread.join(10)
    assert not thread.is_alive()
    assert isinstance(values.get('error'),OperationCanceled),values


def test_cancel_during_publication_finishes_and_keeps_receipt(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'publish')
    wait_for(lambda:(evidence/'publishing').exists())
    event.set()
    thread.join(10)
    assert not thread.is_alive()
    assert 'error' not in values,values
    assert values['result'].run_dir.joinpath('transcript.html').read_text() == 'published'
    assert (root/'_jobs/receipts/job_test.json').is_file()


def test_cli_and_worker_compete_for_the_same_lock(tmp_path, worker_file):
    root = tmp_path/'outputs'
    with execution_lock(root):
        thread,event,values,evidence,_ = start_operation(tmp_path,worker_file,'success')
        thread.join(10)
        assert isinstance(values.get('error'),ExecutionBusy),values
        assert not evidence.exists()


def test_parent_eof_terminates_descendants(tmp_path, worker_file):
    evidence,root = tmp_path/'evidence',tmp_path/'outputs'
    client = tmp_path/'client.py'
    client.write_text('import sys,threading\nfrom pathlib import Path\nfrom bilifan.execution import execute_operation\nexecute_operation({"mode":"stubborn","evidence":sys.argv[2]},outputs_root=Path(sys.argv[1]),progress_callback=lambda *a:None,event_callback=lambda e:None,cancel_event=threading.Event(),job_id="eof",_worker_command=[sys.executable,sys.argv[3]])\n')
    parent = subprocess.Popen([sys.executable,str(client),str(root),str(evidence),str(worker_file)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        wait_for(lambda:(evidence/'grandchild_pid').exists())
        pids = [int((evidence/name).read_text()) for name in ('worker_pid','command_pid','grandchild_pid')]
        parent.kill()
        parent.wait(timeout=2)
        wait_for(lambda:not set(pids).intersection(process_table()),timeout=10)
        wait_for(lambda:json.loads((root/'_execution/claim.json').read_text()).get('status')=='canceled')
        with execution_lock(root):
            pass
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=2)


def test_supervisor_death_never_releases_a_live_descendant_lease(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'stubborn')
    wait_for(lambda:(evidence/'grandchild_pid').exists())
    owner = json.loads(next((root/'_execution').glob('*/owner.json')).read_text())
    assert process_identity(owner['pid']) == owner['identity']
    os.kill(owner['pid'],signal.SIGKILL)
    thread.join(3)
    assert not thread.is_alive()
    assert isinstance(values.get('error'),ExecutionUncertain),values
    # Either the inherited kernel lease is live or the unresolved nonce claim
    # rejects dispatch. In neither case may a replacement start computing.
    with pytest.raises((ExecutionBusy,ExecutionUncertain)):
        with execution_lock(root):
            pytest.fail('a replacement acquired an unresolved execution')


def test_unresolved_claim_fails_closed(tmp_path):
    root=tmp_path/'outputs'
    base=root/'_execution'
    base.mkdir(parents=True)
    (base/'claim.json').write_text('{"status":"running","nonce":"old-execution"}')
    with pytest.raises(ExecutionUncertain):
        with execution_lock(root):
            pass


def test_cancellable_run_preserves_run_interface(tmp_path):
    with execution_lock(tmp_path/'outputs'):
        result=cancellable_run([sys.executable,'-c','import sys;sys.stdout.write(sys.stdin.read().upper())'],input='hello',capture_output=True,text=True,check=True)
    assert result.stdout=='HELLO'
    assert result.returncode==0


def test_cancellable_run_timeout(tmp_path):
    with execution_lock(tmp_path/'outputs'):
        started=time.monotonic()
        with pytest.raises(subprocess.TimeoutExpired):
            cancellable_run([sys.executable,'-c','import time;time.sleep(60)'],capture_output=True,text=True,timeout=.1)
        assert time.monotonic()-started < 3


def test_receipt_write_failure_pauses_after_publishing(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'receipt_fail')
    thread.join(10)
    assert not thread.is_alive()
    assert isinstance(values.get('error'),ExecutionUncertain),values
    assert (root/'video/runs/2026-09-29_000000/transcript.html').is_file()
    with pytest.raises(ExecutionUncertain):
        with execution_lock(root):
            pass


def test_crash_after_receipt_recovers_committed_success(tmp_path, worker_file):
    thread,event,values,evidence,root = start_operation(tmp_path,worker_file,'crash_after_receipt')
    thread.join(10)
    assert not thread.is_alive()
    assert 'error' not in values,values
    assert values['result'].run_dir.joinpath('transcript.html').read_text()=='published'
    with execution_lock(root):
        pass


def test_process_identity_uses_kernel_start_identity():
    identity=process_identity(os.getpid())
    assert identity
    assert identity==process_identity(os.getpid())
    if sys.platform=='darwin':
        assert identity.startswith('darwin:')


def test_cancel_tracks_a_descendant_that_starts_another_session(tmp_path,worker_file):
    thread,event,values,evidence,root=start_operation(tmp_path,worker_file,'escaped')
    wait_for(lambda:(evidence/'grandchild_pid').exists())
    grandchild=int((evidence/'grandchild_pid').read_text())
    # Ensure the guardian has observed the new-session descendant, then cancel.
    def observed():
        for path in (root/'_execution').glob('*/owner.json'):
            if any(item['pid']==grandchild for item in json.loads(path.read_text()).get('processes',[])):
                return True
        return False
    wait_for(observed)
    event.set()
    thread.join(10)
    assert not thread.is_alive()
    assert isinstance(values.get('error'),OperationCanceled),values
    assert grandchild not in process_table()


def test_explicit_recovery_requires_dead_owned_processes_and_nonce(tmp_path,worker_file):
    thread,event,values,evidence,root=start_operation(tmp_path,worker_file,'python_hang')
    wait_for(lambda:(evidence/'worker_pid').exists())
    owner=json.loads(next((root/'_execution').glob('*/owner.json')).read_text())
    with pytest.raises(ExecutionBusy):
        reconcile_execution(root)
    os.kill(owner['pid'],signal.SIGKILL)
    thread.join(3)
    assert isinstance(values.get('error'),ExecutionUncertain),values
    wait_for(lambda:owner['worker_pid'] not in process_table())
    # The worker is reaped asynchronously by the OS after its guardian died.
    wait_for(lambda:process_identity(owner['worker_pid']) is None)
    assert reconcile_execution(root) is True
    with execution_lock(root):
        pass


def test_recovery_does_not_erase_a_claim_with_missing_identity(tmp_path):
    root=tmp_path/'outputs'
    base=root/'_execution';base.mkdir(parents=True)
    claim={'status':'running','nonce':'old-without-proof'}
    (base/'claim.json').write_text(json.dumps(claim))
    with pytest.raises(ExecutionUncertain):
        reconcile_execution(root)
    assert json.loads((base/'claim.json').read_text())==claim


@pytest.mark.parametrize("attempt", range(2))
def test_immediate_parent_exit_and_closed_fds_cannot_escape_cancellation(tmp_path,worker_file,attempt):
    # Reproduce the independently found race, with no wait-for-observed gate.
    text=worker_file.read_text().replace('close_fds=False,start_new_session=', 'close_fds=True,start_new_session=')
    text=text.replace('+ "); time.sleep(60)"', '+ "); sys.exit(0)"')
    worker_file.write_text(text)
    thread,event,values,evidence,root=start_operation(tmp_path,worker_file,'escaped')
    wait_for(lambda:(evidence/'grandchild_pid').exists())
    pid=int((evidence/'grandchild_pid').read_text())
    identity=process_identity(pid)
    try:
        event.set()
        thread.join(10)
        assert not thread.is_alive()
        assert isinstance(values.get('error'),OperationCanceled),values
        assert pid not in process_table()
        with execution_lock(root):
            pass
    finally:
        if process_identity(pid)==identity:
            os.kill(pid,signal.SIGKILL)


def test_known_descendant_that_clears_environment_still_stops(tmp_path,worker_file):
    # Once ancestry establishes ownership, clearing env must not waive cleanup.
    text=worker_file.read_text().replace('close_fds=False,start_new_session=', 'close_fds=True,env={},start_new_session=')
    worker_file.write_text(text)
    thread,event,values,evidence,root=start_operation(tmp_path,worker_file,'escaped')
    wait_for(lambda:(evidence/'grandchild_pid').exists())
    pid=int((evidence/'grandchild_pid').read_text())
    identity=process_identity(pid)
    try:
        def linked():
            return any(any(item['pid']==pid for item in json.loads(path.read_text()).get('processes',[]))
                       for path in (root/'_execution').glob('*/owner.json'))
        wait_for(linked)
        event.set()
        thread.join(10)
        assert not thread.is_alive()
        assert isinstance(values.get('error'),OperationCanceled),values
        assert pid not in process_table()
    finally:
        if process_identity(pid)==identity:
            os.kill(pid,signal.SIGKILL)


@pytest.mark.parametrize('mode,artifacts,warnings',[
    ('retry_fresh',['transcript.txt'],['original_saved']),
    ('retry_without_diagnostic',[],[]),
])
def test_retry_error_only_uses_explicit_attempt_diagnostics(tmp_path,worker_file,mode,artifacts,warnings):
    thread,event,values,evidence,root=start_operation(tmp_path,worker_file,mode,
        operation_extra={'kind':'retry','run_key':'video/runs/2026-09-29_000000'})
    thread.join(10)
    assert not thread.is_alive()
    error=values['error']
    from bilifan.pipeline import PipelineRunError
    assert isinstance(error,PipelineRunError),values
    assert error.run_key=='video/runs/2026-09-29_000000'
    assert error.artifact_paths==artifacts
    assert error.warnings==warnings


def test_run_link_is_durable_before_parent_receives_ipc(tmp_path,monkeypatch):
    from bilifan import execution
    from bilifan.web.queue_storage import read_run_link
    root=tmp_path/'outputs'
    key='BV1abcDEF12G_p1/runs/2026-09-29_000000'
    (root/key).mkdir(parents=True)
    state=root/'_execution'/'test'
    state.mkdir(parents=True)
    context=execution._Context(root,state,'a'*32,999,job_id='ipc_not_received',event_fd=987)
    token=execution._context.set(context)
    seen=[]
    original_write=execution.os.write
    def fail_at_ipc(descriptor,data):
        if descriptor==987:
            # The parent has received no bytes, yet restart recovery already
            # has a durable link to this exact job and invocation.
            seen.append(read_run_link(root,'ipc_not_received'))
            raise BrokenPipeError('parent disappeared before event')
        return original_write(descriptor,data)
    monkeypatch.setattr(execution.os,'write',fail_at_ipc)
    try:
        with pytest.raises(OperationCanceled):
            execution.emit_event({'type':'run_created','run_key':key})
    finally:
        execution._context.reset(token)
    assert len(seen)==1
    assert seen[0]['job_id']=='ipc_not_received'
    assert seen[0]['nonce']=='a'*32
    assert seen[0]['run_key']==key
    assert read_run_link(root,'ipc_not_received')['run_key']==key


def test_run_link_write_failure_prevents_metadata_and_ipc(tmp_path,monkeypatch):
    from bilifan import execution
    from bilifan.web import queue_storage
    root=tmp_path/'outputs';root.mkdir()
    state=root/'execution';state.mkdir()
    context=execution._Context(root,state,'a'*32,999,job_id='link_failed',event_fd=987)
    token=execution._context.set(context)
    seen=[]
    def fail_link(*args,**kwargs):
        raise OSError('fixture disk full')
    monkeypatch.setattr(queue_storage,'write_run_link',fail_link)
    monkeypatch.setattr(execution.os,'write',lambda *args:seen.append(args))
    try:
        with pytest.raises(ExecutionUncertain):
            execution.emit_event({'type':'run_created','run_key':'never_processed/runs/x'})
        assert context.uncertain is True
        assert seen==[]
    finally:
        execution._context.reset(token)
