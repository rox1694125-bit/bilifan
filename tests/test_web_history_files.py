import json

import pytest

from bilifan.web.files import (
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
    partial_dir = run_dir / "partial_summaries"
    partial_dir.mkdir()
    (partial_dir / "chunk_001.json").write_text("{}", encoding="utf-8")
    return run_dir


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


def test_list_run_files_only_includes_whitelisted_files(tmp_path):
    outputs = tmp_path / "outputs"
    _make_run(outputs)
    run_dir = outputs / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000"
    (run_dir / "secret.txt").write_text("no", encoding="utf-8")

    files = list_run_files(outputs, "BV1abcDEF12G_p1", "2026-06-08_120000")

    assert "metadata.json" in files
    assert "report.html" in files
    assert "partial_summaries/chunk_001.json" in files
    assert "secret.txt" not in files


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


def test_resolve_run_file_rejects_symlink_escape(tmp_path):
    outputs = tmp_path / "outputs"
    run_dir = _make_run(outputs)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_file = outside_dir / "metadata.json"
    outside_file.write_text('{"title":"Outside"}', encoding="utf-8")
    metadata_path = run_dir / "metadata.json"
    metadata_path.unlink()
    try:
        metadata_path.symlink_to(outside_file)
    except (NotImplementedError, OSError):
        pytest.skip("Symlink creation is unsupported on this platform.")

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
