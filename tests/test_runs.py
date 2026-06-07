import json
from datetime import datetime, timezone

import pytest

from bilifan.bilibili import BilibiliPartRef
from bilifan.runs import create_error_run, create_run


def test_create_run_uses_stable_output_id_and_updates_latest(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=2,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    run = create_run(tmp_path / "outputs", ref, now=now)

    assert run.video_dir == tmp_path / "outputs" / "BV1abcDEF12G_p2"
    assert run.run_dir == run.video_dir / "runs" / "2026-06-08_011530"
    assert run.run_dir.is_dir()

    latest = json.loads((run.video_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["run_id"] == "2026-06-08_011530"
    assert latest["run_dir"] == "runs/2026-06-08_011530"
    assert latest["generated_at"] == "2026-06-08T01:15:30+00:00"
    assert latest["input_url_sanitized"] == "https://www.bilibili.com/video/BV1abcDEF12G?p=2"


def test_create_run_refuses_existing_run_without_overwrite(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    create_run(tmp_path / "outputs", ref, now=now)

    with pytest.raises(FileExistsError, match="already exists"):
        create_run(tmp_path / "outputs", ref, now=now)


def test_create_run_allows_overwrite(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    first = create_run(tmp_path / "outputs", ref, now=now)
    stale_file = first.run_dir / "stale.txt"
    stale_file.write_text("old content", encoding="utf-8")

    second = create_run(tmp_path / "outputs", ref, now=now, overwrite=True)

    assert second.run_dir == first.run_dir
    assert not stale_file.exists()


def test_create_error_run_does_not_update_video_latest(tmp_path):
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    run = create_error_run(tmp_path / "outputs", now=now)

    assert run.video_dir == tmp_path / "outputs" / "_errors"
    assert run.run_dir == run.video_dir / "runs" / "2026-06-08_011530"
    assert run.run_dir.is_dir()
    assert not (run.video_dir / "latest.json").exists()


def test_create_error_run_refuses_same_second_collision(tmp_path):
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    create_error_run(tmp_path / "outputs", now=now)

    with pytest.raises(FileExistsError):
        create_error_run(tmp_path / "outputs", now=now)
