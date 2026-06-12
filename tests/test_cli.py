import json

from typer.testing import CliRunner

import bilifan.cli as cli
import bilifan.pipeline as pipeline
from bilifan.cli import app
from bilifan.media import MediaDownloadError
from bilifan.metadata import MetadataIngestError
from bilifan.summarizer import SummarizationError
from bilifan.transcript import TranscriptError


runner = CliRunner()
URL = "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999"
REAL_BILIBILI_URLS = [
    (
        "https://www.bilibili.com/video/BV14kVE6eEtC"
        "?spm_id_from=333.788.player.player_end_recommend"
        "&vd_source=39fc5b438dea96faea88e7841fb3d0ca"
        "&trackid=web_related_0.router-related-2589621-kz84p.1780846547972.446",
        "BV14kVE6eEtC_p1",
    ),
    (
        "https://www.bilibili.com/video/BV1xuVC6AEbg/?spm_id_from=333.1391.0.0",
        "BV1xuVC6AEbg_p1",
    ),
    (
        "https://www.bilibili.com/video/BV1ETEF6VEHu/?spm_id_from=333.1391.0.0",
        "BV1ETEF6VEHu_p1",
    ),
]


def _install_fake_metadata_fetch(monkeypatch, *, title="Mock metadata title"):
    calls = []

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        calls.append(
            {
                "ref": ref,
                "run_dir": run_dir,
                "cookies_from_browser": cookies_from_browser,
                "cookies_file": cookies_file,
            }
        )
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": "123456",
            "title": title,
            "part_title": title,
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

    monkeypatch.setattr(
        pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata
    )
    return calls


def _install_fake_audio_download(monkeypatch, *, duration_seconds=120):
    calls = []

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        calls.append(
            {
                "ref": ref,
                "metadata": metadata,
                "run_dir": run_dir,
                "cookies_from_browser": cookies_from_browser,
                "cookies_file": cookies_file,
            }
        )
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": duration_seconds,
            "duration_check": {
                "status": "ok",
                "metadata_seconds": metadata.get("duration"),
                "audio_seconds": duration_seconds,
                "difference_ratio": 0,
                "tolerance_ratio": 0.05,
                "attempts": 1,
            },
        }

    monkeypatch.setattr(
        pipeline, "download_current_part_audio", fake_download_current_part_audio
    )
    return calls


def _install_fake_transcript_build(monkeypatch):
    calls = []

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        calls.append(
            {
                "metadata": metadata,
                "media": media,
                "run_dir": run_dir,
                "force_whisper": force_whisper,
                "language": language,
                "transcriber": transcriber,
            }
        )
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

    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)
    return calls


