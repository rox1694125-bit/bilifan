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


@pytest.mark.parametrize("description", [
    "git config --global user.name Example\ngit config --global user.email example@example.test\ngit remote add origin repository",
    "执行 `python -m pip install package-name` 后再配置。",
    "```python\nimport asyncio\nasync def execute_request(payload):\n    return await client.submit(payload)\n```",
])
def test_chinese_title_with_commands_or_code_is_not_english_audio(description):
    route = choose_whisper_route({"title": "中文开发工具配置教程", "description": description})
    assert route["selected_language"] == "zh"
    assert "description_code_ignored" in route["signals"]


def test_code_cannot_forge_explicit_english_audio_signal():
    route = choose_whisper_route({"title": "配置教程", "description": '`print("spoken in English")`'})
    assert route["selected_language"] == "zh"


def test_english_title_and_natural_description_still_select_english():
    route = choose_whisper_route({"title": "How reliable backups work", "description": "We discuss practical recovery steps and verify the saved documents."})
    assert route["selected_language"] == "en"


def test_speaker_name_alone_does_not_establish_audio_language():
    route = choose_whisper_route({"title": "吴恩达课程的中文讲解", "description": "讲解常用模型评估方法。"})
    assert route["selected_language"] == "zh"


def test_multiline_shell_continuations_are_not_spoken_english_evidence():
    # Sanitized reconstruction of an observed deployment tutorial description.
    description = (
        "这是中文部署教程。命令：\n"
        "docker run -d \\\n"
        "\u00a0--name demonstration \\\n"
        "\u00a0--restart=always \\\n"
        "\u00a0-p 8080:8080 \\\n"
        "\u00a0-e console=true \\\n"
        "\u00a0-e EXAMPLE_VALUE=placeholder \\\n"
        "\u00a0-v /opt/example/logs/:/opt/example/logs/ \\\n"
        "\u00a0registry.example.test/demonstration:latest\n\n"
        "http://localhost:8080/admin/login.html\njdbc:h2:./example"
    )
    route = choose_whisper_route({"title": "中文部署", "description": description})
    assert route["selected_language"] == "zh"
    assert "description_code_ignored" in route["signals"]
