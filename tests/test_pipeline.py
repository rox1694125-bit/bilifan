import json
from pathlib import Path

import pytest

import bilifan.pipeline as pipeline
from bilifan.bundle import BundleError
from bilifan.chunking import LongVideoConfirmationRequired
from bilifan.pipeline import (
    PipelineRequest,
    PipelineResult,
    PipelineStage,
    default_progress,
)


def test_pipeline_request_defaults_for_web_and_cli(tmp_path):
    request = PipelineRequest(url="https://www.bilibili.com/video/BV1abcDEF12G", out=tmp_path)

    assert request.output_format == "html,pdf"
    assert request.transcriber == "auto"
    assert request.language == "auto"
    assert request.force_whisper is False
    assert request.llm_provider == "codex-exec"
    assert request.llm_model == "gpt-5.5"
    assert request.summary_template == "学习笔记"
    assert request.with_frames is False
    assert request.with_diagrams is False
    assert request.require_pdf is False
    assert request.allow_long_video is False
    assert request.yes_i_understand is False
    assert request.overwrite is False
    assert request.cookies_from_browser is None
    assert request.cookies_file is None


def test_pipeline_result_uses_relative_run_key(tmp_path):
    result = PipelineResult(
        run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
        run_dir=tmp_path / "outputs" / "BV1abcDEF12G_p1" / "runs" / "2026-06-08_120000",
        diagnostics_path=tmp_path / "diagnostics.json",
        artifact_paths=["report.html"],
        warnings=[],
    )

    assert result.run_key == "BV1abcDEF12G_p1/runs/2026-06-08_120000"
    assert result.artifact_paths == ["report.html"]


def test_default_progress_accepts_all_known_stages():
    for stage in PipelineStage:
        default_progress(stage.value, "running", f"{stage.value} running")


def _fake_transcript_article(end: float = 120.0) -> dict:
    return {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "开场",
                "start": 0,
                "end": end,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?t=0",
                "source_segment_start_index": 0,
                "source_segment_end_index": 0,
                "paragraphs": [{"text": "转写", "emphasis": []}],
                "key_terms": [],
                "warnings": [],
            }
        ],
        "warnings": [],
    }


@pytest.fixture(autouse=True)
def _article_first_defaults(monkeypatch):
    def fake_generate_transcript_article(
        *,
        ref,
        metadata,
        transcript,
        chunks,
        run_dir,
        provider="codex-exec",
        model="gpt-5.5",
    ):
        article = _fake_transcript_article(chunks["chunks"][0]["end"])
        (run_dir / "transcript_article.json").write_text(
            json.dumps(article, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return article

    def fake_summarize_article_sections(
        *,
        ref,
        metadata,
        article,
        run_dir,
        provider="codex-exec",
        model="gpt-5.5",
        style="学习笔记",
    ):
        return {
            "style": style,
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": article["sections"][0]["title"],
                    "start": article["sections"][0]["start"],
                    "end": article["sections"][0]["end"],
                    "timestamp_url": ref.timestamp_url(0),
                    "summary": "学习笔记摘要",
                    "key_points": ["要点"],
                    "quotes": [],
                    "visual_anchors": [],
                }
            ],
        }

    def fake_render_transcript_html(*, ref, metadata, article, run_dir):
        html_path = run_dir / "transcript.html"
        html_path.write_text("<html><body>transcript</body></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(
        pipeline,
        "generate_transcript_article",
        fake_generate_transcript_article,
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "summarize_article_sections",
        fake_summarize_article_sections,
        raising=False,
    )
    monkeypatch.setattr(
        pipeline,
        "render_transcript_html",
        fake_render_transcript_html,
        raising=False,
    )


def _install_minimal_successful_pipeline_fakes(monkeypatch) -> None:
    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-17T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "title": "Mock metadata title",
            "part_title": "Mock metadata title",
            "owner_name": "Mock Owner",
            "duration": 120,
            "subtitles": [],
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {"status": "ok"},
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0.0, "end": 120.0, "text": "转写"}],
            "transcript_check": {"status": "ok", "segment_count": 1},
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        return {
            "chunk_count": 1,
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0.0,
                    "end": 120.0,
                    "segments": [
                        {
                            "source_index": 0,
                            "start": 0.0,
                            "end": 120.0,
                            "text": "转写",
                        }
                    ],
                    "text": "转写",
                }
            ],
        }

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)


