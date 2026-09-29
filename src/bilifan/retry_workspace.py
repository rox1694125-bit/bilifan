"""Isolate retry writes and retain the original run until publication.

Publication uses two same-filesystem renames, with rollback on an ordinary
exception. It is not a crash-atomic directory exchange: a process interruption
between renames can leave the original in the hidden backup directory. Backups
that cannot be restored or cleaned up are deliberately retained for recovery.
"""

from __future__ import annotations

import fcntl
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4


logger = logging.getLogger(__name__)


class RetryWorkspaceError(RuntimeError):
    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


class RetryWorkspace:
    def __init__(self, *, run_dir: Path, path: Path) -> None:
        self.run_dir = run_dir
        self.path = path
        self.backup_path: Path | None = None
        self.warnings: list[str] = []
        self._published = False

    def publish(self) -> None:
        if self._published:
            raise RetryWorkspaceError("Retry workspace has already been published.")
        _reject_symlinks(self.path)
        backup_path = self.run_dir.parent / f".{self.run_dir.name}.backup-{uuid4().hex}"
        try:
            self.run_dir.rename(backup_path)
        except OSError as exc:
            raise RetryWorkspaceError(
                "Could not prepare retry publication; original run was not replaced."
            ) from exc
        self.backup_path = backup_path
        try:
            self.path.rename(self.run_dir)
        except OSError as publish_error:
            try:
                backup_path.rename(self.run_dir)
            except OSError as restore_error:
                raise RetryWorkspaceError(
                    f"Retry publication and restoration failed; backup preserved at {backup_path}.",
                    backup_path=backup_path,
                ) from restore_error
            self.backup_path = None
            raise RetryWorkspaceError(
                "Retry publication failed; original restored."
            ) from publish_error

        self._published = True
        try:
            shutil.rmtree(backup_path)
        except OSError:
            self.warnings.append("retry_backup_cleanup_failed")
            logger.warning(
                "Retry published successfully; backup cleanup failed for %s", backup_path.name
            )
        else:
            self.backup_path = None


@contextmanager
def retry_workspace(run_dir: Path) -> Iterator[RetryWorkspace]:
    """Yield an independent copy; publish only when explicitly requested.

    The retained advisory lock serializes users of this helper for the same
    run. It does not lock readers or unrelated programs writing to that run.
    """
    if run_dir.is_symlink():
        raise RetryWorkspaceError("Cannot retry a run directory containing a symlink.")
    run_dir = run_dir.resolve(strict=False)
    if not run_dir.is_dir():
        raise RetryWorkspaceError("Retry run directory does not exist.")
    lock_dir = run_dir.parent / ".retry-locks"
    try:
        lock_dir.mkdir(exist_ok=True)
        if lock_dir.is_symlink():
            raise RetryWorkspaceError("Retry lock directory must not be a symlink.")
        lock_fd = os.open(
            lock_dir / f"{run_dir.name}.lock",
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as exc:
        raise RetryWorkspaceError("Could not open the retry lock.") from exc

    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RetryWorkspaceError("This run is already being retried.") from exc
        except OSError as exc:
            raise RetryWorkspaceError("Could not acquire the retry lock.") from exc

        _reject_symlinks(run_dir)
        try:
            temp_root = Path(
                tempfile.mkdtemp(prefix=f".{run_dir.name}.retry-", dir=run_dir.parent)
            )
        except OSError as exc:
            raise RetryWorkspaceError("Could not create an isolated retry workspace.") from exc
        workspace = RetryWorkspace(run_dir=run_dir, path=temp_root / "work")
        try:
            try:
                # Preserve links only long enough to reject them below, rather
                # than following any link added between inspection and copying.
                shutil.copytree(run_dir, workspace.path, symlinks=True)
                _reject_symlinks(workspace.path)
            except OSError as exc:
                raise RetryWorkspaceError("Could not copy the run into the retry workspace.") from exc
            yield workspace
        finally:
            try:
                shutil.rmtree(temp_root)
            except OSError:
                workspace.warnings.append("retry_workspace_cleanup_failed")
                logger.warning("Could not remove retry workspace %s", temp_root.name)
    finally:
        # Keep the lock file: unlinking permits another writer to lock a new
        # inode while a previous writer still holds the original inode's lock.
        os.close(lock_fd)


def _reject_symlinks(root: Path) -> None:
    def raise_walk_error(error: OSError) -> None:
        raise RetryWorkspaceError("Could not inspect the retry run directory.") from error

    if root.is_symlink():
        raise RetryWorkspaceError("Cannot retry a run directory containing a symlink.")
    for directory, subdirs, files in os.walk(root, followlinks=False, onerror=raise_walk_error):
        for name in [*subdirs, *files]:
            if (Path(directory) / name).is_symlink():
                raise RetryWorkspaceError("Cannot retry a run directory containing a symlink.")
