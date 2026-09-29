"""Single-writer, crash-resistant queue ledger and independently durable receipts."""
from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class QueueStorageError(RuntimeError):
    """The queue must stop scheduling until its durable state is trustworthy."""


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def atomic_bytes(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


class QueueStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.backup_path = self.path.with_suffix(self.path.suffix + ".bak")
        self._lock_file = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._lock_file = self.path.with_suffix(self.path.suffix + ".writer.lock").open("a+b")
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ValueError) as exc:
            self.close()
            raise QueueStorageError("任务账本不可写或已由另一服务占用，已暂停调度。") from exc

    def load(self) -> dict[str, Any] | None:
        try:
            payload = self.path.read_bytes()
        except FileNotFoundError:
            # A missing main file next to a backup is an incident, not a new queue.
            if self.backup_path.exists():
                raise QueueStorageError("任务账本缺失但备份仍存在，已暂停调度，请先核对恢复。")
            return None
        except OSError as exc:
            raise QueueStorageError("无法读取任务账本，已暂停调度。") from exc
        try:
            value = json.loads(payload)
            if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
                raise ValueError("invalid ledger")
            if value.get("schema_version", 1) not in {1, 2}:
                raise ValueError("unknown ledger version")
            if not isinstance(value.get("paused", False), bool):
                raise ValueError("invalid pause state")
            if not isinstance(value.get("intake_batches", {}), dict):
                raise ValueError("invalid intake index")
            return value
        except (ValueError, UnicodeError) as exc:
            raise QueueStorageError("任务账本损坏或版本不兼容，已暂停调度；原文件和备份均已保留。") from exc

    def save(self, value: dict[str, Any]) -> None:
        if self._lock_file is None:
            raise QueueStorageError("任务账本写入权已释放，已暂停调度。")
        try:
            if self.path.exists():
                # Never turn invalid input into a purported last-good backup.
                self.load()
                atomic_bytes(self.backup_path, self.path.read_bytes())
            atomic_json(self.path, value)
        except (OSError, ValueError, TypeError, QueueStorageError) as exc:
            raise QueueStorageError("任务账本保存失败，已暂停调度；此次操作未确认，请检查存储后恢复。") from exc

    def close(self) -> None:
        handle, self._lock_file = self._lock_file, None
        if handle is not None:
            # close releases flock; never unlink the shared inode.
            handle.close()

    def __del__(self) -> None:
        self.close()


