import json
from datetime import datetime, timezone

import pytest

from bilifan.bilibili import BilibiliPartRef
from bilifan.runs import create_error_run, create_run


class _GenericRef:
    output_id = "YTdQw4w9WgXcQ_p1"
    sanitized_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


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


def test_create_run_accepts_youtube_output_id(tmp_path):
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    run = create_run(tmp_path / "outputs", _GenericRef(), now=now)

    assert run.video_dir == tmp_path / "outputs" / "YTdQw4w9WgXcQ_p1"
    latest = json.loads((run.video_dir / "latest.json").read_text(encoding="utf-8"))
    assert latest["input_url_sanitized"] == (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    )


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


def test_create_run_rejects_escaped_output_id_before_overwrite_delete(tmp_path):
    ref = BilibiliPartRef(
        bvid="../outside",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    outside_run = tmp_path / "outside_p1" / "runs" / "2026-06-08_011530"
    outside_run.mkdir(parents=True)
    sentinel = outside_run / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid run output id"):
        create_run(tmp_path / "outputs", ref, now=now, overwrite=True)

    assert sentinel.read_text(encoding="utf-8") == "keep me"


def test_create_run_rejects_unsafe_output_ids(tmp_path):
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    unsafe_refs = [
        BilibiliPartRef(
            bvid=str(tmp_path / "absolute"),
            part_index=1,
            sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        ),
        BilibiliPartRef(
            bvid="BV1abc/DEF12G",
            part_index=1,
            sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        ),
        BilibiliPartRef(
            bvid="BV1abcDEF12!",
            part_index=1,
            sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        ),
    ]

    for ref in unsafe_refs:
        with pytest.raises(ValueError, match="Invalid run output id"):
            create_run(tmp_path / "outputs", ref, now=now, overwrite=True)


def test_create_run_rejects_resolved_run_dir_outside_out_dir(tmp_path):
    ref = BilibiliPartRef(
        bvid="BV1abcDEF12G",
        part_index=1,
        sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=1",
    )
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    out_dir = tmp_path / "outputs"
    outside_video_dir = tmp_path / "outside_video"
    outside_run = outside_video_dir / "runs" / "2026-06-08_011530"
    outside_run.mkdir(parents=True)
    sentinel = outside_run / "sentinel.txt"
    sentinel.write_text("keep me", encoding="utf-8")
    out_dir.mkdir()
    (out_dir / ref.output_id).symlink_to(outside_video_dir, target_is_directory=True)

    with pytest.raises(ValueError, match="outside output directory"):
        create_run(out_dir, ref, now=now, overwrite=True)

    assert sentinel.read_text(encoding="utf-8") == "keep me"


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
