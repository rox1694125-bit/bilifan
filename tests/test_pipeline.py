import json
from pathlib import Path

import pytest

import bilifan.pipeline as pipeline
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

    def fake_summarize_chunks(
        *,
        ref,
        metadata,
        chunks,
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
                    "title": "开场",
                    "start": 0,
                    "end": chunks["chunks"][0]["end"],
                    "timestamp_url": ref.timestamp_url(0),
                    "summary": "学习笔记摘要",
                    "key_points": ["要点"],
                    "quotes": [],
                    "visual_anchors": [],
                }
            ],
        }

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    def fake_export_report_pdf(*, html_path, pdf_path):
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summarize_chunks)
    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(pipeline, "export_report_pdf", fake_export_report_pdf)

    result = pipeline.run_summarize_pipeline(
        PipelineRequest(
            url="https://www.bilibili.com/video/BV1abcDEF12G",
            out=tmp_path,
            yes_i_understand=True,
        ),
        progress_callback=record_progress,
    )

    assert result.run_key.startswith("BV1abcDEF12G_p1/runs/")
    assert "report.html" in result.artifact_paths
    assert "report.pdf" in result.artifact_paths
    assert "transcript.txt" in result.artifact_paths
    assert "transcript.srt" in result.artifact_paths
    assert "notes.md" in result.artifact_paths
    assert "content_bundle.json" in result.artifact_paths
    assert "media/audio.mp3" in result.artifact_paths
    assert "nabaichuan.jsonl" in result.artifact_paths

    for artifact_name in (
        "metadata.json",
        "media/audio.mp3",
        "nabaichuan.jsonl",
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
        "chapters.json",
        "notes.md",
        "content_bundle.json",
        "diagnostics.json",
    ):
        assert (result.run_dir / artifact_name).is_file()

    bundle = json.loads((result.run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p1"
    assert bundle["artifacts"]["report_html"] == "report.html"
    assert bundle["artifacts"]["audio_mp3"] == "media/audio.mp3"
    assert bundle["summary"]["chapters"][0]["title"] == "开场"

    assert [
        (stage, status)
        for stage, status, _message in progress_events
        if status == "running"
    ] == [
        ("preflight", "running"),
        ("metadata", "running"),
        ("audio", "running"),
        ("transcript", "running"),
        ("chunking", "running"),
        ("summarization", "running"),
        ("render", "running"),
    ]


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

    def fake_summarize_chunks(**kwargs):
        raise pipeline.SummarizationError("codex exec failed")

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summarize_chunks)

    with pytest.raises(pipeline.PipelineRunError) as exc_info:
        pipeline.run_summarize_pipeline(
            PipelineRequest(
                url="https://www.bilibili.com/video/BV1abcDEF12G",
                out=tmp_path,
                yes_i_understand=True,
            )
        )

    assert "transcript.json" in exc_info.value.artifact_paths
    assert "transcript.txt" in exc_info.value.artifact_paths
    assert "transcript.srt" in exc_info.value.artifact_paths
    run_dir = exc_info.value.diagnostics_path.parent
    assert (run_dir / "transcript.txt").is_file()
    assert (run_dir / "transcript.srt").is_file()


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

    def fake_summarize_chunks(**kwargs):
        return {
            "style": "学习笔记",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "开场",
                    "start": 0,
                    "end": 120,
                    "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?t=0",
                    "summary": "摘要",
                    "key_points": ["要点"],
                    "quotes": [],
                    "visual_anchors": [],
                }
            ],
        }

    def fake_render_report_html(**kwargs):
        raise RuntimeError("template failed for /private/tmp/report.html")

    monkeypatch.setattr(pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    monkeypatch.setattr(pipeline, "download_current_part_audio", fake_download_current_part_audio)
    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    monkeypatch.setattr(pipeline, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summarize_chunks)
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
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
        "chapters.json",
        "notes.md",
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
