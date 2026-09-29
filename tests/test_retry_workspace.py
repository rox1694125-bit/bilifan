from pathlib import Path

import pytest

import bilifan.retry_workspace as workspace_module
from bilifan.retry_workspace import RetryWorkspaceError, retry_workspace


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-09_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "report.html").write_text("old report", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"old pdf")
    media = run_dir / "media"
    media.mkdir()
    (media / "audio.mp3").write_bytes(b"original audio")
    (run_dir.parent.parent / "latest.json").write_text("original latest", encoding="utf-8")
    return run_dir


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_failure_discards_independent_copy_and_keeps_original(tmp_path):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)

    with pytest.raises(RuntimeError, match="generation failed"):
        with retry_workspace(run_dir) as workspace:
            working_path = workspace.path
            (working_path / "report.html").write_text("new report", encoding="utf-8")
            (working_path / "media/audio.mp3").write_bytes(b"changed copy")
            assert _snapshot(run_dir) == original
            raise RuntimeError("generation failed")

    assert _snapshot(run_dir) == original
    assert not working_path.exists()


def test_no_explicit_publish_keeps_original(tmp_path):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    with retry_workspace(run_dir) as workspace:
        (workspace.path / "report.html").unlink()
    assert _snapshot(run_dir) == original


def test_publish_replaces_whole_directory_and_keeps_latest_pointer(tmp_path):
    run_dir = _run_dir(tmp_path)
    latest_path = run_dir.parent.parent / "latest.json"
    latest = latest_path.read_bytes()
    with retry_workspace(run_dir) as workspace:
        (workspace.path / "report.html").write_text("new report", encoding="utf-8")
        (workspace.path / "report.pdf").unlink()
        (workspace.path / "content_bundle.json").write_text("{}", encoding="utf-8")
        expected = _snapshot(workspace.path)
        workspace.publish()
        assert workspace.warnings == []
    assert _snapshot(run_dir) == expected
    assert latest_path.read_bytes() == latest
    assert not list(run_dir.parent.glob(".*.backup-*"))


def test_publish_failure_restores_original(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    original_rename = Path.rename
    with retry_workspace(run_dir) as workspace:
        working_path = workspace.path
        (working_path / "report.html").write_text("new report", encoding="utf-8")

        def fail_publishing(self, target):
            if self == working_path:
                raise OSError("simulated publish failure")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fail_publishing)
        with pytest.raises(RetryWorkspaceError, match="original restored"):
            workspace.publish()
        assert _snapshot(run_dir) == original
    assert _snapshot(run_dir) == original
    assert not working_path.exists()


def test_initial_rename_failure_keeps_original(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    with retry_workspace(run_dir) as workspace:
        (workspace.path / "report.html").write_text("new report", encoding="utf-8")

        def fail_rename(self, target):
            raise OSError("simulated permission failure")

        monkeypatch.setattr(Path, "rename", fail_rename)
        with pytest.raises(RetryWorkspaceError, match="original run was not replaced"):
            workspace.publish()
        assert workspace.backup_path is None
    assert _snapshot(run_dir) == original


def test_copy_failure_cleans_partial_workspace_and_keeps_original(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)

    def fail_copy(source, target, **kwargs):
        target.mkdir()
        (target / "partial").write_bytes(b"partly copied")
        raise OSError("disk full")

    monkeypatch.setattr(workspace_module.shutil, "copytree", fail_copy)
    with pytest.raises(RetryWorkspaceError, match="Could not copy"):
        with retry_workspace(run_dir):
            pytest.fail("a partial copy is not a usable workspace")
    assert _snapshot(run_dir) == original
    assert not list(run_dir.parent.glob(".*.retry-*"))


def test_restore_failure_preserves_backup_after_context_cleanup(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    original_rename = Path.rename
    with retry_workspace(run_dir) as workspace:
        working_path = workspace.path

        def fail_publish_and_restore(self, target):
            if self != run_dir:
                raise OSError("simulated rename failure")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fail_publish_and_restore)
        with pytest.raises(RetryWorkspaceError, match="backup preserved"):
            workspace.publish()
        backup_path = workspace.backup_path
        assert backup_path is not None
        assert not run_dir.exists()
    assert backup_path.is_dir()
    assert _snapshot(backup_path) == original
    assert not working_path.exists()


@pytest.mark.parametrize("link_kind", ["file", "directory", "broken"])
def test_rejects_symlinks_without_modifying_run(tmp_path, link_kind):
    run_dir = _run_dir(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "data.txt"
    secret.write_text("external data", encoding="utf-8")
    target = {"file": secret, "directory": outside, "broken": outside / "missing"}[link_kind]
    (run_dir / "linked").symlink_to(target)
    with pytest.raises(RetryWorkspaceError, match="symlink"):
        with retry_workspace(run_dir):
            pytest.fail("linked input must be rejected")
    assert (run_dir / "report.html").read_text(encoding="utf-8") == "old report"
    assert secret.read_text(encoding="utf-8") == "external data"


def test_same_run_cannot_be_retried_concurrently_and_lock_is_reusable(tmp_path):
    run_dir = _run_dir(tmp_path)
    with retry_workspace(run_dir):
        with pytest.raises(RetryWorkspaceError, match="already being retried"):
            with retry_workspace(run_dir):
                pytest.fail("second writer acquired the same run")
    with retry_workspace(run_dir):
        pass
    assert (run_dir.parent / ".retry-locks" / f"{run_dir.name}.lock").is_file()


def test_symlink_created_by_generation_cannot_be_published(tmp_path):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    with retry_workspace(run_dir) as workspace:
        (workspace.path / "linked-report").symlink_to(run_dir / "report.html")
        with pytest.raises(RetryWorkspaceError, match="symlink"):
            workspace.publish()
    assert _snapshot(run_dir) == original


def test_backup_cleanup_failure_is_success_with_warning(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    original = _snapshot(run_dir)
    original_rmtree = workspace_module.shutil.rmtree
    with retry_workspace(run_dir) as workspace:
        (workspace.path / "report.html").write_text("new report", encoding="utf-8")

        def fail_backup_cleanup(path, *args, **kwargs):
            if ".backup-" in Path(path).name:
                raise OSError("simulated cleanup failure")
            return original_rmtree(path, *args, **kwargs)

        monkeypatch.setattr(workspace_module.shutil, "rmtree", fail_backup_cleanup)
        workspace.publish()
        backup_path = workspace.backup_path
        assert workspace.warnings == ["retry_backup_cleanup_failed"]
    assert (run_dir / "report.html").read_text(encoding="utf-8") == "new report"
    assert backup_path is not None
    assert _snapshot(backup_path) == original