def test_metadata_done_message_includes_long_video_chunk_estimate():
    message = pipeline._metadata_done_message({"duration": 2.5 * 60 * 60})

    assert "Estimated summary chunks: 4-5" in message
    assert "require confirmation" in message


def test_pipeline_resolves_adapter_before_creating_run(tmp_path, monkeypatch):
    calls = {"parse": 0}

    class FakeAdapter:
        platform = "bilibili"

        def parse_url(self, url):
            calls["parse"] += 1
            from bilifan.sources.base import VideoRef

            return VideoRef(
                "bilibili",
                "BV1abcDEF12G",
                "p1",
                "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
                url,
            )

        def output_id(self, ref):
            return "BV1abcDEF12G_p1"

        def timestamp_url(self, ref, seconds):
            return f"{ref.canonical_url}&t={int(seconds)}"

    def fake_create_run(out, ref, *, overwrite=False):
        assert ref.output_id == "BV1abcDEF12G_p1"
        raise RuntimeError("stop")

    monkeypatch.setattr(pipeline, "resolve_source_adapter", lambda url: FakeAdapter())
    monkeypatch.setattr(pipeline, "create_run", fake_create_run)

    with pytest.raises(RuntimeError, match="stop"):
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
            )
        )

    assert calls["parse"] == 1


