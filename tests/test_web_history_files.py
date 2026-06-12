import json

import pytest

from bilifan.web.files import (
    list_all_runs,
    list_latest_runs,
    list_run_files,
    resolve_run_file,
)


def _make_run(
    outputs,
    output_id="BV1abcDEF12G_p1",
    run_id="2026-06-08_120000",
    *,
    success=True,
):
    video_dir = outputs / output_id
    run_dir = video_dir / "runs" / run_id
    run_dir.mkdir(parents=True)
    (video_dir / "latest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "run_dir": f"runs/{run_id}",
                "generated_at": "2026-06-08T12:00:00+00:00",
                "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "metadata.json").write_text('{"title":"Mock title"}', encoding="utf-8")
    (run_dir / "diagnostics.json").write_text(
        json.dumps(
            {
                "error_type": None if success else "MetadataIngestError",
                "stage": "render" if success else "metadata",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"%PDF")
    (run_dir / "transcript.txt").write_text("plain transcript", encoding="utf-8")
    (run_dir / "transcript.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\ncaption",
        encoding="utf-8",
    )
    (run_dir / "notes.md").write_text("# Notes", encoding="utf-8")
    (run_dir / "content_bundle.json").write_text('{"schema_version":1}', encoding="utf-8")
    (run_dir / "nabaichuan.jsonl").write_text('{"type":"video"}\n', encoding="utf-8")
    frame_dir = run_dir / "media" / "frames"
    frame_dir.mkdir(parents=True)
    (frame_dir / "chapter_001_000030.jpg").write_bytes(b"jpg")
    partial_dir = run_dir / "partial_summaries"
    partial_dir.mkdir()
    (partial_dir / "chunk_001.json").write_text("{}", encoding="utf-8")
    return run_dir


def _replace_with_symlink_or_skip(link_path, target_path):
    try:
        link_path.unlink()
    except FileNotFoundError:
        pass
    try:
        link_path.symlink_to(target_path, target_is_directory=target_path.is_dir())
    except (NotImplementedError, OSError):
        pytest.skip("Symlink creation is unsupported on this platform.")


def test_list_latest_runs_reads_outputs_latest_json(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    items = list_latest_runs(outputs)

    assert len(items) == 1
    assert items[0]["output_id"] == "BV1abcDEF12G_p1"
    assert items[0]["title"] == "Mock title"
    assert items[0]["status"] == "succeeded"
    assert items[0]["stage"] == "render"
    assert items[0]["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert items[0]["artifacts"] == {
        "html": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
        "pdf": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.pdf",
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
        "txt": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt",
        "srt": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.srt",
        "md": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/notes.md",
        "bundle": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json",
        "nabaichuan": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl",
        "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
    }


def test_list_latest_runs_accepts_youtube_output_id(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs, output_id="YTdQw4w9WgXcQ_p1")

    items = list_latest_runs(outputs)

    assert len(items) == 1
    assert items[0]["output_id"] == "YTdQw4w9WgXcQ_p1"
    assert items[0]["run_key"] == "YTdQw4w9WgXcQ_p1/runs/2026-06-08_120000"


@pytest.mark.parametrize("metadata", [{}, {"title": 123}, {"title": ""}])
def test_list_latest_runs_falls_back_to_output_id_for_missing_or_invalid_title(
    tmp_path, metadata
):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    items = list_latest_runs(outputs)

    assert items[0]["title"] == "BV1abcDEF12G_p1"


def test_list_latest_runs_skips_invalid_utf8_latest_json(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    (outputs / "BV1abcDEF12G_p1" / "latest.json").write_bytes(b"\xff")

    items = list_latest_runs(outputs)

    assert items == []


def test_list_latest_runs_skips_latest_json_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    video_dir = outputs / "BV1abcDEF12G_p1"
    video_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_latest = outside_dir / "latest.json"
    outside_latest.write_text(
        json.dumps(
            {
                "run_id": "2026-06-08_120000",
                "run_dir": "runs/2026-06-08_120000",
                "generated_at": "2026-06-08T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    _replace_with_symlink_or_skip(video_dir / "latest.json", outside_latest)

    items = list_latest_runs(outputs)

    assert items == []


def test_list_latest_runs_falls_back_to_output_id_for_invalid_utf8_metadata(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "metadata.json").write_bytes(b"\xff")

    items = list_latest_runs(outputs)

    assert items[0]["title"] == "BV1abcDEF12G_p1"


def test_list_latest_runs_ignores_invalid_utf8_diagnostics(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "diagnostics.json").write_bytes(b"\xff")

    items = list_latest_runs(outputs)

    assert items[0]["status"] == "succeeded"
    assert items[0]["stage"] == ""


def test_list_latest_runs_does_not_read_metadata_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "metadata.json"
    outside_file.write_text('{"title":"Outside title"}', encoding="utf-8")
    _replace_with_symlink_or_skip(run_dir / "metadata.json", outside_file)

    items = list_latest_runs(outputs)

    assert items[0]["title"] == "BV1abcDEF12G_p1"


def test_list_latest_runs_does_not_read_diagnostics_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "diagnostics.json"
    outside_file.write_text(
        json.dumps({"error_type": "OutsideError", "stage": "outside"}),
        encoding="utf-8",
    )
    _replace_with_symlink_or_skip(run_dir / "diagnostics.json", outside_file)

    items = list_latest_runs(outputs)

    assert items[0]["status"] == "succeeded"
    assert items[0]["stage"] == ""


def test_list_latest_runs_failed_run_includes_friendly_error_and_retry_actions(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs, success=False)
    (run_dir / "transcript.json").write_text("{}", encoding="utf-8")
    (run_dir / "chunks.json").write_text("{}", encoding="utf-8")
    (run_dir / "diagnostics.json").write_text(
        json.dumps(
            {
                "error_type": "SummarizationError",
                "stage": "summarization",
                "sanitized_message": "codex exec failed to start: [Errno 2] No such file or directory: 'codex'",
                "artifact_paths": [
                    "diagnostics.json",
                    "metadata.json",
                    "transcript.json",
                    "chunks.json",
                ],
                "warnings": ["summarization_failed"],
            }
        ),
        encoding="utf-8",
    )

    items = list_latest_runs(outputs)

    assert items[0]["status"] == "failed"
    assert items[0]["friendly_error"]["title"] == "Codex CLI 未找到"
    assert items[0]["retry_actions"] == ["summarization"]


def test_failed_latest_run_uses_diagnostics_artifacts_not_stale_files(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs, success=False)
    (run_dir / "diagnostics.json").write_text(
        json.dumps(
            {
                "error_type": "SummarizationError",
                "stage": "summarization",
                "artifact_paths": [
                    "diagnostics.json",
                    "metadata.json",
                    "transcript.json",
                    "chunks.json",
                ],
            }
        ),
        encoding="utf-8",
    )

    items = list_latest_runs(outputs)

    artifacts = items[0]["artifacts"]
    assert artifacts == {
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
        "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
    }


def test_failed_all_runs_uses_diagnostics_artifacts_not_stale_files(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs, success=False)
    (run_dir / "diagnostics.json").write_text(
        json.dumps(
            {
                "error_type": "RenderError",
                "stage": "render",
                "artifact_paths": [
                    "diagnostics.json",
                    "metadata.json",
                    "transcript.json",
                    "chunks.json",
                    "chapters.json",
                    "content_bundle.json",
                ],
            }
        ),
        encoding="utf-8",
    )

    items = list_all_runs(outputs)

    artifacts = items[0]["artifacts"]
    assert artifacts == {
        "diagnostics": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json",
        "bundle": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json",
        "folder": "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder",
    }


def test_list_latest_runs_skips_run_dir_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_run_dir = tmp_path / "outside_run"
    outside_run_dir.mkdir()
    (outside_run_dir / "metadata.json").write_text(
        '{"title":"Outside title"}',
        encoding="utf-8",
    )
    run_backup = tmp_path / "original_run"
    run_dir.rename(run_backup)
    _replace_with_symlink_or_skip(run_dir, outside_run_dir)

    items = list_latest_runs(outputs)

    assert items == []


def test_list_run_files_only_includes_whitelisted_files(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    run_dir = outputs / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
    (run_dir / "secret.txt").write_text("no", encoding="utf-8")

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "metadata.json" in files
    assert "report.html" in files
    assert "transcript.txt" in files
    assert "transcript.srt" in files
    assert "notes.md" in files
    assert "content_bundle.json" in files
    assert "nabaichuan.jsonl" in files
    assert "media/frames/chapter_001_000030.jpg" in files
    assert "partial_summaries/chunk_001.json" in files
    assert "secret.txt" not in files


def test_list_and_resolve_visible_audio_artifact_without_exposing_cache(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    audio_path = run_dir / "media" / "audio.mp3"
    audio_path.parent.mkdir(exist_ok=True)
    audio_path.write_bytes(b"audio")
    cache_path = run_dir / ".bilifan" / "cache" / "hidden.mp3"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_bytes(b"hidden")

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")
    resolved = resolve_run_file(
        outputs,
        "BV1abcDEF12G_p1",
        "2026-06-08_120000",
        "media/audio.mp3",
    )

    assert "media/audio.mp3" in files
    assert ".bilifan/cache/hidden.mp3" not in files
    assert resolved == audio_path
    frame = resolve_run_file(
        outputs,
        "BV1abcDEF12G_p1",
        "2026-06-08_120000",
        "media/frames/chapter_001_000030.jpg",
    )
    assert frame.name == "chapter_001_000030.jpg"
    with pytest.raises(ValueError):
        resolve_run_file(
            outputs,
            "BV1abcDEF12G_p1",
            "2026-06-08_120000",
            ".bilifan/cache/hidden.mp3",
        )


def test_list_run_files_only_includes_numeric_partial_summary_chunks(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    partial_dir = (
        outputs
        / "BV1abcDEF12G_p1"
        / "runs"
        / "2026-06-08_120000"
        / "partial_summaries"
    )
    (partial_dir / "chunk_notes.json").write_text("{}", encoding="utf-8")
    (partial_dir / "chunk_.json").write_text("{}", encoding="utf-8")

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "partial_summaries/chunk_001.json" in files
    assert "partial_summaries/chunk_notes.json" not in files
    assert "partial_summaries/chunk_.json" not in files


def test_list_run_files_excludes_root_artifact_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "report.html"
    outside_file.write_text("<html>outside</html>", encoding="utf-8")
    _replace_with_symlink_or_skip(run_dir / "report.html", outside_file)

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "report.html" not in files


def test_list_run_files_excludes_partial_summary_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "chunk_001.json"
    outside_file.write_text("{}", encoding="utf-8")
    _replace_with_symlink_or_skip(
        run_dir / "partial_summaries" / "chunk_001.json",
        outside_file,
    )

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "partial_summaries/chunk_001.json" not in files


def test_resolve_run_file_rejects_non_numeric_partial_summary_chunk(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    (run_dir / "partial_summaries" / "chunk_notes.json").write_text(
        "{}",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        resolve_run_file(
            outputs,
            "BV1abcDEF12G_p1",
            "2026-06-08_120000",
            "partial_summaries/chunk_notes.json",
        )


def test_resolve_run_file_accepts_numeric_partial_summary_chunk(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    path = resolve_run_file(
        outputs,
        "BV1abcDEF12G_p1",
        "2026-06-08_120000",
        "partial_summaries/chunk_001.json",
    )

    assert path.name == "chunk_001.json"


@pytest.mark.parametrize(
    ("file_path", "content"),
    [
        ("transcript.txt", "plain transcript"),
        ("transcript.srt", "caption"),
        ("notes.md", "# Notes"),
        ("content_bundle.json", "schema_version"),
        ("nabaichuan.jsonl", "video"),
    ],
)
def test_resolve_run_file_accepts_export_artifacts(tmp_path, file_path, content):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    path = resolve_run_file(
        outputs,
        "BV1abcDEF12G_p1",
        "2026-06-08_120000",
        file_path,
    )

    assert content in path.read_text(encoding="utf-8")


def test_resolve_run_file_allows_error_run_diagnostics(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = outputs / "_errors" / "runs" / "2026-06-08_120000"
    run_dir.mkdir(parents=True)
    (run_dir / "diagnostics.json").write_text("{}", encoding="utf-8")

    path = resolve_run_file(outputs, "_errors", "2026-06-08_120000", "diagnostics.json")

    assert path == run_dir / "diagnostics.json"


def test_resolve_run_file_rejects_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "metadata.json"
    outside_file.write_text('{"title":"Outside"}', encoding="utf-8")
    metadata_path = run_dir / "metadata.json"
    _replace_with_symlink_or_skip(metadata_path, outside_file)

    with pytest.raises(ValueError):
        resolve_run_file(
            outputs,
            "BV1abcDEF12G_p1",
            "2026-06-08_120000",
            "metadata.json",
        )


@pytest.mark.parametrize(
    "file_path",
    ["../metadata.json", "/tmp/secret", "partial_summaries/../metadata.json", "a\\\\b"],
)
def test_resolve_run_file_rejects_unsafe_paths(tmp_path, file_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)

    with pytest.raises(ValueError):
        resolve_run_file(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000", file_path)
