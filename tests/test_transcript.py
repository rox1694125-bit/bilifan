import json

import pytest

from bilifan.transcript import (
    TranscriptError,
    build_transcript,
    check_transcript_complete,
    choose_whisper_model,
    parse_bilibili_subtitle_json,
)


def test_parse_bilibili_subtitle_json_segments():
    payload = {
        "body": [
            {"from": 0, "to": 1.25, "content": "第一句"},
            {"from": 1.25, "to": 3, "content": "第二句"},
        ]
    }

    assert parse_bilibili_subtitle_json(json.dumps(payload).encode("utf-8")) == [
        {"start": 0.0, "end": 1.25, "text": "第一句"},
        {"start": 1.25, "end": 3.0, "text": "第二句"},
    ]


def test_check_transcript_complete_allows_close_last_segment_end():
    check = check_transcript_complete(
        [{"start": 0, "end": 98, "text": "ok"}],
        audio_seconds=100,
    )

    assert check == {
        "status": "ok",
        "audio_seconds": 100,
        "last_segment_end": 98,
        "difference_seconds": 2,
        "tolerance_seconds": 10,
        "segment_count": 1,
    }


def test_check_transcript_complete_flags_incomplete_transcript():
    check = check_transcript_complete(
        [{"start": 0, "end": 60, "text": "too short"}],
        audio_seconds=120,
    )

    assert check["status"] == "transcript_incomplete"
    assert check["difference_seconds"] == 60
    assert check["tolerance_seconds"] == 10


def test_choose_whisper_model_defaults_chinese_and_english_small_en():
    assert choose_whisper_model({"title": "中文标题", "description": "这里是简介"}) == (
        "turbo",
        "zh",
    )
    assert choose_whisper_model(
        {"title": "How to build a small app", "description": "A short tutorial"}
    ) == ("small.en", "en")


def test_build_transcript_prefers_bilibili_subtitle(tmp_path):
    metadata = {
        "subtitles": [
            {
                "language": "zh-Hans",
                "name": "中文",
                "url": "https://example.test/subtitle.json",
                "ext": "json",
            }
        ]
    }
    media = {"duration_seconds": 3, "audio_path": ".bilifan/cache/audio.mp3"}

    def fake_fetcher(url):
        assert url == "https://example.test/subtitle.json"
        return json.dumps(
            {"body": [{"from": 0, "to": 3, "content": "字幕内容"}]}
        ).encode("utf-8")

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        subtitle_fetcher=fake_fetcher,
    )

    assert transcript["source"] == "bilibili-subtitle"
    assert transcript["language"] == "zh-Hans"
    assert transcript["model"] is None
    assert transcript["segments"] == [
        {
            "start": 0.0,
            "end": 3.0,
            "text": "字幕内容",
            "language": "zh-Hans",
            "source": "bilibili-subtitle",
        }
    ]
    assert transcript["transcript_check"]["status"] == "ok"


def test_build_transcript_redacts_sensitive_segment_text(tmp_path):
    metadata = {
        "subtitles": [
            {
                "language": "zh-Hans",
                "url": "https://example.test/subtitle.json",
                "ext": "json",
            }
        ]
    }
    media = {"duration_seconds": 3, "audio_path": ".bilifan/cache/audio.mp3"}

    def fake_fetcher(url):
        return json.dumps(
            {
                "body": [
                    {
                        "from": 0,
                        "to": 3,
                        "content": (
                            "Cookie: SESSDATA=secret /Users/jack/raw.txt "
                            "https://www.bilibili.com/video/BV1abcDEF12G?p=1"
                            "&vd_source=secret"
                        ),
                    }
                ]
            }
        ).encode("utf-8")

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        subtitle_fetcher=fake_fetcher,
    )

    serialized = json.dumps(transcript, ensure_ascii=False)
    assert "SESSDATA=secret" not in serialized
    assert "/Users/jack" not in serialized
    assert "vd_source" not in serialized
    assert "BV1abcDEF12G" in serialized


