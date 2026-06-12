import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import bilifan.retry as retry_module
from bilifan.renderer import PdfExportError
from bilifan.summarizer import SummarizationError
from bilifan.cli import app
from bilifan.retry import RetryError, retry_run


runner = CliRunner()


def _run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-09_120000"
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "metadata.json",
        {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-09T00:00:00+00:00",
            "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "video_id": "BV1abcDEF12G",
            "part_index": 1,
            "title": "Retry title",
            "part_title": "Retry title",
            "owner_name": "UP",
            "duration": 120,
            "metadata_source": "fixture",
        },
    )
    _write_json(
        run_dir / "transcript.json",
        {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0, "end": 120, "text": "转写"}],
            "transcript_check": {"status": "ok", "segment_count": 1},
        },
    )
    _write_json(
        run_dir / "chunks.json",
        {
            "chunk_count": 1,
            "media_duration_seconds": 120,
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0,
                    "end": 120,
                    "segments": [{"source_index": 0, "start": 0, "end": 120, "text": "转写"}],
                    "text": "转写",
                }
            ],
        },
    )
    _write_json(run_dir / "diagnostics.json", {"duration_check": {"status": "ok"}})
    (run_dir / "transcript.txt").write_text("转写", encoding="utf-8")
    return run_dir


def _youtube_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "outputs" / "YTdQw4w9WgXcQ_p1" / "runs" / "2026-06-09_120000"
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "metadata.json",
        {
            "platform": "youtube",
            "video_id": "dQw4w9WgXcQ",
            "part_index": 1,
            "input_url_sanitized": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "YouTube retry title",
            "part_title": "YouTube retry title",
            "owner_name": "Channel",
            "duration": 3,
            "metadata_source": "fixture",
        },
    )
    _write_json(
        run_dir / "transcript.json",
        {
            "source": "youtube-subtitle",
            "language": "en",
            "segments": [{"start": 0, "end": 3, "text": "Hello"}],
            "transcript_check": {"status": "ok", "segment_count": 1},
        },
    )
    _write_json(
        run_dir / "chunks.json",
        {
            "chunk_count": 1,
            "media_duration_seconds": 3,
            "chunks": [{"chunk_index": 1, "start": 0, "end": 3, "text": "Hello"}],
        },
    )
    _write_json(run_dir / "diagnostics.json", {"duration_check": {"status": "ok"}})
    return run_dir


def _chapters():
    return {
        "style": "学习笔记",
        "chapters": [
            {
                "chapter_index": 1,
                "title": "重试章节",
                "start": 0,
                "end": 120,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "summary": "重试摘要",
                "key_points": ["要点"],
                "quotes": [],
                "visual_anchors": [],
            }
        ],
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_retry_bundle_writes_bundle_and_success_diagnostics(tmp_path):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")

    result = retry_run(run_dir, from_stage="bundle")

    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-09_120000"
    assert "content_bundle.json" in result.artifact_paths
    assert "nabaichuan.jsonl" in result.artifact_paths
    assert (run_dir / "nabaichuan.jsonl").is_file()
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p1"
    assert diagnostics["error_type"] is None
    assert diagnostics["stage"] == "bundle"


def test_retry_youtube_bundle_preserves_platform_and_source_id(tmp_path):
    run_dir = _youtube_run_dir(tmp_path)
    _write_json(
        run_dir / "chapters.json",
        {
            "style": "学习笔记",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "Intro",
                    "start": 0,
                    "end": 3,
                    "timestamp_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=0s",
                    "summary": "Summary",
                    "key_points": [],
                    "quotes": [],
                    "visual_anchors": [],
                }
            ],
        },
    )

    result = retry_run(run_dir, from_stage="bundle")

    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert result.run_key == "YTdQw4w9WgXcQ_p1/runs/2026-06-09_120000"
    assert bundle["bundle_id"] == "youtube:dQw4w9WgXcQ:p1"
    assert bundle["source"]["platform"] == "youtube"
    assert bundle["source"]["id"] == "dQw4w9WgXcQ"
    assert diagnostics["video_id"] == "dQw4w9WgXcQ"


def test_retry_render_rewrites_report_and_bundle(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text(f"<html>{chapters['chapters'][0]['title']}</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    def fake_export_report_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(retry_module, "export_report_pdf", fake_export_report_pdf)

    result = retry_run(run_dir, from_stage="render", output_format="html,pdf")

    assert (run_dir / "report.html").read_text(encoding="utf-8") == "<html>重试章节</html>"
    assert (run_dir / "report.pdf").is_file()
    assert (run_dir / "content_bundle.json").is_file()
    assert (run_dir / "nabaichuan.jsonl").is_file()
    assert "content_bundle.json" in result.artifact_paths
    assert "nabaichuan.jsonl" in result.artifact_paths


def test_retry_summarization_rewrites_chapters_notes_report_and_bundle(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)

    def fake_summarize_chunks(*, ref, metadata, chunks, run_dir, provider, model, style):
        assert provider == "codex-exec"
        assert model == "gpt-5.5"
        return _chapters()

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "summarize_chunks", fake_summarize_chunks)
    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(run_dir, from_stage="summarization", output_format="html")

    chapters = json.loads((run_dir / "chapters.json").read_text(encoding="utf-8"))
    assert chapters["chapters"][0]["title"] == "重试章节"
    assert (run_dir / "notes.md").is_file()
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "content_bundle.json").is_file()
    assert "content_bundle.json" in result.artifact_paths


