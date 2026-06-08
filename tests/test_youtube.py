import json
import sys
from subprocess import CompletedProcess

import pytest

from bilifan.bundle import write_content_bundle
from bilifan.media import MediaDownloadError
from bilifan.sources.base import SourceOptions
from bilifan.sources.youtube import YouTubeAdapter, parse_youtube_vtt
from bilifan.transcript import build_transcript
from bilifan.pipeline import PipelineRequest, run_summarize_pipeline
import bilifan.pipeline as pipeline_module


def test_youtube_parse_watch_and_short_urls():
    adapter = YouTubeAdapter()

    watch = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    short = adapter.parse_url("https://youtu.be/dQw4w9WgXcQ")

    assert watch.source_id == "dQw4w9WgXcQ"
    assert short.source_id == "dQw4w9WgXcQ"
    assert adapter.timestamp_url(watch, 12.8).endswith("&t=12s")


def test_youtube_rejects_playlist_only_url():
    adapter = YouTubeAdapter()

    assert adapter.can_parse("https://www.youtube.com/playlist?list=PL123") is False


def test_youtube_metadata_mapping():
    adapter = YouTubeAdapter()
    raw = {
        "id": "dQw4w9WgXcQ",
        "title": "Example",
        "channel": "Channel",
        "duration": 123,
        "description": "Description",
        "tags": ["AI"],
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        "subtitles": {"en": [{"url": "https://example.com/en.vtt", "ext": "vtt"}]},
        "automatic_captions": {},
    }

    metadata = adapter.map_metadata(
        raw,
        canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )

    assert metadata["platform"] == "youtube"
    assert metadata["video_id"] == "dQw4w9WgXcQ"
    assert metadata["owner_name"] == "Channel"
    assert metadata["duration"] == 123
    assert metadata["subtitles"][0]["language"] == "en"
    assert metadata["subtitles"][0]["source"] == "manual"


def test_youtube_metadata_keeps_only_supported_vtt_subtitles_first():
    adapter = YouTubeAdapter()
    raw = {
        "id": "dQw4w9WgXcQ",
        "title": "Example",
        "duration": 123,
        "subtitles": {
            "en": [
                {"url": "https://example.com/en.json3", "ext": "json3"},
                {"url": "https://example.com/en.vtt", "ext": "vtt"},
            ]
        },
        "automatic_captions": {
            "zh": [
                {"url": "https://example.com/zh.ttml", "ext": "ttml"},
                {"url": "https://example.com/zh.vtt", "ext": "vtt"},
            ]
        },
    }

    metadata = adapter.map_metadata(
        raw,
        canonical_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    )

    assert [track["url"] for track in metadata["subtitles"]] == [
        "https://example.com/en.vtt",
        "https://example.com/zh.vtt",
    ]
    assert all(track["ext"] == "vtt" for track in metadata["subtitles"])


def test_parse_youtube_vtt_segments():
    segments = parse_youtube_vtt(
        "WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello world\n"
    )

    assert segments == [{"start": 1.0, "end": 3.5, "text": "Hello world"}]


def test_build_transcript_prefers_youtube_vtt_subtitle(tmp_path):
    metadata = {
        "platform": "youtube",
        "subtitles": [
            {
                "language": "en",
                "url": "https://example.test/en.vtt",
                "ext": "vtt",
                "source": "manual",
            }
        ],
    }
    media = {"duration_seconds": 3.5, "audio_path": ".bilifan/cache/audio.mp3"}

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        subtitle_fetcher=lambda url: (
            b"WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello world\n"
        ),
    )

    assert transcript["source"] == "youtube-subtitle"
    assert transcript["language"] == "en"
    assert transcript["segments"][0]["text"] == "Hello world"


def test_build_transcript_uses_vtt_when_youtube_non_vtt_is_listed_first(tmp_path):
    metadata = {
        "platform": "youtube",
        "subtitles": [
            {
                "language": "en",
                "url": "https://example.test/en.json3",
                "ext": "json3",
                "source": "manual",
            },
            {
                "language": "en",
                "url": "https://example.test/en.vtt",
                "ext": "vtt",
                "source": "manual",
            },
        ],
    }
    media = {"duration_seconds": 3.5, "audio_path": ".bilifan/cache/audio.mp3"}

    def fake_fetcher(url):
        assert url == "https://example.test/en.vtt"
        return b"WEBVTT\n\n00:00:01.000 --> 00:00:03.500\nHello world\n"

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        subtitle_fetcher=fake_fetcher,
    )

    assert transcript["source"] == "youtube-subtitle"
    assert transcript["segments"][0]["text"] == "Hello world"


def test_youtube_adapter_bundle_shape_from_mapped_metadata(tmp_path):
    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    metadata = adapter.map_metadata(
        {"id": ref.source_id, "title": "Example", "channel": "Channel", "duration": 3},
        canonical_url=ref.canonical_url,
    )
    transcript = {
        "source": "youtube-subtitle",
        "language": "en",
        "segments": [{"start": 0, "end": 3, "text": "Hello"}],
    }
    chapters = {
        "style": "学习笔记",
        "chapters": [
            {
                "chapter_index": 1,
                "title": "Intro",
                "start": 0,
                "end": 3,
                "timestamp_url": adapter.timestamp_url(ref, 0),
                "summary": "Summary",
                "key_points": [],
                "quotes": [],
                "visual_anchors": [],
            }
        ],
    }

    path = write_content_bundle(
        run_dir=tmp_path,
        metadata=metadata,
        transcript=transcript,
        chapters=chapters,
        artifact_paths=[],
        platform=adapter.platform,
        source_id=ref.source_id,
        part_id=ref.part_id,
    )

    assert json.loads(path.read_text(encoding="utf-8"))["source"]["platform"] == "youtube"