def test_run_summarize_pipeline_writes_artifacts_and_reports_progress(
    tmp_path, monkeypatch
):
    progress_events: list[tuple[str, str, str]] = []

    def record_progress(stage: str, status: str, message: str) -> None:
        progress_events.append((stage, status, message))

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": "123456",
            "title": "Mock metadata title",
            "part_title": "Mock metadata title",
            "owner_name": "Mock Owner",
            "description": "",
            "tags": [],
            "cover_url": "",
            "cover_path": "",
            "duration": 0,
            "parts": [],
            "subtitles": [],
            "yt_dlp_version": "mock",
            "ffmpeg_version": "",
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {
                "status": "ok",
                "metadata_seconds": metadata.get("duration"),
                "audio_seconds": 120,
                "difference_ratio": 0,
                "tolerance_ratio": 0.05,
                "attempts": 1,
            },
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [
                {
                    "start": 0.0,
                    "end": media["duration_seconds"],
                    "text": "转写",
                    "language": "zh",
                    "source": "whisper",
                }
            ],
            "transcript_check": {
                "status": "ok",
                "audio_seconds": media["duration_seconds"],
                "last_segment_end": media["duration_seconds"],
                "difference_seconds": 0,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        return {
            "strategy": {
                "mode": "single_pass",
                "single_pass_max_seconds": 2700,
                "min_chunk_seconds": 1800,
                "max_chunk_seconds": 2700,
                "target_chunk_seconds": None,
                "token_budget": 24000,
                "long_video_confirmed": long_video_confirmed or allow_long_video,
                "allow_long_video": allow_long_video,
            },
            "media_duration_seconds": media["duration_seconds"],
            "transcript_duration_seconds": media["duration_seconds"],
            "chunk_count": 1,
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0.0,
                    "end": media["duration_seconds"],
                    "duration_seconds": media["duration_seconds"],
                    "segment_start_index": 0,
                    "segment_end_index": 0,
                    "segment_count": 1,
                    "estimated_tokens": 1,
                    "segments": [
                        {
                            "source_index": 0,
                            "start": 0.0,
                            "end": media["duration_seconds"],
                            "text": "转写",
                        }
                    ],
                    "text": "转写",
                }
            ],
        }

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    def fake_export_html_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(pipeline, "export_html_pdf", fake_export_html_pdf, raising=False)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            yes_i_understand=True,
            with_frames=True,
            with_diagrams=True,
        ),
        progress_callback=record_progress,
    )

    assert result.run_key.startswith("BV1abcDEF12G_p1/runs/")
    assert "transcript_article.json" in result.artifact_paths
    assert "transcript.html" in result.artifact_paths
    assert "report.html" in result.artifact_paths
    assert "report.pdf" in result.artifact_paths
    assert "content_bundle.json" in result.artifact_paths
    assert "media/audio.mp3" in result.artifact_paths
    assert "nabaichuan.jsonl" not in result.artifact_paths
    assert "notes.md" not in result.artifact_paths
    assert "transcript.txt" not in result.artifact_paths
    assert "transcript.srt" not in result.artifact_paths

    for artifact_name in (
        "metadata.json",
        "media/audio.mp3",
        "transcript.json",
        "chunks.json",
        "transcript_article.json",
        "chapters.json",
        "transcript.html",
        "report.html",
        "content_bundle.json",
        "diagnostics.json",
    ):
        assert (result.run_dir / artifact_name).is_file()
    for legacy_artifact_name in (
        "nabaichuan.jsonl",
        "notes.md",
        "transcript.txt",
        "transcript.srt",
    ):
        assert not (result.run_dir / legacy_artifact_name).exists()

    bundle = json.loads((result.run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    diagnostics = json.loads((result.run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p1"
    assert bundle["artifacts"]["transcript_article_json"] == "transcript_article.json"
    assert bundle["artifacts"]["transcript_html"] == "transcript.html"
    assert bundle["artifacts"]["report_html"] == "report.html"
    assert bundle["artifacts"]["audio_mp3"] == "media/audio.mp3"
    assert bundle["transcript_article"]["sections"][0]["title"] == "开场"
    assert bundle["summary"]["chapters"][0]["title"] == "开场"
    assert bundle["summary"]["chapters"][0]["diagram"]["caption"] == "图解：开场"
    assert "frames_unavailable" in diagnostics["warnings"]

    assert [
        (stage, status)
        for stage, status, _message in progress_events
        if status == "running"
    ] == [
        ("preflight", "running"),
        ("metadata", "running"),
        ("transcript", "running"),
        ("audio", "running"),
        ("transcript", "running"),
        ("chunking", "running"),
        ("summarization", "running"),
        ("render", "running"),
    ]


def test_pipeline_exports_transcript_and_report_pdfs_when_pdf_requested(
    tmp_path, monkeypatch
):
    _install_minimal_successful_pipeline_fakes(monkeypatch)

    def fake_render_transcript_html(*, ref, metadata, article, run_dir):
        html_path = run_dir / "transcript.html"
        html_path.write_text("<html><body>transcript</body></html>", encoding="utf-8")
        return html_path

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    def fake_export_html_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(f"PDF for {html_path.name}".encode())
        return pdf_path

    monkeypatch.setattr(pipeline, "render_transcript_html", fake_render_transcript_html)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(pipeline, "export_html_pdf", fake_export_html_pdf, raising=False)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            output_format="html,pdf",
            yes_i_understand=True,
        )
    )

    assert "transcript.pdf" in result.artifact_paths
    assert "report.pdf" in result.artifact_paths
    assert (result.run_dir / "transcript.pdf").read_bytes() == b"PDF for transcript.html"
    assert (result.run_dir / "report.pdf").read_bytes() == b"PDF for report.html"


def test_pipeline_promotes_transcript_quality_warning_to_diagnostics(
    tmp_path, monkeypatch
):
    _install_minimal_successful_pipeline_fakes(monkeypatch)

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0.0, "end": 120.0, "text": "转写"}],
            "transcript_check": {"status": "ok", "segment_count": 1},
            "transcript_quality_check": {"status": "suspect_wrong_route"},
            "transcription_attempts": [
                {
                    "model": "turbo",
                    "language": "zh",
                    "backend": "openai-whisper",
                    "quality_status": "suspect_wrong_route",
                    "selected": True,
                }
            ],
        }

    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            output_format="html",
            yes_i_understand=True,
        )
    )

    diagnostics = json.loads((result.run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    assert "transcript_quality_suspect_wrong_route" in result.warnings
    assert "transcript_quality_suspect_wrong_route" in diagnostics["warnings"]
    assert diagnostics["transcript_check"]["status"] == "ok"


def test_pipeline_pdf_failure_warns_when_not_required(tmp_path, monkeypatch):
    _install_minimal_successful_pipeline_fakes(monkeypatch)

    def fake_export_html_pdf(*, html_path, pdf_path):
        raise pipeline.PdfExportError("pdf failed")

    monkeypatch.setattr(pipeline, "export_html_pdf", fake_export_html_pdf, raising=False)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            output_format="html,pdf",
            yes_i_understand=True,
        )
    )

    assert result.warnings.count("pdf_failed") == 1
    assert "transcript.html" in result.artifact_paths
    assert "report.html" in result.artifact_paths
    assert (result.run_dir / "transcript.html").is_file()
    assert (result.run_dir / "report.html").is_file()
    assert not (result.run_dir / "transcript.pdf").exists()
    assert not (result.run_dir / "report.pdf").exists()


