import pytest

from bilifan.chunking import (
    ChunkingError,
    LongVideoConfirmationRequired,
    build_chunks,
    estimate_text_tokens,
)


def test_estimate_text_tokens_counts_cjk_more_densely_than_ascii():
    assert estimate_text_tokens("中文测试") == 4
    assert estimate_text_tokens("abcd efgh") == 2


def test_build_chunks_uses_single_pass_for_short_video():
    transcript = {
        "segments": [
            {
                "start": 0,
                "end": 60,
                "text": "第一段",
                "language": "zh",
                "source": "whisper",
            },
            {
                "start": 60,
                "end": 120,
                "text": "第二段",
                "language": "zh",
                "source": "whisper",
            },
        ]
    }
    media = {"duration_seconds": 120}

    chunks = build_chunks(transcript, media)

    assert chunks["strategy"]["mode"] == "single_pass"
    assert chunks["chunk_count"] == 1
    assert chunks["chunks"][0]["start"] == 0.0
    assert chunks["chunks"][0]["end"] == 120.0
    assert chunks["chunks"][0]["text"] == "第一段\n第二段"


def test_build_chunks_uses_dynamic_chunks_for_45_to_180_minutes():
    transcript = {
        "segments": [
            {
                "start": index * 900,
                "end": (index + 1) * 900,
                "text": f"第 {index} 段",
                "language": "zh",
                "source": "whisper",
            }
            for index in range(6)
        ]
    }
    media = {"duration_seconds": 90 * 60}

    chunks = build_chunks(transcript, media, long_video_confirmed=True)

    assert chunks["strategy"]["mode"] == "dynamic"
    assert chunks["strategy"]["target_chunk_seconds"] == 45 * 60
    assert chunks["chunk_count"] == 2
    assert chunks["chunks"][0]["segment_count"] == 3
    assert chunks["chunks"][1]["segment_count"] == 3


def test_build_chunks_shrinks_target_for_dense_transcript():
    transcript = {
        "segments": [
            {
                "start": index * 900,
                "end": (index + 1) * 900,
                "text": "字" * 20_000,
                "language": "zh",
                "source": "whisper",
            }
            for index in range(4)
        ]
    }
    media = {"duration_seconds": 60 * 60}

    chunks = build_chunks(transcript, media)

    assert chunks["strategy"]["mode"] == "dynamic"
    assert chunks["strategy"]["target_chunk_seconds"] == 30 * 60


def test_build_chunks_requires_confirmation_for_90_to_180_minutes():
    transcript = {
        "segments": [
            {"start": 0, "end": 90 * 60, "text": "长视频", "language": "zh"}
        ]
    }
    media = {"duration_seconds": 90 * 60}

    with pytest.raises(LongVideoConfirmationRequired):
        build_chunks(transcript, media)


def test_build_chunks_allow_long_video_does_not_skip_90_to_180_confirmation():
    transcript = {
        "segments": [
            {"start": 0, "end": 90 * 60, "text": "长视频", "language": "zh"}
        ]
    }
    media = {"duration_seconds": 90 * 60}

    with pytest.raises(LongVideoConfirmationRequired):
        build_chunks(transcript, media, allow_long_video=True)


def test_build_chunks_rejects_over_180_minutes_without_flag():
    transcript = {
        "segments": [
            {"start": 0, "end": 181 * 60, "text": "超长视频", "language": "zh"}
        ]
    }
    media = {"duration_seconds": 181 * 60}

    with pytest.raises(ChunkingError, match="--allow-long-video"):
        build_chunks(transcript, media, long_video_confirmed=True)


def test_build_chunks_allows_over_180_minutes_with_flag():
    transcript = {
        "segments": [
            {"start": 0, "end": 181 * 60, "text": "超长视频", "language": "zh"}
        ]
    }
    media = {"duration_seconds": 181 * 60}

    chunks = build_chunks(transcript, media, allow_long_video=True)

    assert chunks["strategy"]["allow_long_video"] is True
    assert chunks["chunk_count"] == 1


def test_build_chunks_redacts_sensitive_segment_text():
    transcript = {
        "segments": [
            {
                "start": 0,
                "end": 60,
                "text": "Cookie: SESSDATA=secret /Users/jack/raw.txt",
            }
        ]
    }
    media = {"duration_seconds": 60}

    chunks = build_chunks(transcript, media)

    assert "SESSDATA=secret" not in chunks["chunks"][0]["text"]
    assert "/Users/jack" not in chunks["chunks"][0]["text"]