def test_youtube_fetch_metadata_uses_yt_dlp_dump_json(tmp_path):
    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def fake_runner(cmd, **kwargs):
        assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
        assert "--dump-single-json" in cmd
        return CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"id": ref.source_id, "title": "Example", "duration": 3}),
            stderr="",
        )

    metadata = adapter.fetch_metadata(ref, tmp_path, SourceOptions(), runner=fake_runner)

    assert metadata["video_id"] == "dQw4w9WgXcQ"
    assert metadata["title"] == "Example"


def test_youtube_download_audio_uses_yt_dlp_and_ffprobe(tmp_path):
    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def fake_downloader(cmd, **kwargs):
        assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
        assert "--extract-audio" in cmd
        audio_path = tmp_path / ".bilifan" / "cache" / "YTdQw4w9WgXcQ_p1.mp3"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"audio")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_probe(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        return CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"format": {"duration": "3.0"}}),
            stderr="",
        )

    media = adapter.download_audio(
        ref,
        {"duration": 3},
        tmp_path,
        SourceOptions(),
        downloader=fake_downloader,
        probe_runner=fake_probe,
    )

    assert media["audio_path"] == ".bilifan/cache/YTdQw4w9WgXcQ_p1.mp3"
    assert media["duration_check"]["status"] == "ok"


def test_youtube_download_audio_fails_on_duration_mismatch(tmp_path):
    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    calls = []

    def fake_downloader(cmd, **kwargs):
        calls.append(cmd)
        audio_path = tmp_path / ".bilifan" / "cache" / "YTdQw4w9WgXcQ_p1.mp3"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(b"audio")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    def fake_probe(cmd, **kwargs):
        return CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"format": {"duration": "30.0"}}),
            stderr="",
        )

    with pytest.raises(MediaDownloadError, match="duration differs"):
        adapter.download_audio(
            ref,
            {"duration": 3},
            tmp_path,
            SourceOptions(),
            downloader=fake_downloader,
            probe_runner=fake_probe,
        )

    assert len(calls) == 2


def test_youtube_download_rejects_cookies_for_public_mvp(tmp_path):
    adapter = YouTubeAdapter()
    ref = adapter.parse_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    with pytest.raises(MediaDownloadError, match="cookies"):
        adapter.download_audio(
            ref,
            {"duration": 3},
            tmp_path,
            SourceOptions(cookies_from_browser="chrome"),
        )


def test_pipeline_can_prepare_youtube_run_with_mocked_adapter(tmp_path, monkeypatch):
    def fake_fetch_metadata(self, ref, run_dir, options):
        return self.map_metadata(
            {
                "id": ref.source_id,
                "title": "Example",
                "channel": "Channel",
                "duration": 3,
            },
            canonical_url=ref.canonical_url,
        )

    def fake_download_audio(self, ref, metadata, run_dir, options):
        audio_path = run_dir / ".bilifan" / "cache" / "YTdQw4w9WgXcQ_p1.mp3"
        audio_path.parent.mkdir(parents=True)
        audio_path.write_bytes(b"audio")
        return {
            "audio_path": ".bilifan/cache/YTdQw4w9WgXcQ_p1.mp3",
            "audio_source": "yt-dlp",
            "duration_seconds": 3,
            "duration_check": {"status": "ok"},
        }

    monkeypatch.setattr(YouTubeAdapter, "fetch_metadata", fake_fetch_metadata)
    monkeypatch.setattr(YouTubeAdapter, "download_audio", fake_download_audio)
    monkeypatch.setattr(
        pipeline_module,
        "build_transcript",
        lambda metadata, media, run_dir, **kwargs: {
            "source": "whisper",
            "language": "en",
            "segments": [{"start": 0, "end": 3, "text": "Hello"}],
            "transcript_check": {"status": "ok", "segment_count": 1},
        },
    )
    monkeypatch.setattr(
        pipeline_module,
        "build_chunks",
        lambda transcript, media, **kwargs: {
            "chunks": [{"chunk_index": 1, "start": 0, "end": 3, "text": "Hello"}],
            "chunk_count": 1,
        },
    )
    monkeypatch.setattr(
        pipeline_module,
        "summarize_chunks",
        lambda **kwargs: {
            "style": "学习笔记",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "Intro",
                    "start": 0,
                    "end": 3,
                    "timestamp_url": kwargs["ref"].timestamp_url(0),
                    "summary": "Summary",
                    "key_points": [],
                    "quotes": [],
                    "visual_anchors": [],
                }
            ],
        },
    )

    def fake_render_report_html(*, ref, metadata, transcript, chapters, run_dir):
        html_path = run_dir / "report.html"
        html_path.write_text("<html>youtube</html>", encoding="utf-8")
        return html_path

    monkeypatch.setattr(pipeline_module, "render_report_html", fake_render_report_html)
    monkeypatch.setattr(
        pipeline_module,
        "export_report_pdf",
        lambda *, html_path, pdf_path: pdf_path.write_bytes(b"%PDF") or pdf_path,
    )

    result = run_summarize_pipeline(
        PipelineRequest(
            url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            out=tmp_path,
            output_format="html",
        )
    )

    assert result.run_key.startswith("YTdQw4w9WgXcQ_p1/runs/")
    bundle = json.loads((result.run_dir / "content_bundle.json").read_text(encoding="utf-8"))
    assert bundle["source"]["platform"] == "youtube"
    assert bundle["source"]["id"] == "dQw4w9WgXcQ"
