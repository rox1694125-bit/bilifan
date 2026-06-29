import pytest

from bilifan.transcription_routing import (
    alternate_whisper_route,
    choose_whisper_route,
)


def test_choose_route_records_chinese_decision_with_ignored_reference_urls():
    route = choose_whisper_route(
        {
            "title": "给傻子的Git教程",
            "part_title": "给傻子的Git教程",
            "description": (
                "Git官网: https://git-scm.com/\n"
                "Git第一步配置: https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup"
            ),
            "tags": ["软件", "学习", "github", "git"],
            "subtitles": [],
        }
    )

    assert route["selected_model"] == "turbo"
    assert route["selected_language"] == "zh"
    assert route["confidence"] == "high"
    assert route["reason"] == "cjk_title_without_explicit_english_audio"
    assert "title_has_cjk" in route["signals"]
    assert "description_urls_ignored" in route["signals"]
    assert route["alternates"] == [{"model": "small.en", "language": "en"}]


def test_choose_route_records_explicit_english_audio_signal():
    route = choose_whisper_route(
        {
            "title": "Andrew Ng 访谈精华",
            "part_title": "英语原声完整版",
            "description": "课程讨论和创业建议。",
        }
    )

    assert route["selected_model"] == "small.en"
    assert route["selected_language"] == "en"
    assert route["confidence"] == "high"
    assert route["reason"] == "explicit_english_audio_signal"
    assert "explicit_english_audio_signal" in route["signals"]


def test_choose_route_records_manual_language_choice():
    route = choose_whisper_route(
        {"title": "How to build a small app", "description": "A short tutorial"},
        language="zh",
    )

    assert route["selected_model"] == "turbo"
    assert route["selected_language"] == "zh"
    assert route["confidence"] == "manual"
    assert route["reason"] == "manual_language_zh"
    assert route["signals"] == ["manual_language_zh"]


def test_choose_route_rejects_unsupported_language():
    with pytest.raises(ValueError, match="Unsupported Whisper language"):
        choose_whisper_route({"title": "中文标题"}, language="ja")


def test_alternate_whisper_route_switches_supported_routes():
    assert alternate_whisper_route(
        {"selected_model": "small.en", "selected_language": "en"}
    ) == {
        "model": "turbo",
        "language": "zh",
    }
    assert alternate_whisper_route(
        {"selected_model": "turbo", "selected_language": "zh"}
    ) == {
        "model": "small.en",
        "language": "en",
    }
