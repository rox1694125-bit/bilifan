"""Cancelable execution with one durable, inherited execution lease per outputs tree.

The supervisor owns the lease; the worker and every managed subprocess inherit
its open file description. Closing (never explicitly unlocking) the descriptor
cannot release another still-running descendant's lease.
"""
from __future__ import annotations

import contextvars
import ctypes
import fcntl
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

POLL_SECONDS = 0.05
TERM_GRACE_SECONDS = 5.0


class OperationCanceled(RuntimeError):
    """Raised only after the managed computation has stopped."""


class ExecutionBusy(RuntimeError):
    pass


class ExecutionUncertain(RuntimeError):
    """Do not dispatch more work until execution ownership is reconciled."""


@dataclass(frozen=True)
class ExecutionResult:
    run_key: str
    run_dir: Path
    diagnostics_path: Path
    artifact_paths: list[str]
    warnings: list[str]


@dataclass
class _Context:
    root: Path
    state: Path
    nonce: str
    lock_fd: int
    job_id: str | None = None
    event_fd: int | None = None
    cancel_event: threading.Event | None = None
    published: bool = False
    uncertain: bool = False
    completion_recorded: bool = False


_context: contextvars.ContextVar[_Context | None] = contextvars.ContextVar("bilifan_execution", default=None)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    from .web.queue_storage import atomic_json as write
    write(path, value)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Execution record is not an object")
    return value


def _execution_root(outputs_root: Path) -> Path:
    return Path(outputs_root).resolve() / "_execution"


