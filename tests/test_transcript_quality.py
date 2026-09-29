from bilifan.transcript_quality import check_transcript_quality


def test_quality_check_accepts_chinese_transcript_for_chinese_route():
    result = check_transcript_quality(
        [{"start": 0, "end": 8, "text": "嗨 这里是 Alex 今天我们讲 Git 的基本概念和常用命令"}],
        expected_language="zh",
        metadata={"title": "给傻子的Git教程"},
        audio_seconds=8,
    )

    assert result["status"] == "ok"
    assert result["observed_language"] == "zh"
    assert result["metrics"]["cjk_ratio"] > 0.3


def test_quality_check_flags_english_output_for_expected_chinese():
    result = check_transcript_quality(
        [
            {"start": 0, "end": 4, "text": "Now I do Ay Ari's text."},
            {"start": 4, "end": 8, "text": "This is not a coherent transcript for the tutorial."},
        ],
        expected_language="zh",
        metadata={"title": "给傻子的Git教程"},
        audio_seconds=8,
    )

    assert result["status"] == "suspect_wrong_route"
    assert result["observed_language"] == "en"
    assert "expected_zh_but_low_cjk" in result["warnings"]


def test_quality_check_accepts_english_transcript_for_english_route():
    result = check_transcript_quality(
        [{"start": 0, "end": 6, "text": "Today we are going to talk about evaluation pipelines."}],
        expected_language="en",
        metadata={"title": "Evaluation pipelines"},
        audio_seconds=6,
    )

    assert result["status"] == "ok"
    assert result["observed_language"] == "en"


def test_quality_check_flags_chinese_output_for_expected_english():
    result = check_transcript_quality(
        [{"start": 0, "end": 6, "text": "今天我们来聊一下评估流程和自动化测试。"}],
        expected_language="en",
        metadata={"title": "English audio interview"},
        audio_seconds=6,
    )

    assert result["status"] == "suspect_wrong_route"
    assert result["observed_language"] == "zh"
    assert "expected_en_but_low_ascii_words" in result["warnings"]


def test_quality_check_marks_repetitive_transcript_unusable():
    result = check_transcript_quality(
        [{"start": index, "end": index + 1, "text": "thank you"} for index in range(20)],
        expected_language="en",
        metadata={"title": "English talk"},
        audio_seconds=20,
    )

    assert result["status"] == "unusable"
    assert "high_repetition" in result["warnings"]


def test_short_valid_clip_is_not_unusable_just_for_character_count():
    result = check_transcript_quality([{"start": 0, "end": 2, "text": "hello"}], expected_language="en", audio_seconds=2)
    assert result["status"] == "ok"


def test_long_clip_with_nearly_no_words_remains_unusable():
    result = check_transcript_quality([{"start": 0, "end": 120, "text": "hello"}], expected_language="en", audio_seconds=120)
    assert result["status"] == "unusable"


def test_selected_english_output_does_not_prove_chinese_title_was_english_audio():
    result = check_transcript_quality(
        [{"start": 0, "end": 8, "text": "Now we explain configuration steps and install all the packages."}],
        expected_language="en", audio_seconds=8,
        metadata={"title": "中文工具安装教程", "description": "git config --global user.name Example"},
    )
    assert result["status"] == "low_confidence"
    assert "metadata_language_conflict" in result["warnings"]