def test_pipeline_require_pdf_fails_if_transcript_pdf_fails(tmp_path, monkeypatch):
    _install_minimal_successful_pipeline_fakes(monkeypatch)

    def fake_export_html_pdf(*, html_path, pdf_path):
        if pdf_path.name == "transcript.pdf":
            raise pipeline.PdfExportError("pdf failed")
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(pipeline, "export_html_pdf", fake_export_html_pdf, raising=False)

    with pytest.raises(pipeline.PipelineRunError) as exc_info:
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                output_format="html,pdf",
                require_pdf=True,
                yes_i_understand=True,
            )
        )

    assert exc_info.value.exit_code == 1
    assert "transcript.html" in exc_info.value.artifact_paths
    diagnostics = json.loads(exc_info.value.diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "PdfExportError"
    assert diagnostics["warnings"] == ["pdf_failed"]


def test_pipeline_bundle_failure_writes_diagnostics_with_completed_artifacts(
    tmp_path, monkeypatch
):
    _install_minimal_successful_pipeline_fakes(monkeypatch)

    def fake_export_html_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    def fake_write_content_bundle(**kwargs):
        raise BundleError("bundle failed")

    monkeypatch.setattr(pipeline, "export_html_pdf", fake_export_html_pdf, raising=False)
    monkeypatch.setattr(pipeline, "write_content_bundle", fake_write_content_bundle)

    with pytest.raises(pipeline.PipelineRunError, match="bundle failed") as exc_info:
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                output_format="html,pdf",
                yes_i_understand=True,
            )
        )

    diagnostics = json.loads(exc_info.value.diagnostics_path.read_text(encoding="utf-8"))
    assert exc_info.value.exit_code == 1
    assert diagnostics["stage"] == "bundle"
    assert diagnostics["error_type"] == "BundleError"
    assert "transcript.html" in diagnostics["artifact_paths"]
    assert "report.html" in diagnostics["artifact_paths"]
    assert "transcript.pdf" in diagnostics["artifact_paths"]
    assert "report.pdf" in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in diagnostics["artifact_paths"]
    assert "content_bundle.json" not in exc_info.value.artifact_paths
    assert not (exc_info.value.diagnostics_path.parent / "content_bundle.json").exists()


