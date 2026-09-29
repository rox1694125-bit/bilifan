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
            "segments": [{"start": 0, "end": 120, "text": '这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。'}],
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
                    "segments": [{"source_index": 0, "start": 0, "end": 120, "text": '这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。'}],
                    "text": '这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。',
                }
            ],
        },
    )
    _write_json(run_dir / "diagnostics.json", {"duration_check": {"status": "ok"}})
    (run_dir / "transcript.txt").write_text('这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。', encoding="utf-8")
    _write_json(run_dir / "transcript_article.json", _article())
    (run_dir / "transcript.html").write_text("<html>existing article</html>")
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
    _write_json(run_dir / "transcript_article.json", _article())
    (run_dir / "transcript.html").write_text("<html>existing article</html>")
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


def _article():
    return {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "重试文章",
                "start": 0,
                "end": 120,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "source_segment_start_index": 0,
                "source_segment_end_index": 0,
                "paragraphs": [{"text": '这是一段逐字稿测试内容，详细说明操作步骤、环境要求和验证方法，保留说话者的原意与关键细节。', "emphasis": []}],
                "key_terms": [],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _seed_existing_delivery(run_dir):
    _write_json(run_dir / "chapters.json", _chapters())
    _write_json(run_dir / "transcript_article.json", _article())
    _write_json(run_dir / "diagnostics.json", {
        "error_type": None, "exit_code": 0, "stage": "render",
        "duration_check": {"status": "ok"}, "warnings": [],
        "artifact_paths": ["report.html", "content_bundle.json"],
    })
    for name in ("transcript.html", "report.html", "transcript.pdf", "report.pdf",
                 "content_bundle.json", "nabaichuan.jsonl"):
        (run_dir / name).write_bytes(f"original {name}".encode())
    frame = run_dir / "media/frames/chapter_001_000001.jpg"
    frame.parent.mkdir(parents=True)
    frame.write_bytes(b"original frame")
    return {str(p.relative_to(run_dir)): p.read_bytes()
            for p in run_dir.rglob("*") if p.is_file()}


@pytest.mark.parametrize("failure", ["article", "article_render", "pdf", "bundle"])
def test_failed_regeneration_keeps_entire_previous_delivery(tmp_path, monkeypatch, failure):
    run_dir = _run_dir(tmp_path)
    previous = _seed_existing_delivery(run_dir)

    def generate(**kwargs):
        if failure == "article":
            raise retry_module.ArticleError("new article failed")
        article = _article()
        article["sections"][0]["title"] = "new article"
        _write_json(kwargs["run_dir"] / "transcript_article.json", article)
        (kwargs["run_dir"] / "media/frames/chapter_001_000001.jpg").write_bytes(b"new frame")
        return article

    def summarize(**kwargs):
        if failure == "summary":
            raise SummarizationError("new summary failed")
        return _chapters()

    def render_article(**kwargs):
        if failure == "article_render":
            raise ValueError("new article rendering failed")
        path = kwargs["run_dir"] / "transcript.html"
        path.write_text("new article html")
        return path

    def render_report(**kwargs):
        if failure == "report":
            raise ValueError("new report failed")
        path = kwargs["run_dir"] / "report.html"
        path.write_text("new report html")
        return path

    def pdf(**kwargs):
        path = kwargs["pdf_path"]
        path.write_bytes(b"new pdf")
        if failure == "pdf" and path.name == "transcript.pdf":
            raise PdfExportError("second pdf failed")
        return path

    real_bundle = retry_module.write_content_bundle
    def bundle(**kwargs):
        if failure == "bundle":
            (kwargs["run_dir"] / "content_bundle.json").write_text("truncated")
            raise OSError("new bundle failed")
        return real_bundle(**kwargs)

    monkeypatch.setattr(retry_module, "generate_transcript_article", generate)
    monkeypatch.setattr(retry_module, "summarize_article_sections", summarize)
    monkeypatch.setattr(retry_module, "render_transcript_html", render_article)
    monkeypatch.setattr(retry_module, "render_report_html", render_report)
    monkeypatch.setattr(retry_module, "export_html_pdf", pdf)
    monkeypatch.setattr(retry_module, "write_content_bundle", bundle)

    with pytest.raises(RetryError) as caught:
        retry_run(run_dir, from_stage="summarization", require_pdf=True)

    assert {name: (run_dir / name).read_bytes() for name in previous} == previous
    assert caught.value.diagnostics_path == run_dir / "retry_diagnostics.json"
    diagnostic = json.loads(caught.value.diagnostics_path.read_text())
    assert diagnostic["exit_code"] == 1
    assert diagnostic["error_type"]
    assert "report.html" not in diagnostic["artifact_paths"]


@pytest.mark.parametrize("missing", ["transcript.json", "transcript_article.json"])
def test_retry_missing_input_keeps_existing_delivery(tmp_path, missing):
    run_dir = _run_dir(tmp_path)
    previous = _seed_existing_delivery(run_dir)
    (run_dir / missing).unlink()
    previous.pop(missing)
    with pytest.raises(RetryError, match=missing):
        retry_run(run_dir, from_stage="summarization" if missing == "transcript.json" else "render")
    assert {name: (run_dir / name).read_bytes() for name in previous} == previous


def test_best_effort_pdf_failure_does_not_publish_partial_or_previous_pdf(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _seed_existing_delivery(run_dir)

    def fail_pdf(**kwargs):
        kwargs["pdf_path"].write_bytes(b"partial pdf")
        raise PdfExportError("Chrome failed")

    monkeypatch.setattr(retry_module, "export_html_pdf", fail_pdf)
    result = retry_run(run_dir, from_stage="render")
    assert result.run_dir == run_dir
    assert result.diagnostics_path == run_dir / "diagnostics.json"
    assert "pdf_failed" in result.warnings
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "report.pdf").is_file()
    assert not (run_dir / "transcript.pdf").exists()
    assert not (run_dir / "nabaichuan.jsonl").exists()


def test_retry_bundle_writes_bundle_and_success_diagnostics(tmp_path):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.html").write_text("<html></html>", encoding="utf-8")
    frame_path = run_dir / "media" / "frames" / "chapter_001_000030.jpg"
    frame_path.parent.mkdir(parents=True)
    frame_path.write_bytes(b"jpg")

    result = retry_run(run_dir, from_stage="bundle")

    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-09_120000"
    assert "content_bundle.json" in result.artifact_paths
    assert "nabaichuan.jsonl" not in result.artifact_paths
    assert "media/frames/chapter_001_000030.jpg" in result.artifact_paths
    assert "media/frames/chapter_001_000030.jpg" in bundle["artifacts"]["all"]
    assert not (run_dir / "nabaichuan.jsonl").exists()
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


def test_retry_bundle_passes_article_when_available(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    _write_json(run_dir / "transcript_article.json", _article())
    calls = []

    real_write_content_bundle = retry_module.write_content_bundle

    def fake_write_content_bundle(**kwargs):
        calls.append(kwargs)
        return real_write_content_bundle(**kwargs)

    monkeypatch.setattr(retry_module, "write_content_bundle", fake_write_content_bundle)

    result = retry_run(run_dir, from_stage="bundle")

    assert calls[0]["transcript_article"]["sections"][0]["title"] == "重试文章"
    assert "content_bundle.json" in result.artifact_paths
    assert "nabaichuan.jsonl" not in result.artifact_paths


def test_retry_render_rewrites_article_and_bundle(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text(f"<html>{chapters['chapters'][0]['title']}</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    def fake_export_html_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(
        retry_module,
        "export_html_pdf",
        fake_export_html_pdf,
        raising=False,
    )

    result = retry_run(run_dir, from_stage="render", output_format="html,pdf")

    assert not (run_dir / "report.html").exists()
    assert (run_dir / "transcript.pdf").is_file()
    assert (run_dir / "content_bundle.json").is_file()
    assert (run_dir / "transcript.html").is_file()
    assert not (run_dir / "nabaichuan.jsonl").exists()
    assert "content_bundle.json" in result.artifact_paths
    assert "transcript.html" in result.artifact_paths
    assert "nabaichuan.jsonl" not in result.artifact_paths


def test_retry_render_with_article_never_creates_new_report(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    _write_json(run_dir / "transcript_article.json", _article())

    def fake_render_transcript_html(*, ref, metadata, article, run_dir):
        html_path = run_dir / "transcript.html"
        html_path.write_text(f"<html>{article['sections'][0]['title']}</html>", encoding="utf-8")
        return html_path

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text(f"<html>{chapters['chapters'][0]['title']}</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(
        retry_module,
        "render_transcript_html",
        fake_render_transcript_html,
        raising=False,
    )
    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(run_dir, from_stage="render", output_format="html")

    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert (run_dir / "transcript.html").read_text(encoding="utf-8") == "<html>重试文章</html>"
    assert not (run_dir / "report.html").exists()
    assert "transcript_article" in bundle
    assert bundle["artifacts"]["transcript_html"] == "transcript.html"
    assert "nabaichuan.jsonl" not in result.artifact_paths
    assert not (run_dir / "nabaichuan.jsonl").exists()


def test_retry_legacy_summarization_rewrites_article_without_main_report(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    summary_styles = []

    def fake_generate_transcript_article(
        *,
        ref,
        metadata,
        transcript,
        chunks,
        run_dir,
        provider,
        model,
        **_options,
    ):
        article = _article()
        _write_json(run_dir / "transcript_article.json", article)
        return article

    def fake_summarize_article_sections(
        *,
        ref,
        metadata,
        article,
        run_dir,
        provider,
        model,
        style,
    ):
        assert provider == "codex-exec"
        assert model == "gpt-5.5"
        assert article["sections"][0]["title"] == "重试文章"
        summary_styles.append(style)
        return _chapters()

    def fake_render_transcript_html(*, ref, metadata, article, run_dir):
        html_path = run_dir / "transcript.html"
        html_path.write_text("<html>article</html>", encoding="utf-8")
        return html_path

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(
        retry_module,
        "generate_transcript_article",
        fake_generate_transcript_article,
        raising=False,
    )
    monkeypatch.setattr(
        retry_module,
        "summarize_article_sections",
        fake_summarize_article_sections,
        raising=False,
    )
    monkeypatch.setattr(
        retry_module,
        "render_transcript_html",
        fake_render_transcript_html,
        raising=False,
    )
    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(
        run_dir,
        from_stage="summarization",
        output_format="html",
        summary_template="观点提炼",
    )

    assert not (run_dir / "chapters.json").exists()
    assert summary_styles == []
    assert (run_dir / "transcript_article.json").is_file()
    assert (run_dir / "transcript.html").is_file()
    assert not (run_dir / "report.html").exists()
    assert (run_dir / "content_bundle.json").is_file()
    assert "content_bundle.json" in result.artifact_paths
    assert "nabaichuan.jsonl" not in result.artifact_paths
    assert not (run_dir / "notes.md").exists()
    assert not (run_dir / "nabaichuan.jsonl").exists()


def test_retry_missing_required_file_fails_with_sanitized_message(tmp_path):
    run_dir = _run_dir(tmp_path)

    (run_dir / "transcript_article.json").unlink()
    with pytest.raises(RetryError, match="transcript_article.json"):
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

    result = runner.invoke(
        app,
        [
            "retry",
            str(run_dir),
            "--from",
            "bundle",
            "--summary-template",
            "会议纪要",
            "--with-frames",
            "--with-diagrams",
        ],
    )

    assert result.exit_code == 0
    assert "Retried Bilifan run: BV1abcDEF12G_p1/runs/2026-06-09_120000" in result.output
    assert calls[0][0] == run_dir
    assert calls[0][1]["from_stage"] == "bundle"
    assert calls[0][1]["summary_template"] == "会议纪要"
    assert calls[0][1]["with_frames"] is True
    assert calls[0][1]["with_diagrams"] is True


def test_retry_invalid_format_fails_before_summarization_side_effects(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    calls = []

    def fake_summarize_article_sections(**kwargs):
        calls.append(kwargs)
        return _chapters()

    monkeypatch.setattr(
        retry_module,
        "summarize_article_sections",
        fake_summarize_article_sections,
        raising=False,
    )

    with pytest.raises(RetryError, match="--format"):
        retry_run(run_dir, from_stage="summarization", output_format="docx")

    assert calls == []
    assert not (run_dir / "chapters.json").exists()


def test_retry_legacy_summary_template_is_accepted_without_summary_side_effects(
    tmp_path, monkeypatch
):
    run_dir = _run_dir(tmp_path)
    calls = []

    def fake_summarize_article_sections(**kwargs):
        calls.append(kwargs)
        return _chapters()

    monkeypatch.setattr(
        retry_module,
        "summarize_article_sections",
        fake_summarize_article_sections,
        raising=False,
    )

    retry_run(run_dir, from_stage="render", output_format="html", summary_template="营销文案")

    assert calls == []
    assert not (run_dir / "chapters.json").exists()


def test_retry_render_html_only_does_not_expose_stale_pdf(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    (run_dir / "report.pdf").write_bytes(b"stale pdf")

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(run_dir, from_stage="render", output_format="html")
    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))

    assert "report.pdf" not in result.artifact_paths
    assert "report_pdf" not in bundle["artifacts"]
    assert (run_dir / "report.pdf").is_file()


def test_retry_render_html_only_removes_stale_article_pdfs(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())
    _write_json(run_dir / "transcript_article.json", _article())
    (run_dir / "transcript.pdf").write_bytes(b"stale transcript pdf")
    (run_dir / "report.pdf").write_bytes(b"stale report pdf")
    _write_json(run_dir / "content_bundle.json", {"stale": True})

    def fake_render_transcript_html(*, ref, metadata, article, run_dir):
        html_path = run_dir / "transcript.html"
        html_path.write_text("<html>transcript</html>", encoding="utf-8")
        return html_path

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>report</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "render_transcript_html", fake_render_transcript_html)
    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(run_dir, from_stage="render", output_format="html")
    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))

    assert "transcript.pdf" not in result.artifact_paths
    assert "report.pdf" not in result.artifact_paths
    assert "transcript_pdf" not in bundle["artifacts"]
    assert "report_pdf" not in bundle["artifacts"]
    assert not (run_dir / "transcript.pdf").exists()
    assert (run_dir / "report.pdf").is_file()


def test_retry_render_does_not_write_nabaichuan_jsonl(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)

    result = retry_run(run_dir, from_stage="render", output_format="html")

    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert "content_bundle.json" in bundle["artifacts"]["all"]
    assert "nabaichuan.jsonl" not in bundle["artifacts"]["all"]
    assert "nabaichuan.jsonl" not in result.artifact_paths
    assert not (run_dir / "nabaichuan.jsonl").exists()


def test_retry_require_pdf_failure_writes_failed_diagnostics(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    _write_json(run_dir / "chapters.json", _chapters())

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>retry</html>", encoding="utf-8")
        return html_path

    def fake_export_html_pdf(*, html_path, pdf_path):
        raise PdfExportError("Chrome failed for /Users/jack/report.html")

    monkeypatch.setattr(retry_module, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(
        retry_module,
        "export_html_pdf",
        fake_export_html_pdf,
        raising=False,
    )

    with pytest.raises(RetryError, match="Chrome failed"):
        retry_run(run_dir, from_stage="render", require_pdf=True)

    diagnostics = json.loads((run_dir / "retry_diagnostics.json").read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "PdfExportError"
    assert diagnostics["stage"] == "render"
    assert diagnostics["exit_code"] == 1
    assert "/Users/jack" not in diagnostics["sanitized_message"]


def test_retry_summarization_failure_writes_failed_diagnostics(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)

    def fake_generate_transcript_article(**kwargs):
        article = _article()
        _write_json(kwargs["run_dir"] / "transcript_article.json", article)
        return article

    def fake_summarize_article_sections(**kwargs):
        raise SummarizationError("CODEX_ACCESS_TOKEN=secret failed")

    monkeypatch.setattr(
        retry_module,
        "generate_transcript_article",
        fake_generate_transcript_article,
        raising=False,
    )
    monkeypatch.setattr(
        retry_module,
        "generate_transcript_article",
        fake_summarize_article_sections,
        raising=False,
    )

    with pytest.raises(RetryError, match="CODEX_ACCESS_TOKEN=<redacted>"):
        retry_run(run_dir, from_stage="summarization", output_format="html")

    diagnostics = json.loads((run_dir / "retry_diagnostics.json").read_text(encoding="utf-8"))
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
    (run_dir / "transcript.html").write_text("<html>stale transcript</html>", encoding="utf-8")
    (run_dir / "transcript.pdf").write_bytes(b"stale transcript pdf")
    (run_dir / "report.html").write_text("<html>stale</html>", encoding="utf-8")
    (run_dir / "report.pdf").write_bytes(b"stale pdf")
    _write_json(run_dir / "content_bundle.json", {"stale": True})

    def fake_generate_transcript_article(**kwargs):
        article = _article()
        _write_json(kwargs["run_dir"] / "transcript_article.json", article)
        return article

    def fake_summarize_article_sections(**kwargs):
        raise SummarizationError("summary failed")

    monkeypatch.setattr(
        retry_module,
        "generate_transcript_article",
        fake_generate_transcript_article,
        raising=False,
    )
    monkeypatch.setattr(
        retry_module,
        "generate_transcript_article",
        fake_summarize_article_sections,
        raising=False,
    )

    with pytest.raises(RetryError, match="summary failed"):
        retry_run(run_dir, from_stage="summarization", output_format="html")

    diagnostics = json.loads((run_dir / "retry_diagnostics.json").read_text(encoding="utf-8"))
    assert "report.html" not in diagnostics["artifact_paths"]
    assert "report.pdf" not in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in diagnostics["artifact_paths"]
    assert (run_dir / "transcript.html").exists()
    assert (run_dir / "transcript.pdf").exists()
    assert (run_dir / "report.html").exists()
    assert (run_dir / "report.pdf").exists()
    assert (run_dir / "content_bundle.json").exists()


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

    monkeypatch.setattr(retry_module, "render_transcript_html", fake_render_report_html)

    with pytest.raises(RetryError, match="render failed"):
        retry_run(run_dir, from_stage="render", output_format="html")

    diagnostics = json.loads((run_dir / "retry_diagnostics.json").read_text(encoding="utf-8"))
    assert "report.html" not in diagnostics["artifact_paths"]
    assert "report.pdf" not in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in diagnostics["artifact_paths"]


def test_retry_unusable_raw_never_calls_ai_and_preserves_old_delivery(tmp_path, monkeypatch):
    run_dir = _run_dir(tmp_path)
    raw = json.loads((run_dir / "transcript.json").read_text())
    raw["segments"][0]["text"] = "嗯"
    _write_json(run_dir / "transcript.json", raw)
    previous = _seed_existing_delivery(run_dir)
    monkeypatch.setattr(retry_module, "generate_transcript_article", lambda **kw: pytest.fail("unusable raw sent to AI"))
    with pytest.raises(RetryError, match="不可用"):
        retry_run(run_dir, from_stage="summarization", output_format="html")
    assert all((run_dir / name).read_bytes() == value for name, value in previous.items())


def test_bundle_retry_carries_same_article_warning_in_raw_archive_and_bundle(tmp_path):
    import zipfile
    run_dir = _run_dir(tmp_path)
    raw = json.loads((run_dir / "transcript.json").read_text())
    raw["segments"][0]["text"] += "请在 20 分钟内完成。"
    _write_json(run_dir / "transcript.json", raw)
    article = _article()
    article["sections"][0]["paragraphs"][0]["text"] += "请在 30 分钟内完成。"
    _write_json(run_dir / "transcript_article.json", article)
    result = retry_run(run_dir, from_stage="bundle", output_format="html")
    bundle = json.loads((run_dir / "content_bundle.json").read_text())
    quality = json.loads((run_dir / "quality.json").read_text())
    assert bundle["quality"] == quality
    assert quality["status"] == "needs_review"
    assert "quality_review_required" in result.warnings
    assert "需复查" in (run_dir / "transcript.txt").read_text()
    with zipfile.ZipFile(run_dir / "transcript_source.zip") as archive:
        assert json.loads(archive.read("quality.json")) == quality


def test_changed_completed_artifact_cannot_keep_success_marker(tmp_path):
    from bilifan.delivery import successful_delivery
    run_dir = _run_dir(tmp_path)
    retry_run(run_dir, from_stage="render", output_format="html")
    assert successful_delivery(run_dir)
    (run_dir / "transcript.html").write_text("<html>replacement incomplete article</html>")
    assert not successful_delivery(run_dir)


def test_retry_updates_latest_success_without_moving_back_to_an_older_run(tmp_path):
    import shutil
    old = _run_dir(tmp_path)
    video = old.parent.parent
    assert not (video / "latest.json").exists()
    retry_run(old, from_stage="render", output_format="html")
    assert json.loads((video / "latest.json").read_text())["run_id"] == old.name
    newer = old.parent / "2026-06-10_120000"
    shutil.copytree(old, newer)
    # A newer attempt exists but has not been delivered, so it cannot move latest.
    (newer / "completion.json").unlink()
    _write_json(newer / "run_state.json", {"status": "running"})
    assert json.loads((video / "latest.json").read_text())["run_id"] == old.name
    retry_run(newer, from_stage="render", output_format="html")
    assert json.loads((video / "latest.json").read_text())["run_id"] == newer.name
    retry_run(old, from_stage="render", output_format="html")
    assert json.loads((video / "latest.json").read_text())["run_id"] == newer.name
