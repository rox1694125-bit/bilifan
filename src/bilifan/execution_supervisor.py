"""Small process guardian: no models imported, and no Web runtime required."""
from __future__ import annotations

import fcntl
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .execution import (
    ExecutionBusy, ExecutionUncertain, POLL_SECONDS, TERM_GRACE_SECONDS,
    _acquire_lock, _execution_root, _read_json, atomic_json,
    process_has_nonce, process_identity, process_table,
)


def _emit(message: dict[str, Any]) -> None:
    try:
        os.write(1, (json.dumps(message, ensure_ascii=False) + "\n").encode())
    except BrokenPipeError:
        pass


def _publishing(state: Path) -> bool:
    with (state / "publish.lock").open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True


def supervise(state: Path, nonce: str) -> int:
    request = _read_json(state / "request.json")
    if request.get("nonce") != nonce:
        raise ExecutionUncertain("执行 nonce 不匹配。")
    root = Path(request["outputs_root"]).resolve()
    fd = _acquire_lock(root)
    baseline = {pid: process_identity(pid) for pid, info in process_table().items() if info.get("uid") == os.getuid()}
    claim = {"schema_version": 1, "nonce": nonce, "status": "running", "owner": "supervisor", "pid": os.getpid(), "identity": process_identity(os.getpid()), "state": str(state)}
    atomic_json(_execution_root(root) / "claim.json", claim)
    atomic_json(state / "owner.json", claim)
    control_read, control_write = os.pipe()
    worker: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    cancel_requested = False
    def on_signal(_signum: int, _frame: Any) -> None:
        nonlocal cancel_requested
        cancel_requested = True
    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    try:
        env = dict(os.environ, BILIFAN_EXECUTION_LOCK_FD=str(fd), BILIFAN_EXECUTION_CONTROL_FD=str(control_read), BILIFAN_EXECUTION_NONCE=nonce)
        command = request.get("worker_command") or [sys.executable, "-m", "bilifan.execution_worker"]
        worker = subprocess.Popen([*command, str(state), nonce], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, pass_fds=(fd, control_read), start_new_session=True)
        os.close(control_read)
        control_read = -1
        assert worker.stdout is not None
        selector.register(worker.stdout, selectors.EVENT_READ, "worker")
        selector.register(sys.stdin.buffer, selectors.EVENT_READ, "parent")
        initial_identity = process_identity(worker.pid)
        tracked: dict[int, str] = {worker.pid: initial_identity} if initial_identity else {}
        claim.update(worker_pid=worker.pid, worker_identity=initial_identity, worker_pgid=worker.pid)
        atomic_json(state / "owner.json", claim)
        atomic_json(_execution_root(root) / "claim.json", claim)
        buffer = b""
        term_at: float | None = None
        kill_at: float | None = None
        worker_result: dict[str, Any] | None = None
        nonce_cache: dict[tuple[int, str], bool | None] = {}
        unresolved: dict[int, str] = {}
        known_groups: dict[int, int] = {worker.pid: worker.pid}
        observed_records: set[Path] = set()
        run_key = request.get("operation", {}).get("run_key")
        while True:
            for key, _mask in selector.select(POLL_SECONDS):
                block = os.read(key.fileobj.fileno(), 65536)
                if key.data == "parent":
                    if not block or b"cancel" in block:
                        cancel_requested = True
                    if not block:
                        selector.unregister(key.fileobj)
                    continue
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                buffer += block
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(event, dict) and event.get("type") in {"event", "progress"}:
                        payload = event.get("event", {})
                        if payload.get("type") == "run_created" and isinstance(payload.get("run_key"), str):
                            run_key = payload["run_key"]
                        _emit(event)
            if cancel_requested:
                (state / "cancel").touch()
            finished = worker.poll() is not None
            # Keep the child leader unreaped as long as practical and verify all
            # live members, ignoring zombies (they no longer own descriptors).
            table = process_table()
            # Registration by our own launcher is direct ownership evidence,
            # even when the command disappears before the first ps sample.
            for child_path in (state / "children").glob("*.json"):
                if child_path in observed_records:
                    continue
                child = _read_json(child_path)
                if child.get("nonce") != nonce or not isinstance(child.get("pid"), int) or not child.get("identity"):
                    raise ExecutionUncertain("计算子进程启动声明无效。")
                tracked[child["pid"]] = child["identity"]
                if isinstance(child.get("pgid"), int):
                    known_groups[child["pid"]] = child["pgid"]
                observed_records.add(child_path)
            members = {pid for pid, info in table.items() if info["pgid"] == worker.pid}
            identities = {pid: process_identity(pid) for pid in members}
            anchored = any(identities.get(pid) == expected for pid, expected in tracked.items() if expected)
            if members and not anchored:
                # A process may legitimately exit between ps and identity reads.
                current = process_table()
                members = {pid for pid in members if pid in current and current[pid]["pgid"] == worker.pid}
                if members:
                    anchored = any(identities.get(pid) is not None and process_has_nonce(pid, nonce) is True for pid in members)
                    if not anchored:
                        raise ExecutionUncertain("计算进程身份无法核对；保留执行声明并停止调度。")
            # Retain already observed descendants even if they establish another
            # process group or become reparented after their parent exits.
            for pid, expected in tracked.items():
                if pid in table:
                    observed_identity = process_identity(pid)
                    if observed_identity is None:
                        if pid in process_table():
                            raise ExecutionUncertain("已记录计算子进程的身份无法确认，已暂停且未发送信号。")
                        continue
                    if observed_identity == expected:
                        members.add(pid)
                        identities[pid] = expected
            changed = True
            while changed:
                changed = False
                for pid, info in table.items():
                    if pid not in members and info["ppid"] in members:
                        identity = process_identity(pid)
                        if identity:
                            members.add(pid)
                            identities[pid] = identity
                            changed = True
                        elif pid in process_table():
                            raise ExecutionUncertain("发现计算子孙但无法核对启动身份，已暂停且未发送信号。")
            # A descendant can setsid, close its inherited descriptors and be
            # reparented before even one process-table sample. The exec nonce
            # remains an independently checkable lineage marker in that case.
            # Deliberately clearing the environment AND detaching before any
            # ancestry observation is outside this unprivileged POSIX contract.
            # Never infer ownership merely from an unrelated new daemon's PID.
            unresolved_now: dict[int, str] = {}
            for pid, info in table.items():
                if pid in members or info.get("uid") != os.getuid():
                    continue
                identity = process_identity(pid)
                if not identity or baseline.get(pid) == identity:
                    continue
                cache_key = (pid, identity)
                if cache_key not in nonce_cache:
                    nonce_cache[cache_key] = process_has_nonce(pid, nonce)
                if nonce_cache[cache_key] is True:
                    members.add(pid)
                    identities[pid] = identity
                elif pid in tracked and tracked[pid] == identity:
                    # Startup/ancestry evidence makes this our responsibility.
                    # An unrelated application's new daemon is not such proof.
                    unresolved_now[pid] = identity
            unresolved = unresolved_now
            old_count = len(tracked)
            for pid in members:
                identity = identities.get(pid)
                if identity is None:
                    if pid in process_table():
                        raise ExecutionUncertain("无法确认计算子进程启动身份。")
                else:
                    tracked[pid] = identity
                    if pid in table:
                        known_groups[pid] = table[pid]["pgid"]
            if len(tracked) != old_count or unresolved:
                claim["processes"] = [{"pid": pid, "identity": identity, "pgid": known_groups.get(pid)} for pid, identity in tracked.items()]
                claim["unresolved_processes"] = [{"pid": pid, "identity": identity} for pid, identity in unresolved.items()]
                atomic_json(state / "owner.json", claim)

            def signal_owned(signum: int) -> None:
                # Only the worker's new session is group-signaled. Escaped
                # descendants are individually checked against start identity.
                anchored_members = [pid for pid in members if table.get(pid, {}).get("pgid") == worker.pid]
                if any(process_identity(pid) == tracked.get(pid) for pid in anchored_members):
                    try:
                        os.killpg(worker.pid, signum)
                    except ProcessLookupError:
                        pass
                for pid in members:
                    if table.get(pid, {}).get("pgid") != worker.pid and process_identity(pid) == tracked.get(pid):
                        try:
                            os.kill(pid, signum)
                        except ProcessLookupError:
                            pass
            published = (state / "publication-complete.json").exists()
            guarded = _publishing(state)
            must_clean = (cancel_requested and not published and not guarded) or finished
            if must_clean and members:
                if term_at is None:
                    # The group is owned by this invocation and anchored above.
                    signal_owned(signal.SIGTERM)
                    term_at = time.monotonic()
                elif time.monotonic() - term_at >= TERM_GRACE_SECONDS and kill_at is None:
                    signal_owned(signal.SIGKILL)
                    kill_at = time.monotonic()
                elif kill_at is not None and time.monotonic() - kill_at > 2:
                    raise ExecutionUncertain("计算进程在强制停止后仍未确认退出。")
            if finished and not members:
                if unresolved:
                    final_table = process_table()
                    unresolved = {pid: identity for pid, identity in unresolved.items() if pid in final_table and process_identity(pid) == identity}
                    claim["unresolved_processes"] = [{"pid": pid, "identity": identity} for pid, identity in unresolved.items()]
                    atomic_json(state / "owner.json", claim)
                if unresolved:
                    raise ExecutionUncertain("执行期间出现无法归属的新孤儿进程，不能确认计算全部退出；已暂停且未向不明进程发信号。")
                break
        try:
            worker_result = _read_json(state / "result.json")
        except (OSError, ValueError):
            worker_result = None
        if worker_result is not None and worker_result.get("nonce") != nonce:
            raise ExecutionUncertain("工作进程结果身份不匹配。")
        from .web.queue_storage import read_completion_receipt
        receipt = read_completion_receipt(root, request["job_id"], run_key=run_key)
        if receipt is not None:
            run_dir = root / receipt["run_key"]
            recovered = {"run_key": receipt["run_key"], "run_dir": str(run_dir), "diagnostics_path": str(run_dir / "diagnostics.json"), "artifact_paths": receipt["artifact_paths"], "warnings": receipt.get("warnings", [])}
            terminal = {"type": "terminal", "status": "completed", "result": recovered}
        elif worker_result and worker_result.get("status") == "uncertain":
            terminal = {"type": "terminal", "status": "uncertain", "error": worker_result.get("error", {})}
        elif (state / "publication-started.json").exists():
            terminal = {"type": "terminal", "status": "uncertain", "message": "发布曾开始但没有完整完成凭证，已停止调度。"}
        elif worker_result and worker_result.get("status") == "completed":
            # A claimed success without a durable receipt is not committed work.
            terminal = {"type": "terminal", "status": "uncertain", "message": "完成凭证缺失，已停止调度。"}
        elif cancel_requested:
            terminal = {"type": "terminal", "status": "canceled"}
        elif worker_result:
            terminal = {"type": "terminal", "status": worker_result.get("status", "failed"), "error": worker_result.get("error", {})}
        else:
            terminal = {"type": "terminal", "status": "failed", "message": "计算进程异常退出，现场已保留。"}
        claim["status"] = terminal["status"]
        if claim["status"] == "uncertain":
            terminal["message"] = str((terminal.get("error") or {}).get("message", terminal.get("message", "成果发布未确认，已停止调度。")))
        elif claim["status"] not in {"completed", "failed", "canceled"}:
            raise ExecutionUncertain("未知执行终态。")
        atomic_json(state / "terminal.json", terminal)
        atomic_json(_execution_root(root) / "claim.json", claim)
        _emit(terminal)
        return 0
    finally:
        selector.close()
        if control_read >= 0:
            os.close(control_read)
        os.close(control_write)  # EOF also asks any surviving worker to stop.
        if worker is not None and worker.stdout is not None:
            worker.stdout.close()
        # Do not LOCK_UN: surviving descendants must retain the same lease.
        os.close(fd)


def main() -> int:
    try:
        return supervise(Path(sys.argv[1]), sys.argv[2])
    except ExecutionBusy as exc:
        _emit({"type": "terminal", "status": "busy", "message": str(exc)})
        return 2
    except BaseException as exc:
        from .diagnostics import redact_text
        terminal = {"type": "terminal", "status": "uncertain", "message": redact_text(str(exc))}
        try:
            atomic_json(Path(sys.argv[1]) / "terminal.json", terminal)
        except (OSError, ValueError):
            pass
        _emit(terminal)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