def test_run_summarize_pipeline_uses_subtitles_without_downloading_audio(
    tmp_path, monkeypatch
):
    progress_events: list[tuple[str, str, str]] = []

    def record_progress(stage: str, status: str, message: str) -> None:
        progress_events.append((stage, status, message))

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-16T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": "123456",
            "title": "Subtitle video",
            "part_title": "Subtitle video",
            "owner_name": "Mock Owner",
            "description": "",
            "tags": [],
            "cover_url": "",
            "cover_path": "",
            "duration": 120,
            "parts": [],
            "subtitles": [
                {
                    "language": "zh-Hans",
                    "url": "https://example.test/subtitle.json",
                    "ext": "json",
                }
            ],
            "yt_dlp_version": "mock",
            "ffmpeg_version": "",
        }

    def forbidden_download_current_part_audio(*args, **kwargs):
        raise AssertionError("audio should not be downloaded when subtitles are usable")

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        assert force_whisper is False
        assert transcriber == "auto"
        assert media["duration_seconds"] == metadata["duration"]
        assert not media.get("audio_path")
        return {
            "source": "bilibili-subtitle",
            "language": "zh-Hans",
            "model": None,
            "segments": [
                {
                    "start": 0.0,
                    "end": 120.0,
                    "text": "字幕内容",
                    "language": "zh-Hans",
                    "source": "bilibili-subtitle",
                }
            ],
            "transcript_check": {
                "status": "ok",
                "audio_seconds": 120,
                "last_segment_end": 120,
                "difference_seconds": 0,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        assert media["duration_seconds"] == 120
        return {
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0,
                    "end": 120,
                    "text": "字幕内容",
                    "segments": [
                        {"source_index": 0, "start": 0, "end": 120, "text": "字幕内容"}
                    ],
                }
            ]
        }

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(
        pipeline,
        "download_current_part_audio",
        forbidden_download_current_part_audio,
    )
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            output_format="html",
            yes_i_understand=True,
        ),
        progress_callback=record_progress,
    )

    assert "transcript_article.json" in result.artifact_paths
    assert "transcript.html" in result.artifact_paths
    assert "report.html" in result.artifact_paths
    assert "transcript.txt" not in result.artifact_paths
    assert "content_bundle.json" in result.artifact_paths
    assert "media/audio.mp3" not in result.artifact_paths
    assert not any(path.endswith(".mp3") for path in result.artifact_paths)
    assert not (result.run_dir / "media" / "audio.mp3").exists()

    diagnostics = json.loads((result.run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    bundle = json.loads((result.run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert diagnostics["duration_check"]["status"] == "metadata_only"
    assert "audio_mp3" not in bundle["artifacts"]
    assert ("audio", "running") not in [
        (stage, status) for stage, status, _message in progress_events
    ]


def test_run_summarize_pipeline_force_whisper_downloads_audio_before_transcript(
    tmp_path, monkeypatch
):
    call_order: list[str] = []

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "title": "Subtitle video",
            "part_title": "Subtitle video",
            "owner_name": "Mock Owner",
            "duration": 120,
            "subtitles": [
                {
                    "language": "zh-Hans",
                    "url": "https://example.test/subtitle.json",
                    "ext": "json",
                }
            ],
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        call_order.append("audio")
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {"status": "ok"},
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        call_order.append("transcript")
        assert force_whisper is True
        assert media["audio_path"].endswith(".mp3")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0.0, "end": 120.0, "text": "转写"}],
            "transcript_check": {"status": "ok"},
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        return {
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0,
                    "end": 120,
                    "text": "转写",
                    "segments": [],
                }
            ]
        }

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            output_format="html",
            force_whisper=True,
            yes_i_understand=True,
        )
    )

    assert call_order[:2] == ["audio", "transcript"]
    assert "media/audio.mp3" in result.artifact_paths


def test_summarization_failure_keeps_transcript_exports_in_artifacts(
    tmp_path, monkeypatch
):
    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "title": "Mock metadata title",
            "part_title": "Mock metadata title",
            "owner_name": "Mock Owner",
            "duration": 120,
            "subtitles": [],
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {"status": "ok"},
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0.0, "end": 120.0, "text": "转写"}],
            "transcript_check": {"status": "ok"},
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        return {
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0,
                    "end": 120,
                    "text": "转写",
                    "segments": [],
                }
            ]
        }

    def fake_summarize_article_sections(**kwargs):
        raise pipeline.SummarizationError("codex exec failed")

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "summarize_article_sections", fake_summarize_article_sections)

    with pytest.raises(pipeline.PipelineRunError) as exc_info:
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                yes_i_understand=True,
            )
        )

    assert "transcript.json" in exc_info.value.artifact_paths
    assert "transcript_article.json" in exc_info.value.artifact_paths
    run_dir = exc_info.value.diagnostics_path.parent
    assert (run_dir / "transcript_article.json").is_file()
    assert not (run_dir / "transcript.txt").exists()
    assert not (run_dir / "transcript.srt").exists()