def _acquire_lock(outputs_root: Path) -> int:
    base = _execution_root(outputs_root)
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(base / "execution.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim_path = base / "claim.json"
        if claim_path.exists():
            try:
                claim = _read_json(claim_path)
            except (OSError, ValueError) as exc:
                raise ExecutionUncertain("执行声明损坏，已停止调度，请先核对旧计算。") from exc
            if claim.get("status") not in {"completed", "failed", "canceled"}:
                raise ExecutionUncertain("上次计算未确认退出，已停止调度，请先核对执行记录。")
        return fd
    except BlockingIOError as exc:
        os.close(fd)
        raise ExecutionBusy("已有任务或 CLI 正在计算，请等待实际计算退出后继续。") from exc
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def execution_lock(outputs_root: Path) -> Iterator[None]:
    """CLI lease; inside a worker the already-inherited lease is reused."""
    existing = _context.get()
    if existing is not None:
        if existing.root != Path(outputs_root).resolve():
            raise ExecutionUncertain("执行期间不能切换 outputs 目录。")
        yield
        return
    root = Path(outputs_root).resolve()
    fd = _acquire_lock(root)
    nonce = uuid.uuid4().hex
    state = _execution_root(root) / nonce
    try:
        state.mkdir(mode=0o700)
        claim = {"schema_version": 1, "nonce": nonce, "status": "running", "owner": "cli", "pid": os.getpid(), "identity": process_identity(os.getpid()), "state": str(state)}
        atomic_json(state / "owner.json", claim)
        atomic_json(_execution_root(root) / "claim.json", claim)
    except BaseException:
        os.close(fd)
        raise
    token = _context.set(_Context(root, state, nonce, fd))
    try:
        yield
    except BaseException as exc:
        claim["status"] = "uncertain" if isinstance(exc, ExecutionUncertain) or _context.get().uncertain else "failed"
        atomic_json(_execution_root(root) / "claim.json", claim)
        raise
    else:
        claim["status"] = "uncertain" if _context.get().uncertain else "completed"
        atomic_json(_execution_root(root) / "claim.json", claim)
    finally:
        _context.reset(token)
        os.close(fd)


def reconcile_execution(outputs_root: Path) -> bool:
    """Explicit recovery only: never signal PIDs or silently take over a lease.

    Returns True when a stale invocation is proven stopped and its claim is
    resolved; False when there is no unresolved claim. Missing evidence remains
    fail-closed. Call only from an explicit recovery action, not startup.
    """
    base = _execution_root(outputs_root)
    claim_path = base / "claim.json"
    if not claim_path.exists():
        return False
    descriptor = os.open(base / "execution.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ExecutionBusy("旧计算仍持有执行锁，不能恢复新任务。") from exc
        try:
            claim = _read_json(claim_path)
            if claim.get("status") in {"completed", "failed", "canceled"}:
                return False
            nonce = claim.get("nonce")
            if not isinstance(nonce, str) or not re.fullmatch(r"[0-9a-f]{32}", nonce):
                raise ValueError("Missing invocation nonce")
            state = base / nonce
            if Path(claim.get("state", "")).resolve() != state.resolve():
                raise ValueError("Invocation state directory mismatch")
            owner = _read_json(state / "owner.json")
            if owner.get("nonce") != nonce or owner.get("owner") not in {"supervisor", "cli"}:
                raise ValueError("Invocation identity mismatch")
            table = process_table()
            identities = [{"pid": owner.get("pid"), "identity": owner.get("identity")}]
            groups: set[int] = set()
            if owner.get("owner") == "supervisor":
                if not isinstance(owner.get("worker_pid"), int):
                    raise ValueError("Missing worker ownership evidence")
                identities.append({"pid": owner["worker_pid"], "identity": owner.get("worker_identity")})
                if owner.get("worker_pgid") != owner["worker_pid"]:
                    raise ValueError("Worker group mismatch")
                groups.add(owner["worker_pgid"])
            for item in [*owner.get("processes", []), *owner.get("unresolved_processes", [])]:
                if not isinstance(item, dict):
                    raise ValueError("Invalid descendant identity")
                identities.append(item)
                if isinstance(item.get("pgid"), int):
                    groups.add(item["pgid"])
            for path in (state / "children").glob("*.json"):
                child = _read_json(path)
                if child.get("nonce") != nonce:
                    raise ValueError("Child nonce mismatch")
                identities.append(child)
                if isinstance(child.get("pgid"), int):
                    groups.add(child["pgid"])
            for item in identities:
                pid, identity = item.get("pid"), item.get("identity")
                if not isinstance(pid, int) or pid <= 0 or not isinstance(identity, str) or not identity:
                    raise ValueError("Missing process start identity")
                current_identity = process_identity(pid)
                if current_identity == identity:
                    raise ExecutionBusy("旧执行所属进程仍存活，保持暂停。")
                if pid in table and current_identity is None:
                    raise ExecutionUncertain("无法核对旧执行进程身份，保持暂停。")
            if any(info["pgid"] in groups for info in table.values()):
                raise ExecutionBusy("旧执行组仍有进程，无法确认清理完成。")
            # The kernel lease was acquired and every captured invocation/group
            # identity is now absent. Preserve evidence; only resolve its claim.
            claim.update(status="failed", reconciled=True)
            atomic_json(state / "reconciled.json", {"nonce": nonce, "status": "stopped"})
            atomic_json(claim_path, claim)
            return True
        except (OSError, ValueError, TypeError) as exc:
            raise ExecutionUncertain("执行身份证据不完整，保持暂停并保留现场。") from exc
    finally:
        os.close(descriptor)


def check_cancelled() -> None:
    context = _context.get()
    if context is None or context.published or (context.state / "publication-complete.json").exists():
        return
    if (context.cancel_event is not None and context.cancel_event.is_set()) or (context.state / "cancel").exists():
        raise OperationCanceled("任务已取消，已停止计算。")


def emit_event(event: dict[str, Any]) -> None:
    context = _context.get()
    if context is not None and context.job_id and event.get("type") == "run_created":
        from .web.queue_storage import QueueStorageError, write_run_link
        try:
            write_run_link(context.root, context.job_id, nonce=context.nonce, run_key=event.get("run_key"))
        except (OSError, ValueError, QueueStorageError) as exc:
            context.uncertain = True
            raise ExecutionUncertain("任务目录已创建，但任务关联未能保存；已停止后续处理并保留现场。") from exc
    if context is not None and context.event_fd is not None:
        encoded = (json.dumps({"type": "event", "event": event}, ensure_ascii=False) + "\n").encode()
        try:
            os.write(context.event_fd, encoded)
        except BrokenPipeError:
            # The supervisor is gone. Do not continue into publication.
            (context.state / "cancel").touch()
            check_cancelled()


def current_operation_identity() -> dict[str, str] | None:
    context = _context.get()
    if context is None:
        return None
    identity = {"nonce": context.nonce}
    if context.job_id:
        identity["job_id"] = context.job_id
    return identity


def record_completion(result: Any) -> None:
    context = _context.get()
    if context is not None and context.job_id and not context.completion_recorded:
        from .web.queue_storage import write_completion_receipt
        try:
            write_completion_receipt(context.root, context.job_id, result)
            context.completion_recorded = True
        except (OSError, ValueError) as exc:
            context.uncertain = True
            raise ExecutionUncertain("成果已发布但完成凭证未能保存，已停止后续调度。") from exc


@contextmanager
def publish_guard() -> Iterator[None]:
    """Protect only the final publication/rollback/receipt critical section."""
    context = _context.get()
    if context is None:
        yield
        return
    with (context.state / "publish.lock").open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        check_cancelled()
        atomic_json(context.state / "publication-started.json", {"nonce": context.nonce})
        try:
            yield
        except BaseException:
            # Publication could have crossed an atomic rename before failing.
            # Its caller may roll back, but only durable evidence can prove it.
            context.uncertain = True
            raise
        else:
            atomic_json(context.state / "publication-complete.json", {"nonce": context.nonce})
            context.published = True
        # Closing drops only this critical-section lock.


class _MacBsdInfo(ctypes.Structure):
    # Public macOS <sys/proc_info.h>, struct proc_bsdinfo (136 bytes).
    _fields_ = [("prefix", ctypes.c_uint32 * 12), ("comm", ctypes.c_char * 16),
                ("name", ctypes.c_char * 32), ("suffix", ctypes.c_uint32 * 6),
                ("start_seconds", ctypes.c_uint64), ("start_microseconds", ctypes.c_uint64)]


def _mac_process_identity(pid: int) -> str | None:
    library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    function = library.proc_pidinfo
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    info = _MacBsdInfo()
    size = ctypes.sizeof(info)
    if function(pid, 3, 0, ctypes.byref(info), size) != size:
        return None
    return f"darwin:{info.start_seconds}:{info.start_microseconds}"


def process_identity(pid: int) -> str | None:
    """Capture kernel start identity, not just a reusable PID."""
    try:
        if sys.platform == "darwin":
            return _mac_process_identity(pid)
        stat = Path(f"/proc/{pid}/stat")
        if stat.exists():
            fields = stat.read_text().rsplit(")", 1)[1].split()
            return "linux:" + fields[19]  # /proc field 22: start ticks
        result = subprocess.run(["ps", "-p", str(pid), "-o", "lstart="], capture_output=True, text=True, timeout=2)
        started = result.stdout.strip()
        return "ps:" + started if result.returncode == 0 and started else None
    except (OSError, subprocess.SubprocessError, IndexError):
        return None


def process_table() -> dict[int, dict[str, Any]]:
    try:
        result = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid=,stat=,uid="], capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ExecutionUncertain("无法读取计算进程表，已停止调度。") from exc
    if result.returncode:
        raise ExecutionUncertain("无法核对计算进程，已停止调度。")
    table: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            pid, ppid, pgid = map(int, parts[:3])
        except ValueError:
            continue
        if not parts[3].startswith("Z"):
            table[pid] = {"ppid": ppid, "pgid": pgid, "uid": int(parts[4])}
    return table


def process_has_nonce(pid: int, nonce: str) -> bool | None:
    """Compare only our invocation tag; never log or persist process environments.

    The tag survives setsid, reparenting and close_fds. The result is attribution,
    not permission to kill: every signal still checks the kernel start identity.
    None means the OS would not let us establish identity, so it cannot be used
    as evidence that a possible orphan is unrelated.
    """
    marker = ("BILIFAN_EXECUTION_NONCE=" + nonce).encode()
    try:
        if sys.platform == "linux":
            return marker in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        if sys.platform != "darwin":
            return None
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        function = libc.sysctl
        function.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
        function.restype = ctypes.c_int
        mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2
        size = ctypes.c_size_t(max(262144, os.sysconf("SC_ARG_MAX")))
        buffer = ctypes.create_string_buffer(size.value)
        if function(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
            return None
        raw = buffer.raw[:size.value]
        argc = int.from_bytes(raw[:4], sys.byteorder, signed=True)
        if argc < 0 or argc > 65536:
            return None
        offset = raw.find(b"\0", 4) + 1  # executable path
        if offset <= 0:
            return None
        while offset < len(raw) and raw[offset] == 0:
            offset += 1
        for _ in range(argc):
            end = raw.find(b"\0", offset)
            if end < 0:
                return None
            offset = end + 1
        return marker in raw[offset:].split(b"\0")
    except (OSError, ValueError):
        return None


def _terminate_subprocess(process: subprocess.Popen[Any], *, isolated: bool) -> None:
    """Terminate a child and its observed descendants without touching unrelated PIDs."""
    if process.poll() is not None:
        return
    identity = process_identity(process.pid)
    if identity is None:
        raise ExecutionUncertain("无法确认待取消进程身份。")
    children: dict[int, str] = {}
    table = process_table()
    descendants = {process.pid}
    changed = True
    while changed:
        changed = False
        for pid, info in table.items():
            if info["ppid"] in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    for pid in descendants:
        child_identity = process_identity(pid)
        if child_identity:
            children[pid] = child_identity
    def send(sig: int) -> None:
        if isolated and process_identity(process.pid) == identity:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass
            return
        for pid, expected in reversed(list(children.items())):
            if process_identity(pid) == expected:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
    send(signal.SIGTERM)
    deadline = time.monotonic() + TERM_GRACE_SECONDS
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(POLL_SECONDS)
    send(signal.SIGKILL)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired as exc:
        raise ExecutionUncertain("计算未确认退出，已停止后续调度。") from exc


def cancellable_run(args: Any, *, input: Any = None, capture_output: bool = False, timeout: float | None = None, check: bool = False, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    """subprocess.run-compatible adapter with bounded cancellation polling."""
    check_cancelled()
    context = _context.get()
    if context is None:
        return subprocess.run(args, input=input, capture_output=capture_output, timeout=timeout, check=check, **kwargs)
    if input is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        if kwargs.get("stdout") is not None or kwargs.get("stderr") is not None:
            raise ValueError("stdout and stderr arguments may not be used with capture_output")
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    kwargs["pass_fds"] = tuple(set((*kwargs.pop("pass_fds", ()), context.lock_fd)))
    kwargs["env"] = dict(kwargs.get("env") or os.environ, BILIFAN_EXECUTION_NONCE=context.nonce)
    # Worker descendants stay in the owned group. A CLI needs its own child group.
    isolated = context.event_fd is None
    kwargs["start_new_session"] = isolated
    process = subprocess.Popen(args, **kwargs)
    started = time.monotonic()
    first = True
    try:
        identity = process_identity(process.pid)
        if identity is not None:
            try:
                group = os.getpgid(process.pid)
            except ProcessLookupError:
                group = process.pid if isolated else os.getpgrp()
            atomic_json(context.state / "children" / (uuid.uuid4().hex + ".json"), {"nonce": context.nonce, "pid": process.pid, "identity": identity, "pgid": group})
        elif process.poll() is None:
            context.uncertain = True
            raise ExecutionUncertain("新计算进程启动身份未确认，已停止执行。")
        while True:
            check_cancelled()
            remaining = None if timeout is None else timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            try:
                stdout, stderr = process.communicate(input=input if first else None, timeout=min(POLL_SECONDS, remaining) if remaining is not None else POLL_SECONDS)
                break
            except subprocess.TimeoutExpired:
                first = False
        check_cancelled()
    except BaseException:
        _terminate_subprocess(process, isolated=isolated)
        # Drain closed pipes without blocking indefinitely on an orphan writer.
        try:
            process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        if isolated and any(info["pgid"] == process.pid for info in process_table().values()):
            context.uncertain = True
            raise ExecutionUncertain("CLI 子命令未确认完全退出，已停止后续执行。")
        raise
    if isolated and any(info["pgid"] == process.pid for info in process_table().values()):
        context.uncertain = True
        raise ExecutionUncertain("CLI 子命令结束后仍有后台计算，已停止后续执行。")
    result = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result


def run_whisper_worker(audio_path: Path, *, model_name: str, language: str, backend: str = "whisper") -> list[dict[str, Any]]:
    """Use exec to load Whisper/GPU libraries only inside a fresh interpreter."""
    if backend not in {"whisper", "mlx"}:
        raise ValueError("Unsupported Whisper backend")
    with tempfile.TemporaryDirectory(prefix="bilifan-whisper-") as directory:
        base = Path(directory)
        request_path, result_path = base / "request.json", base / "result.json"
        atomic_json(request_path, {"audio_path": str(audio_path), "model_name": model_name, "language": language, "backend": backend})
        completed = cancellable_run([sys.executable, "-m", "bilifan.execution_worker", "--whisper", str(request_path), str(result_path)], capture_output=True, text=True)
        if not result_path.is_file():
            raise RuntimeError("Whisper 独立进程未能完成转录。")
        payload = _read_json(result_path)
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        if completed.returncode:
            raise RuntimeError("Whisper 独立进程异常退出。")
        segments = payload.get("segments")
        if not isinstance(segments, list):
            raise RuntimeError("Whisper returned invalid transcript segments.")
        return segments


def _result_payload(result: Any) -> dict[str, Any]:
    return {"run_key": result.run_key, "run_dir": str(result.run_dir), "diagnostics_path": str(result.diagnostics_path), "artifact_paths": list(result.artifact_paths), "warnings": list(result.warnings)}


def execute_operation(operation: dict[str, Any], *, outputs_root: Path, progress_callback: Callable[[str, str, str], None], event_callback: Callable[[dict[str, Any]], None], cancel_event: threading.Event, job_id: str, _worker_command: list[str] | None = None) -> ExecutionResult:
    """Launch a supervised operation. Test doubles may inject a worker command."""
    root = Path(outputs_root).resolve()
    nonce = uuid.uuid4().hex
    state = _execution_root(root) / nonce
    state.mkdir(parents=True, mode=0o700)
    atomic_json(state / "request.json", {"operation": operation, "outputs_root": str(root), "job_id": job_id, "nonce": nonce, "worker_command": _worker_command})
    process = subprocess.Popen([sys.executable, "-m", "bilifan.execution_supervisor", str(state), nonce], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    assert process.stdout is not None and process.stdin is not None
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = b""
    sent_cancel = False
    terminal: dict[str, Any] | None = None
    try:
        while True:
            if cancel_event.is_set() and not sent_cancel:
                try:
                    process.stdin.write(b"cancel\n")
                    process.stdin.flush()
                except BrokenPipeError:
                    pass
                sent_cancel = True
            for key, _mask in selector.select(POLL_SECONDS):
                block = os.read(key.fileobj.fileno(), 65536)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                pending += block
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if message.get("type") == "progress":
                        progress_callback(message["stage"], message["status"], message["message"])
                    elif message.get("type") == "event":
                        event_callback(message["event"])
                    elif message.get("type") == "terminal":
                        terminal = message
            if process.poll() is not None and not selector.get_map():
                break
        if terminal is None:
            raise ExecutionUncertain("看护进程意外退出，旧计算未确认结束，已停止后续调度。")
        status = terminal.get("status")
        if status == "busy":
            raise ExecutionBusy(str(terminal.get("message")))
        if status == "uncertain":
            raise ExecutionUncertain(str(terminal.get("message")))
        if status == "canceled":
            raise OperationCanceled("任务已取消，计算进程已退出。")
        if status != "completed":
            from .pipeline import PipelineRunError
            error = terminal.get("error") or {}
            raise PipelineRunError(str(error.get("message", terminal.get("message", "任务执行失败。"))), run_key=error.get("run_key", ""), diagnostics_path=Path(error.get("diagnostics_path") or state / "error.json"), artifact_paths=error.get("artifact_paths", []), warnings=error.get("warnings", []), exit_code=error.get("exit_code", 1))
        result = terminal["result"]
        return ExecutionResult(result["run_key"], Path(result["run_dir"]), Path(result["diagnostics_path"]), result["artifact_paths"], result["warnings"])
    finally:
        # EOF instructs the still-live supervisor to clean up computation.
        process.stdin.close()
        selector.close()
        process.stdout.close()