def _receipt_path(outputs_root: Path, job_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", job_id):
        raise ValueError("Invalid completion receipt job ID")
    return outputs_root / "_jobs" / "receipts" / f"{job_id}.json"


def write_completion_receipt(outputs_root: Path, job_id: str, result: Any) -> None:
    """Call after verified publication, before acknowledging completion to queue."""
    atomic_json(_receipt_path(outputs_root, job_id), {
        "schema_version": 1, "job_id": job_id, "run_key": result.run_key,
        "artifact_paths": list(result.artifact_paths), "warnings": list(result.warnings),
    })


def read_completion_receipt(outputs_root: Path, job_id: str, *, run_key: str | None = None) -> dict[str, Any] | None:
    path = _receipt_path(outputs_root, job_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _receipt_from_completion_marker(outputs_root, job_id, run_key)
    except (OSError, ValueError, UnicodeError) as exc:
        raise QueueStorageError("完成凭证不可读取，已暂停调度并保留原记录。") from exc
    if not isinstance(data, dict) or data.get("job_id") != job_id or data.get("schema_version") != 1:
        raise QueueStorageError("完成凭证身份无效，已暂停调度。")
    key = data.get("run_key")
    artifacts = data.get("artifact_paths")
    if not isinstance(key, str) or not key or not isinstance(artifacts, list):
        raise QueueStorageError("完成凭证字段不完整，已暂停调度。")
    root = outputs_root.resolve()
    run_dir = (root / key).resolve()
    if not run_dir.is_relative_to(root) or run_dir == root or Path(key).is_absolute() or ".." in Path(key).parts:
        raise QueueStorageError("完成凭证路径无效，已暂停调度。")
    if not run_dir.is_dir():
        raise QueueStorageError("完成凭证对应目录缺失，已暂停调度。")
    for name in artifacts:
        if not isinstance(name, str):
            raise QueueStorageError("完成凭证产物无效，已暂停调度。")
        artifact = (run_dir / name).resolve()
        if Path(name).is_absolute() or not artifact.is_relative_to(run_dir) or not artifact.is_file():
            raise QueueStorageError("完成凭证对应产物缺失，已暂停调度。")
    return data


def _receipt_from_completion_marker(outputs_root: Path, job_id: str, run_key: str | None) -> dict[str, Any] | None:
    """Recover the publication-to-receipt crash window, bound to this exact job.

    A successful older retry in the same directory is not evidence that the
    current attempt finished. Both operation identity and published bytes must
    match before using this fallback.
    """
    if not run_key:
        return None
    root = outputs_root.resolve()
    run_dir = (root / run_key).resolve()
    if Path(run_key).is_absolute() or ".." in Path(run_key).parts or not run_dir.is_relative_to(root) or run_dir == root:
        raise QueueStorageError("完成标记目录无效，已暂停调度。")
    try:
        marker = json.loads((run_dir / "completion.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError) as exc:
        raise QueueStorageError("完成标记无法读取，已暂停调度。") from exc
    if not isinstance(marker, dict):
        raise QueueStorageError("完成标记格式无效，已暂停调度。")
    identity = marker.get("execution")
    if not isinstance(identity, dict) or identity.get("job_id") != job_id:
        return None
    if not isinstance(identity.get("nonce"), str) or not identity["nonce"]:
        raise QueueStorageError("完成标记执行身份不完整，已暂停调度。")
    linked = read_run_link(outputs_root, job_id)
    if linked is not None and (linked["nonce"] != identity["nonce"] or linked["run_key"] != run_key):
        raise QueueStorageError("完成标记与本次执行绑定不一致，已暂停调度。")
    from bilifan.delivery import successful_delivery
    if not successful_delivery(run_dir):
        raise QueueStorageError("完成标记与交付文件不一致，已暂停调度。")
    try:
        diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise QueueStorageError("完成标记对应交付记录不可读取，已暂停调度。") from exc
    if not isinstance(diagnostics, dict):
        raise QueueStorageError("完成标记对应交付记录无效，已暂停调度。")
    names = diagnostics.get("artifact_paths", list(marker["artifacts"]))
    if not isinstance(names, list):
        raise QueueStorageError("完成标记对应交付产物无效，已暂停调度。")
    for name in names:
        if (not isinstance(name, str) or Path(name).is_absolute() or ".." in Path(name).parts
                or not (run_dir / name).resolve().is_relative_to(run_dir)
                or not (run_dir / name).is_file()):
            raise QueueStorageError("完成标记对应交付产物缺失，已暂停调度。")
    return {"schema_version": 1, "job_id": job_id, "run_key": run_key,
            "artifact_paths": names, "warnings": diagnostics.get("warnings", []),
            "recovered_from": "completion_marker"}


def _run_link_path(outputs_root: Path, job_id: str) -> Path:
    # Use the same job-ID validation as independent completion receipts.
    validated_name = _receipt_path(outputs_root, job_id).name
    root = Path(outputs_root).resolve()
    path = root / "_jobs" / "run_links" / validated_name
    if any(parent.is_symlink() for parent in (path, path.parent, path.parent.parent)):
        raise ValueError("Run binding must not use symbolic links")
    return path


def _validate_run_link(outputs_root: Path, job_id: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("job_id") != job_id:
        raise ValueError("Run binding identity does not match its job")
    nonce = value.get("nonce")
    key = value.get("run_key")
    if not isinstance(nonce, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", nonce):
        raise ValueError("Run binding nonce is invalid")
    if not isinstance(key, str) or not key or Path(key).is_absolute() or ".." in Path(key).parts:
        raise ValueError("Run binding path is invalid")
    root = Path(outputs_root).resolve()
    run = root / key
    if not run.resolve().is_relative_to(root) or run.resolve() == root:
        raise ValueError("Run binding points outside outputs")
    current = run
    while current != root:
        if current.is_symlink():
            raise ValueError("Run binding must not follow symbolic links")
        current = current.parent
    if not run.is_dir():
        raise ValueError("Run binding directory does not exist")
    return value


def write_run_link(outputs_root: Path, job_id: str, *, nonce: str, run_key: str) -> None:
    """Durably bind a worker to its run before publishing the IPC event.

    One job can have one run and one execution identity. Repeating the same
    event is idempotent; overwriting another invocation is a protocol error.
    """
    value = _validate_run_link(outputs_root, job_id, {
        "schema_version": 1, "job_id": job_id, "nonce": nonce, "run_key": run_key,
    })
    path = _run_link_path(outputs_root, job_id)
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        previous = None
    if previous is not None and previous != value:
        raise ValueError("Cannot rebind a job to a different execution or run")
    atomic_json(path, value)


def read_run_link(outputs_root: Path, job_id: str) -> dict[str, Any] | None:
    try:
        path = _run_link_path(outputs_root, job_id)
        value = json.loads(path.read_text(encoding="utf-8"))
        return _validate_run_link(outputs_root, job_id, value)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, UnicodeError) as exc:
        raise QueueStorageError("任务执行与产物目录的绑定无法核对，已暂停调度并保留原记录。") from exc