def test_render_failure_keeps_completed_exports_in_artifacts(tmp_path, monkeypatch):
    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "title": "Mock metadata title",
            "part_title": "Mock metadata title",
            "owner_name": "Mock Owner",
            "duration": 120,
            "subtitles": [],
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 120,
            "duration_check": {"status": "ok"},
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [{"start": 0.0, "end": 120.0, "text": "转写"}],
            "transcript_check": {"status": "ok"},
        }

    def fake_build_chunks(
        transcript,
        media,
        *,
        allow_long_video=False,
        long_video_confirmed=False,
    ):
        return {
            "chunks": [
                {
                    "chunk_index": 1,
                    "start": 0,
                    "end": 120,
                    "text": "转写",
                    "segments": [],
                }
            ]
        }

    def fake_render_report_html(**kwargs):
        raise RuntimeError("template failed for /private/tmp/report.html")

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)

    with pytest.raises(pipeline.PipelineRunError) as exc_info:
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                yes_i_understand=True,
            )
        )

    assert exc_info.value.artifact_paths == [
        "diagnostics.json",
        "metadata.json",
        ".bilifan/cache/BV1abcDEF12G_p1.mp3",
        "transcript.json",
        "chunks.json",
        "transcript_article.json",
        "chapters.json",
        "transcript.html",
    ]
    diagnostics = json.loads(exc_info.value.diagnostics_path.read_text(encoding="utf-8"))
    assert diagnostics["error_type"] == "RenderError"
    assert diagnostics["stage"] == "render"
    assert "/private/tmp" not in diagnostics["sanitized_message"]


def test_run_summarize_pipeline_without_long_video_callback_does_not_write_failure_diagnostics(
    tmp_path, monkeypatch
):
    progress_events: list[tuple[str, str, str]] = []

    def record_progress(stage: str, status: str, message: str) -> None:
        progress_events.append((stage, status, message))

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": "123456",
            "title": "Long video",
            "part_title": "Long video",
            "owner_name": "Mock Owner",
            "description": "",
            "tags": [],
            "cover_url": "",
            "cover_path": "",
            "duration": 100 * 60,
            "parts": [],
            "subtitles": [],
            "yt_dlp_version": "mock",
            "ffmpeg_version": "",
        }

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": 100 * 60,
            "duration_check": {
                "status": "ok",
                "metadata_seconds": metadata.get("duration"),
                "audio_seconds": 100 * 60,
                "difference_ratio": 0,
                "tolerance_ratio": 0.05,
                "attempts": 1,
            },
        }

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        if not media.get("audio_path"):
            raise pipeline.TranscriptError("Audio file for Whisper is missing.")
        return {
            "source": "whisper",
            "language": "zh",
            "model": "turbo",
            "segments": [
                {
                    "start": 0.0,
                    "end": media["duration_seconds"],
                    "text": "long transcript",
                    "language": "zh",
                    "source": "whisper",
                }
            ],
            "transcript_check": {
                "status": "ok",
                "audio_seconds": media["duration_seconds"],
                "last_segment_end": media["duration_seconds"],
                "difference_seconds": 0,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
        }

    monkeypatch.setattr(
        pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata
    )
    monkeypatch.setattr(
        pipeline, "download_current_part_audio", fake_download_current_part_audio
    )
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)

    with pytest.raises(LongVideoConfirmationRequired):
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                output_format="html",
            ),
            progress_callback=record_progress,
        )

    latest = json.loads(
        (tmp_path / "BV1abcDEF12G_p1" / "latest.json").read_text(encoding="utf-8")
    )
    run_dir = tmp_path / "BV1abcDEF12G_p1" / latest["run_dir"]

    assert not (run_dir / "diagnostics.json").exists()
    assert ("chunking", "failed") in [
        (stage, status) for stage, status, _message in progress_events
    ]