def test_build_transcript_uses_whisper_when_no_subtitles(tmp_path):
    audio_path = tmp_path / ".bilifan" / "cache" / "audio.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    metadata = {"title": "中文教程", "description": "", "subtitles": []}
    media = {"duration_seconds": 2, "audio_path": ".bilifan/cache/audio.mp3"}
    calls = []

    def fake_whisper(audio_file, *, model_name, language):
        calls.append((audio_file, model_name, language))
        return [{"start": 0, "end": 2, "text": "转写内容"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        whisper_transcriber=fake_whisper,
    )

    assert calls == [(audio_path, "turbo", "zh")]
    assert transcript["source"] == "whisper"
    assert transcript["language"] == "zh"
    assert transcript["model"] == "turbo"
    assert transcript["segments"] == [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "转写内容",
            "language": "zh",
            "source": "whisper",
        }
    ]


def test_build_transcript_auto_falls_back_to_whisper_when_subtitle_fails(tmp_path):
    audio_path = tmp_path / ".bilifan" / "cache" / "audio.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    metadata = {
        "title": "中文教程",
        "description": "",
        "subtitles": [{"language": "zh-Hans", "url": "https://example.test/sub.json"}],
    }
    media = {"duration_seconds": 2, "audio_path": ".bilifan/cache/audio.mp3"}
    calls = []

    def failing_fetcher(url):
        raise TranscriptError("subtitle fetch failed")

    def fake_whisper(audio_file, *, model_name, language):
        calls.append((audio_file, model_name, language))
        return [{"start": 0, "end": 2, "text": "fallback 转写"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        subtitle_fetcher=failing_fetcher,
        whisper_transcriber=fake_whisper,
    )

    assert calls == [(audio_path, "turbo", "zh")]
    assert transcript["source"] == "whisper"
    assert transcript["segments"][0]["text"] == "fallback 转写"


def test_build_transcript_subtitles_mode_does_not_fallback_to_whisper(tmp_path):
    audio_path = tmp_path / ".bilifan" / "cache" / "audio.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    metadata = {
        "subtitles": [{"language": "zh-Hans", "url": "https://example.test/sub.json"}],
    }
    media = {"duration_seconds": 2, "audio_path": ".bilifan/cache/audio.mp3"}

    def failing_fetcher(url):
        raise TranscriptError("subtitle fetch failed")

    def forbidden_whisper(audio_file, *, model_name, language):
        raise AssertionError("whisper fallback should not be called")

    with pytest.raises(TranscriptError, match="subtitle fetch failed"):
        build_transcript(
            metadata,
            media,
            tmp_path,
            transcriber="subtitles",
            subtitle_fetcher=failing_fetcher,
            whisper_transcriber=forbidden_whisper,
        )


def test_build_transcript_force_whisper_skips_available_subtitles(tmp_path):
    audio_path = tmp_path / ".bilifan" / "cache" / "audio.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    metadata = {
        "title": "English tutorial",
        "description": "Build something useful",
        "subtitles": [{"language": "zh-Hans", "url": "https://example.test/sub.json"}],
    }
    media = {"duration_seconds": 2, "audio_path": ".bilifan/cache/audio.mp3"}

    def forbidden_fetcher(url):
        raise AssertionError("subtitle fetcher should not be called")

    def fake_whisper(audio_file, *, model_name, language):
        return [{"start": 0, "end": 2, "text": "English transcript"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        force_whisper=True,
        subtitle_fetcher=forbidden_fetcher,
        whisper_transcriber=fake_whisper,
    )

    assert transcript["source"] == "whisper"
    assert transcript["language"] == "en"
    assert transcript["model"] == "small.en"


def test_build_transcript_raises_when_last_segment_is_not_close_to_audio(tmp_path):
    audio_path = tmp_path / ".bilifan" / "cache" / "audio.mp3"
    audio_path.parent.mkdir(parents=True)
    audio_path.write_bytes(b"audio")
    metadata = {"title": "中文教程", "subtitles": []}
    media = {"duration_seconds": 120, "audio_path": ".bilifan/cache/audio.mp3"}

    def fake_whisper(audio_file, *, model_name, language):
        return [{"start": 0, "end": 60, "text": "too short"}]

    transcript = build_transcript(
        metadata,
        media,
        tmp_path,
        whisper_transcriber=fake_whisper,
    )

    assert transcript["segments"] == [
        {
            "start": 0.0,
            "end": 60.0,
            "text": "too short",
            "language": "zh",
            "source": "whisper",
        }
    ]
    assert transcript["transcript_check"]["status"] == "transcript_incomplete"