def _install_fake_summarize_chunks(monkeypatch):
    calls = []

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
        calls.append(
            {
                "ref": ref,
                "metadata": metadata,
                "chunks": chunks,
                "run_dir": run_dir,
                "provider": provider,
                "model": model,
                "style": style,
            }
        )
        partial_dir = run_dir / "partial_summaries"
        partial_dir.mkdir(parents=True, exist_ok=True)
        (partial_dir / "chunk_001.json").write_text(
            json.dumps(
                {
                    "chunk_index": 1,
                    "chapters": [
                        {
                            "title": "开场",
                            "start": 0,
                            "end": chunks["chunks"][0]["end"],
                            "summary": "学习笔记摘要",
                            "key_points": ["要点"],
                            "quotes": [],
                            "visual_anchors": [],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
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

    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summarize_chunks)
    return calls


def _install_fake_report_render(monkeypatch, *, pdf_success=True):
    calls = []

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        calls.append(
            {
                "stage": "html",
                "ref": ref,
                "metadata": metadata,
                "transcript": transcript,
                "chapters": chapters,
                "run_dir": run_dir,
            }
        )
        html_path = run_dir / "report.html"
        html_path.write_text("<html><body>report</body></html>", encoding="utf-8")
        return html_path

    def fake_export_report_pdf(*, html_path, pdf_path):
        calls.append({"stage": "pdf", "html_path": html_path, "pdf_path": pdf_path})
        if not pdf_success:
            raise cli.PdfExportError("Chrome failed for /Users/jack/report.html")
        pdf_path.write_bytes(b"%PDF")
        return pdf_path

    monkeypatch.setattr(pipeline, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(pipeline, "export_report_pdf", fake_export_report_pdf)
    return calls


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output


def test_summarize_declines_local_processing_consent_without_writing_config(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        ["summarize", URL, "--out", str(outputs)],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "local processing consent" in result.output
    assert "Codex CLI" in result.output
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_writes_metadata_json_with_yes_flag(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch, title="CLI metadata title")
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "Prepared Bilifan run:" in result.output
    assert "BV1abcDEF12G_p2/runs/" in result.output
    assert str(outputs) not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

    assert run_dir.is_dir()
    assert diagnostics["error_type"] is None
    assert diagnostics["exit_code"] == 0
    assert diagnostics["stage"] == "render"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["duration_check"]["status"] == "ok"
    assert diagnostics["transcript_check"]["status"] == "ok"
    assert diagnostics["artifact_paths"] == [
        "diagnostics.json",
        "metadata.json",
        "media/audio.mp3",
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
        "chapters.json",
        "notes.md",
        "report.html",
        "report.pdf",
        "content_bundle.json",
        "nabaichuan.jsonl",
    ]
    assert diagnostics["warnings"] == []
    assert metadata["input_url_sanitized"] == (
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2"
    )
    assert metadata["video_id"] == "BV1abcDEF12G"
    assert metadata["part_index"] == 2
    assert metadata["title"] == "CLI metadata title"
    transcript = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))
    assert transcript["source"] == "whisper"
    assert transcript["segments"][0]["text"] == "转写"
    assert (run_dir / "transcript.txt").is_file()
    assert (run_dir / "transcript.srt").is_file()
    chunks = json.loads((run_dir / "chunks.json").read_text(encoding="utf-8"))
    assert chunks["strategy"]["mode"] == "single_pass"
    assert chunks["chunk_count"] == 1
    chapters = json.loads((run_dir / "chapters.json").read_text(encoding="utf-8"))
    assert chapters["style"] == "学习笔记"
    assert chapters["chapters"][0]["title"] == "开场"
    assert (run_dir / "notes.md").is_file()
    assert (run_dir / "report.html").is_file()
    assert (run_dir / "report.pdf").is_file()
    assert (run_dir / "media" / "audio.mp3").is_file()
    assert (run_dir / "nabaichuan.jsonl").is_file()
    bundle = json.loads((run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p2"
    assert bundle["artifacts"]["audio_mp3"] == "media/audio.mp3"
    assert bundle["provenance"]["llm_provider"] == "codex-exec"
    assert bundle["provenance"]["llm_model"] == "gpt-5.5"
    assert (config_home / "config.json").exists()


def test_summarize_accepts_mvp_public_flags_before_later_stages(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    transcript_calls = _install_fake_transcript_build(monkeypatch)
    summary_calls = _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--format",
            "html,pdf",
            "--transcriber",
            "auto",
            "--language",
            "en",
            "--force-whisper",
            "--llm-provider",
            "codex-exec",
            "--llm-model",
            "gpt-5.5",
            "--summary-template",
            "教程步骤",
            "--with-frames",
            "--with-diagrams",
            "--require-pdf",
            "--allow-long-video",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "No such option" not in result.output
    assert "Prepared Bilifan run:" in result.output
    assert transcript_calls[0]["force_whisper"] is True
    assert transcript_calls[0]["transcriber"] == "auto"
    assert transcript_calls[0]["language"] == "en"
    assert summary_calls[0]["provider"] == "codex-exec"
    assert summary_calls[0]["model"] == "gpt-5.5"
    assert summary_calls[0]["style"] == "教程步骤"


def test_summarize_prepares_runs_for_real_bilibili_urls(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

    for url, output_id in REAL_BILIBILI_URLS:
        result = runner.invoke(
            app,
            ["summarize", url, "--yes-i-understand", "--out", str(outputs)],
            env={"BILIFAN_CONFIG_HOME": str(config_home)},
        )

        assert result.exit_code == 0
        assert f"{output_id}/runs/" in result.output
        assert "spm_id_from" not in result.output
        assert "vd_source" not in result.output
        assert "trackid" not in result.output

        video_dir = outputs / output_id
        latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
        diagnostics_path = video_dir / latest["run_dir"] / "diagnostics.json"
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        bvid, part = output_id.rsplit("_p", 1)

        assert latest["input_url_sanitized"] == (
            f"https://www.bilibili.com/video/{bvid}?p={part}"
        )
        assert diagnostics["video_id"] == bvid
        assert diagnostics["part_index"] == int(part)
        assert diagnostics["stage"] == "render"


def test_summarize_records_cookie_notice_without_storing_cookie_file_name(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    calls = _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    config_text = (config_home / "config.json").read_text(encoding="utf-8")
    assert "local_processing_notice_accepted_at" in config_text
    assert "cookies_notice_accepted_at" in config_text
    assert "bili-cookies.txt" not in config_text
    assert "/Users/jack" not in config_text
    assert calls[0]["cookies_file"].as_posix() == "/Users/jack/Downloads/bili-cookies.txt"
    assert "bili-cookies.txt" not in result.output
    assert "/Users/jack" not in result.output


def test_summarize_invalid_url_writes_sanitized_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    invalid_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G/extra"
        "?p=2&vd_source=tracking-secret"
    )

    result = runner.invoke(
        app,
        ["summarize", invalid_url, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    error_runs = list((outputs / "_errors" / "runs").iterdir())
    assert len(error_runs) == 1

    diagnostics = json.loads(
        (error_runs[0] / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics["error_type"] == "InputError"
    assert diagnostics["exit_code"] == 2
    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == ""
    assert diagnostics["part_index"] == 0
    assert "vd_source" not in diagnostics["sanitized_message"]


def test_summarize_invalid_url_requires_consent_before_writing_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--out",
            str(outputs),
        ],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_invalid_url_retries_error_run_collision_without_leaking_path(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    original_create_error_run = pipeline.create_error_run
    calls = 0

    def fake_create_error_run(out_dir, *, now=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileExistsError("/Users/jack/outputs/_errors/runs/collision")
        return original_create_error_run(out_dir, now=now)

    monkeypatch.setattr(pipeline, "create_error_run", fake_create_error_run)

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert calls == 2
    assert "/Users/jack" not in result.output
    assert "collision" not in result.output
    assert len(list((outputs / "_errors" / "runs").glob("*/diagnostics.json"))) == 1


def test_summarize_metadata_failure_writes_sanitized_diagnostics_without_leaks(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=2&vd_source=tracking-secret&token=secret-token"
    )

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        raise MetadataIngestError(
            "yt-dlp failed for "
            f"{url} with --cookies-file /Users/jack/Downloads/bili-cookies.txt "
            "Cookie: SESSDATA=secret"
        )

    monkeypatch.setattr(
        pipeline, "fetch_current_part_metadata", fake_fetch_current_part_metadata
    )

    result = runner.invoke(
        app,
        [
            "summarize",
            url,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "yt-dlp failed" in result.output
    assert "vd_source" not in result.output
    assert "secret-token" not in result.output
    assert "bili-cookies.txt" not in result.output
    assert "/Users/jack" not in result.output
    assert "SESSDATA=secret" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert not (run_dir / "metadata.json").exists()
    assert diagnostics["error_type"] == "MetadataIngestError"
    assert diagnostics["exit_code"] == 1
    assert diagnostics["stage"] == "metadata"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["artifact_paths"] == ["diagnostics.json"]
    assert "vd_source" not in diagnostics["sanitized_message"]
    assert "secret-token" not in diagnostics["sanitized_message"]
    assert "bili-cookies.txt" not in diagnostics["sanitized_message"]
    assert "/Users/jack" not in diagnostics["sanitized_message"]


def test_summarize_audio_failure_writes_diagnostics_after_metadata(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        raise MediaDownloadError(
            "audio duration differs from metadata for "
            "https://www.bilibili.com/video/BV1abcDEF12G?p=2&vd_source=secret "
            "--cookies-file /Users/jack/Downloads/bili-cookies.txt",
            duration_check={
                "status": "duration_mismatch",
                "metadata_seconds": 100,
                "audio_seconds": 106,
                "difference_ratio": 0.06,
                "tolerance_ratio": 0.05,
                "attempts": 2,
            },
        )

    monkeypatch.setattr(
        pipeline, "download_current_part_audio", fake_download_current_part_audio
    )

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "duration differs" in result.output
    assert "vd_source" not in result.output
    assert "/Users/jack" not in result.output
    assert "bili-cookies.txt" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "metadata.json").is_file()
    assert diagnostics["error_type"] == "MediaDownloadError"
    assert diagnostics["exit_code"] == 1
    assert diagnostics["stage"] == "media"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["duration_check"]["status"] == "duration_mismatch"
    assert diagnostics["artifact_paths"] == ["diagnostics.json", "metadata.json"]
    assert "vd_source" not in diagnostics["sanitized_message"]
    assert "/Users/jack" not in diagnostics["sanitized_message"]
    assert "bili-cookies.txt" not in diagnostics["sanitized_message"]


def test_summarize_transcript_failure_writes_diagnostics_after_media(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch, duration_seconds=120)
    _install_fake_summarize_chunks(monkeypatch)

    def fake_build_transcript(
        metadata,
        media,
        run_dir,
        *,
        force_whisper=False,
        language="auto",
        transcriber="auto",
    ):
        raise TranscriptError(
            "transcript appears incomplete for /private/tmp/audio.mp3",
            transcript_check={
                "status": "transcript_incomplete",
                "audio_seconds": 120,
                "last_segment_end": 60,
                "difference_seconds": 60,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
        )

    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "transcript appears incomplete" in result.output
    assert "/private/tmp" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "metadata.json").is_file()
    assert (run_dir / ".bilifan" / "cache" / "BV1abcDEF12G_p2.mp3").is_file()
    assert not (run_dir / "transcript.json").exists()
    assert diagnostics["error_type"] == "TranscriptError"
    assert diagnostics["exit_code"] == 1
    assert diagnostics["stage"] == "transcript"
    assert diagnostics["duration_check"]["status"] == "ok"
    assert diagnostics["transcript_check"]["status"] == "transcript_incomplete"
    assert diagnostics["artifact_paths"] == [
        "diagnostics.json",
        "metadata.json",
        ".bilifan/cache/BV1abcDEF12G_p2.mp3",
    ]
    assert "/private/tmp" not in diagnostics["sanitized_message"]


def test_summarize_incomplete_transcript_writes_file_with_warning(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch, duration_seconds=120)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

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
                    "end": 60.0,
                    "text": "partial",
                    "language": "zh",
                    "source": "whisper",
                }
            ],
            "transcript_check": {
                "status": "transcript_incomplete",
                "audio_seconds": 120,
                "last_segment_end": 60,
                "difference_seconds": 60,
                "tolerance_seconds": 10,
                "segment_count": 1,
            },
        }

    monkeypatch.setattr(pipeline, "build_transcript", fake_build_transcript)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    transcript = json.loads((run_dir / "transcript.json").read_text(encoding="utf-8"))

    assert transcript["transcript_check"]["status"] == "transcript_incomplete"
    assert diagnostics["exit_code"] == 0
    assert diagnostics["transcript_check"]["status"] == "transcript_incomplete"
    assert diagnostics["stage"] == "render"
    assert (run_dir / "chunks.json").is_file()
    assert (run_dir / "chapters.json").is_file()
    assert (run_dir / "report.html").is_file()
    assert diagnostics["warnings"] == ["transcript_incomplete"]


def test_summarize_chunking_confirmation_decline_writes_diagnostics(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch, duration_seconds=90 * 60)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "Prepared Bilifan run:" in result.output

    config_home_2 = tmp_path / "config-home-2"
    result = runner.invoke(
        app,
        ["summarize", URL, "--out", str(outputs), "--overwrite"],
        input="y\nn\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home_2)},
    )

    assert result.exit_code == 1
    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert diagnostics["error_type"] == "ChunkingError"
    assert diagnostics["stage"] == "chunking"
    assert diagnostics["warnings"] == ["chunking_confirmation_required"]
    assert not (run_dir / "chunks.json").exists()


def test_summarize_pdf_failure_is_warning_when_pdf_is_not_required(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch, pdf_success=False)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "report.html").is_file()
    assert not (run_dir / "report.pdf").exists()
    assert (run_dir / "content_bundle.json").is_file()
    assert diagnostics["stage"] == "render"
    assert diagnostics["warnings"] == ["pdf_failed"]
    assert "report.html" in diagnostics["artifact_paths"]
    assert "content_bundle.json" in diagnostics["artifact_paths"]
    assert "nabaichuan.jsonl" in diagnostics["artifact_paths"]


def test_summarize_require_pdf_returns_nonzero_when_pdf_fails(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    _install_fake_report_render(monkeypatch, pdf_success=False)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--require-pdf",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "Chrome failed" in result.output
    assert "/Users/jack" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "report.html").is_file()
    assert not (run_dir / "report.pdf").exists()
    assert diagnostics["error_type"] == "PdfExportError"
    assert diagnostics["stage"] == "render"
    assert diagnostics["warnings"] == ["pdf_failed"]


def test_summarize_format_html_skips_pdf_export(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)
    _install_fake_summarize_chunks(monkeypatch)
    render_calls = _install_fake_report_render(monkeypatch)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--format",
            "html",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert [call["stage"] for call in render_calls] == ["html"]


def test_summarize_invalid_format_fails_before_creating_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--format",
            "png",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "Unsupported --format value" in result.output
    assert not outputs.exists()


def test_summarize_invalid_format_fails_before_consent(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--format",
            "png",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "Unsupported --format value: png" in result.output
    assert "Continue?" not in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_invalid_language_fails_before_consent(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--language",
            "ja",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "--language must be auto, zh, or en." in result.output
    assert "Continue?" not in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_summarization_failure_writes_diagnostics_after_chunks(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)
    _install_fake_transcript_build(monkeypatch)

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
        partial_dir = run_dir / "partial_summaries"
        partial_dir.mkdir(parents=True, exist_ok=True)
        (partial_dir / "chunk_001.json").write_text(
            '{"chunk_index": 1, "chapters": []}',
            encoding="utf-8",
        )
        raise SummarizationError(
            "codex exec failed with OPENAI_API_KEY=secret /Users/jack/raw"
        )

    monkeypatch.setattr(pipeline, "summarize_chunks", fake_summarize_chunks)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "codex exec failed" in result.output
    assert "secret" not in result.output
    assert "/Users/jack" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "chunks.json").is_file()
    assert not (run_dir / "chapters.json").exists()
    assert diagnostics["error_type"] == "SummarizationError"
    assert diagnostics["stage"] == "summarization"
    assert diagnostics["artifact_paths"] == [
        "diagnostics.json",
        "metadata.json",
        ".bilifan/cache/BV1abcDEF12G_p2.mp3",
        "transcript.json",
        "transcript.txt",
        "transcript.srt",
        "chunks.json",
        "partial_summaries/chunk_001.json",
    ]
    assert "secret" not in diagnostics["sanitized_message"]
    assert "/Users/jack" not in diagnostics["sanitized_message"]


def test_summarize_debug_log_is_reserved_for_later_slice(tmp_path):
    config_home = tmp_path / "config-home"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--debug-log",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "--debug-log is reserved for a later slice" in result.output


def test_serve_prints_url_and_starts_uvicorn(monkeypatch):
    calls: dict[str, object] = {}

    def fake_generate_token():
        calls["generate_token"] = True
        return "fixed-token"

    def fake_create_app(*, outputs, token, open_browser):
        calls["create_app"] = {
            "outputs": outputs,
            "token": token,
            "open_browser": open_browser,
        }
        return "app-instance"

    def fake_find_available_port(host, preferred_port):
        calls["find_port"] = {
            "host": host,
            "preferred_port": preferred_port,
        }
        return 8765

    def fake_schedule_browser_open(url):
        calls["schedule_browser_open"] = url

    def fake_uvicorn_run(app_instance, *, host, port, log_level):
        calls["uvicorn_run"] = {
            "app_instance": app_instance,
            "host": host,
            "port": port,
            "log_level": log_level,
        }

    monkeypatch.setattr(cli, "generate_token", fake_generate_token)
    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli, "_find_available_port", fake_find_available_port)
    monkeypatch.setattr(cli, "_schedule_browser_open", fake_schedule_browser_open)
    monkeypatch.setattr(cli.uvicorn, "run", fake_uvicorn_run)

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert "http://127.0.0.1:8765/" in result.output
    assert calls["create_app"] == {
        "outputs": cli.Path("./outputs"),
        "token": "fixed-token",
        "open_browser": True,
    }
    assert calls["find_port"] == {
        "host": "127.0.0.1",
        "preferred_port": 8765,
    }
    assert calls["schedule_browser_open"] == "http://127.0.0.1:8765/"
    assert calls["uvicorn_run"] == {
        "app_instance": "app-instance",
        "host": "127.0.0.1",
        "port": 8765,
        "log_level": "info",
    }


def test_serve_no_open_does_not_open_browser(monkeypatch):
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli, "generate_token", lambda: "fixed-token")

    def fake_create_app(*, outputs, token, open_browser):
        calls["create_app"] = {
            "outputs": outputs,
            "token": token,
            "open_browser": open_browser,
        }
        return "app-instance"

    def fake_schedule_browser_open(url):
        calls["schedule_browser_open"] = url

    def fake_uvicorn_run(app_instance, *, host, port, log_level):
        calls["uvicorn_run"] = {
            "app_instance": app_instance,
            "host": host,
            "port": port,
            "log_level": log_level,
        }

    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli, "_find_available_port", lambda host, preferred_port: 8765)
    monkeypatch.setattr(cli, "_schedule_browser_open", fake_schedule_browser_open)
    monkeypatch.setattr(cli.uvicorn, "run", fake_uvicorn_run)

    result = runner.invoke(app, ["serve", "--no-open"])

    assert result.exit_code == 0
    assert "http://127.0.0.1:8765/" in result.output
    assert calls["create_app"] == {
        "outputs": cli.Path("./outputs"),
        "token": "fixed-token",
        "open_browser": False,
    }
    assert "schedule_browser_open" not in calls
    assert calls["uvicorn_run"] == {
        "app_instance": "app-instance",
        "host": "127.0.0.1",
        "port": 8765,
        "log_level": "info",
    }


def test_serve_rejects_non_localhost_host():
    result = runner.invoke(app, ["serve", "--host", "0.0.0.0"])

    assert result.exit_code == 2
    assert "127.0.0.1" in result.output


def test_serve_uses_next_available_port(monkeypatch):
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli, "generate_token", lambda: "fixed-token")
    monkeypatch.setattr(cli, "create_app", lambda **kwargs: "app-instance")
    monkeypatch.setattr(cli, "_find_available_port", lambda host, preferred_port: 8766)
    monkeypatch.setattr(cli, "_schedule_browser_open", lambda url: calls.setdefault("url", url))

    def fake_uvicorn_run(app_instance, *, host, port, log_level):
        calls["uvicorn_run"] = {
            "app_instance": app_instance,
            "host": host,
            "port": port,
            "log_level": log_level,
        }

    monkeypatch.setattr(cli.uvicorn, "run", fake_uvicorn_run)

    result = runner.invoke(app, ["serve", "--port", "8765"])

    assert result.exit_code == 0
    assert "http://127.0.0.1:8766/" in result.output
    assert calls["url"] == "http://127.0.0.1:8766/"
    assert calls["uvicorn_run"] == {
        "app_instance": "app-instance",
        "host": "127.0.0.1",
        "port": 8766,
        "log_level": "info",
    }


def test_serve_rejects_invalid_port_bounds():
    low = runner.invoke(app, ["serve", "--port", "0"])
    high = runner.invoke(app, ["serve", "--port", "65536"])

    assert low.exit_code == 2
    assert "--port must be between 1 and 65535" in low.output
    assert high.exit_code == 2
    assert "--port must be between 1 and 65535" in high.output


def test_find_available_port_has_upper_bound(monkeypatch):
    class BusySocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def setsockopt(self, level, option, value):
            return None

        def bind(self, address):
            raise OSError("busy")

    monkeypatch.setattr(cli.socket, "socket", lambda *args, **kwargs: BusySocket())

    try:
        cli._find_available_port("127.0.0.1", 65535)
    except cli.typer.BadParameter as exc:
        assert "Could not find an available local port" in str(exc)
    else:
        raise AssertionError("expected BadParameter")


def test_serve_schedules_browser_open_without_calling_it_before_uvicorn(monkeypatch):
    calls: list[tuple[str, str]] = []
    scheduled: list[object] = []

    class FakeTimer:
        daemon = False

        def __init__(self, delay, callback, args=()):
            scheduled.append((delay, callback, args))

        def start(self):
            calls.append(("timer", "start"))

    def fake_open_browser(url):
        calls.append(("browser", url))

    def fake_uvicorn_run(app_instance, *, host, port, log_level):
        calls.append(("uvicorn", f"{host}:{port}"))

    monkeypatch.setattr(cli, "generate_token", lambda: "fixed-token")
    monkeypatch.setattr(cli, "create_app", lambda **kwargs: "app-instance")
    monkeypatch.setattr(cli, "_find_available_port", lambda host, preferred_port: 8765)
    monkeypatch.setattr(cli.threading, "Timer", FakeTimer)
    monkeypatch.setattr(cli, "_open_browser", fake_open_browser)
    monkeypatch.setattr(cli.uvicorn, "run", fake_uvicorn_run)

    result = runner.invoke(app, ["serve"])

    assert result.exit_code == 0
    assert calls == [("timer", "start"), ("uvicorn", "127.0.0.1:8765")]
    assert len(scheduled) == 1
    delay, callback, args = scheduled[0]
    assert delay > 0
    assert callback is cli._open_browser_when_ready
    assert args == ("http://127.0.0.1:8765/",)


def test_schedule_browser_open_waits_for_local_url_before_opening(monkeypatch):
    calls: list[tuple[str, str]] = []
    checks = iter([False, False, True])

    class ImmediateTimer:
        daemon = False

        def __init__(self, delay, callback, args=()):
            calls.append(("timer", str(delay)))
            self.callback = callback
            self.args = args

        def start(self):
            self.callback(*self.args)

    def fake_url_ready(url):
        calls.append(("ready", url))
        return next(checks)

    def fake_open_browser(url):
        calls.append(("open", url))

    monkeypatch.setattr(cli.threading, "Timer", ImmediateTimer)
    monkeypatch.setattr(cli.time, "sleep", lambda delay: calls.append(("sleep", str(delay))))
    monkeypatch.setattr(cli, "_local_url_ready", fake_url_ready)
    monkeypatch.setattr(cli, "_open_browser", fake_open_browser)

    cli._schedule_browser_open("http://127.0.0.1:8765/")

    assert calls == [
        ("timer", str(cli.OPEN_BROWSER_DELAY_SECONDS)),
        ("ready", "http://127.0.0.1:8765/"),
        ("sleep", str(cli.OPEN_BROWSER_RETRY_SECONDS)),
        ("ready", "http://127.0.0.1:8765/"),
        ("sleep", str(cli.OPEN_BROWSER_RETRY_SECONDS)),
        ("ready", "http://127.0.0.1:8765/"),
        ("open", "http://127.0.0.1:8765/"),
    ]