def test_retry_missing_required_file_fails_with_sanitized_message(tmp_path):
    run_dir = _run_dir(tmp_path)

    with pytest.raises(RetryError, match="chapters.json"):
        retry_run(run_dir, from_stage="bundle")


def test_cli_retry_command_invokes_retry(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    calls = []

    def fake_retry_run(run_dir_arg, **kwargs):
        calls.append((run_dir_arg, kwargs))
        return retry_module.RetryResult(
            run_key="BV1abcDEF12G_p1/runs/2026-06-09_120000",
            run_dir=run_dir,
            diagnostics_path=run_dir / "diagnostics.json",
            artifact_paths=["content_bundle.json"],
            warnings=[],
        )

    monkeypatch.setattr("bilifan.cli.retry_run", fake_retry_run)

    result = runner.invoke(app, ["retry", str(run_dir), "--from", "bundle"])

    assert result.exit_code == 0
    assert "Retried Bilifan run: BV1abcDEF12G_p1/runs/2026-06-09_120000" in result.output
    assert calls[0][0] == run_dir
    assert calls[0][1]["from_stage"] == "bundle"


def test_retry_invalid_format_fails_before_summarization_side_effects(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    calls = []

    def fake_summarize_chunks(**kwargs):
        calls.append(kwargs)
        return _chapters()

    monkeypatch.setattr(retry_module, "summarize_chunks", fake_summarize_chunks)

    with pytest.raises(RetryError, match="--format"):
        retry_run(run_dir, from_stage="summarization", output_format="docx")

    assert calls == []
    assert not (run_dir / "chapters.json").exists()


def test_retry_render_html_only_does_not_expose_stale_pdf(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.pdf").write_bytes(b"stale pdf")

    monkeypatch.setattr(
        retry_module,
        "render_report_html",
        lambda *, ref, metadata, transcript, chapters, run_dir: (
            run_dir / "report.html"
        ),
    )
    (run_dir / "report.html").write_text("<html>retry</html>", encoding="utf-8")

    result = retry_run(run_dir, from_stage="render", output_format="html")
    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))

    assert "report.pdf" not in result.artifact_paths
    assert "report_pdf" not in bundle["artifacts"]


def test_retry_require_pdf_failure_writes_failed_diagnostics(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    def fake_export_report_pdf(*, html_path, pdf_path):
        raise PdfExportError("Chrome failed for /Users/jack/report.html")

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(retry_module, "export_report_pdf", fake_export_report_pdf)

    with pytest.raises(RetryError, match="Chrome failed"):
        retry_run(run_dir, from_stage="render", require_pdf=True)

    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "PdfExportError"
    assert diagnostics["stage"] == "render"
    assert diagnostics["exit_code"] == 1
    assert "/Users/jack" not in diagnostics["sanitized_message"]


def test_retry_summarization_failure_writes_failed_diagnostics(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)

    def fake_summarize_chunks(**kwargs):
        raise SummarizationError("CODEX_ACCESS_TOKEN=secret failed")

    monkeypatch.setattr(retry_module, "summarize_chunks", fake_summarize_chunks)

    with pytest.raises(RetryError, match="CODEX_ACCESS_TOKEN=<redacted>"):
        retry_run(run_dir, from_stage="summarization", output_format="html")

    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "SummarizationError"
    assert diagnostics["stage"] == "summarization"
    assert diagnostics["exit_code"] == 1
    assert "secret" not in diagnostics["sanitized_message"]


def test_retry_summarization_failure_does_not_expose_stale_downstream_artifacts(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "notes.md").write_text("stale notes", encoding="utf-8")
    (run_dir / "report.html").write_text("<html>stale</html>", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"stale pdf")
    _write_json(run_dir / "content_bundle.json", {"stale": True})

    def fake_summarize_chunks(**kwargs):
        raise SummarizationError("summary failed")

    monkeypatch.setattr(retry_module, "summarize_chunks", fake_summarize_chunks)

    with pytest.raises(RetryError, match="summary failed"):
        retry_run(run_dir, from_stage="summarization", output_format="html")

    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert "report.html" not in diagnostics["artifact_paths"]
    assert "report.pdf" not in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in diagnostics["artifact_paths"]


def test_retry_render_failure_does_not_expose_stale_report_or_bundle(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.html").write_text("<html>stale</html>", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"stale pdf")
    _write_json(run_dir / "content_bundle.json", {"stale": True})

    def fake_render_report_html(**kwargs):
        raise ValueError("render failed")

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    with pytest.raises(RetryError, match="render failed"):
        retry_run(run_dir, from_stage="render", output_format="html")

    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert "report.html" not in diagnostics["artifact_paths"]
    assert "report.pdf" not in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in diagnostics["artifact_paths"]
