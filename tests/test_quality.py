import json
from pathlib import Path

import pytest

from bilifan.quality import build_quality, quality_text
from bilifan.transcription_routing import choose_whisper_route


FIXTURES = Path(__file__).parent / "fixtures" / "quality"


def _transcript(text="今天我们介绍可靠的数据处理方法，并保留原始记录以便核对。", **overrides):
    return {
        "source": "bilibili-subtitle", "language": "zh",
        "segments": [{"start": 0, "end": 10, "text": text}],
        "transcript_check": {"status": "ok", "audio_seconds": 10},
        **overrides,
    }


def _article(text, start=0, end=0):
    return {"sections": [{"section_index": 1, "start": 0, "end": 10,
        "source_segment_start_index": start, "source_segment_end_index": end,
        "paragraphs": [{"text": text}]}]}


@pytest.mark.parametrize("sample_path", sorted(FIXTURES.glob("[0-9][0-9]-*.json")), ids=lambda p: p.stem)
def test_fixed_quality_samples(sample_path):
    sample = json.loads(sample_path.read_text())
    quality = build_quality(sample["transcript"], sample.get("article"), sample["metadata"])
    assert quality["status"] == sample["expected"]["status"]
    codes = {reason["code"] for reason in quality["reasons"]}
    assert set(sample["expected"].get("reason_codes", [])) <= codes
    if sample["expected"].get("route"):
        assert choose_whisper_route(sample["metadata"])["selected_language"] == sample["expected"]["route"]
    for reason in quality["reasons"]:
        if reason["code"].startswith("article_"):
            assert "segment_start_index" in reason
            assert "start" in reason


def test_fixture_manifest_is_honest_and_has_ten_distinct_inputs():
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    assert len(manifest["samples"]) == 10
    assert len({item["file"] for item in manifest["samples"]}) == 10
    for entry in manifest["samples"]:
        assert entry["origin"] in {"synthetic", "sanitized_historical_snapshot"}
        assert (FIXTURES / entry["file"]).is_file()


def test_old_transcript_with_missing_checks_remains_unknown():
    transcript = _transcript()
    transcript.pop("transcript_check")
    quality = build_quality(transcript)
    assert quality["status"] == "unknown"
    assert quality["checks"]["transcript_quality"]["status"] == "clean"
    assert quality["checks"]["completeness"]["status"] == "unknown"
    assert "未检查" in quality_text(quality)
    assert "已核实" not in quality_text(quality)


def test_historical_bad_saved_check_cannot_hide_fresh_findings():
    transcript = _transcript("This is a complete English tutorial about an unrelated subject.",
        language="en", transcript_quality_check={"status": "ok", "warnings": []})
    quality = build_quality(transcript, metadata={"title": "中文数据库教程"})
    assert quality["status"] == "needs_review"
    assert "metadata_language_conflict" in {x["code"] for x in quality["reasons"]}


def test_explicit_english_audio_with_chinese_title_is_not_a_conflict():
    transcript = _transcript("Today we discuss reliable testing and keeping the original source records.", language="en")
    quality = build_quality(transcript, metadata={"title": "英语原声：软件测试教程"})
    assert quality["status"] == "clean"


def test_empty_transcript_is_unusable():
    quality = build_quality(_transcript(segments=[]))
    assert quality["status"] == "unusable"
    assert quality["review_required"]


def test_missing_or_empty_article_sections_is_unusable():
    quality = build_quality(_transcript(), {"sections": []})
    assert quality["status"] == "unusable"
    assert "article_missing_sections" in {x["code"] for x in quality["reasons"]}


def test_numbers_with_grouping_and_spaces_are_equivalent():
    source = "今天的预算是 1,200 元，保存时间为 30 秒，请记录这些关键参数。"
    cleaned = "今天的预算是1200元，保存时间为30秒。请记录这些关键参数。"
    assert build_quality(_transcript(source), _article(cleaned))["status"] == "clean"


def test_numeric_change_is_located_and_does_not_claim_correctness():
    source = "今天的预算是 1200 元，保存时间为 30 秒，请记录这些关键参数。"
    quality = build_quality(_transcript(source), _article(source.replace("1200", "12000")))
    reason = next(x for x in quality["reasons"] if x["code"] == "article_numbers_changed")
    assert reason["section_id"] == "1"
    assert reason["segment_start_index"] == 0
    assert "核对" in reason["message"]


def test_filler_and_punctuation_changes_are_clean():
    source = "嗯，那个，今天我们介绍数据备份，就是就是要保存原始文件，然后，然后检查结果。"
    cleaned = "今天我们介绍数据备份，要保存原始文件，然后检查结果。"
    assert build_quality(_transcript(source), _article(cleaned))["status"] == "clean"


def test_large_unclaimed_segment_is_located():
    transcript = _transcript(segments=[
        {"start": 0, "end": 10, "text": "今天我们介绍数据备份，备份完成后检查所有记录。"},
        {"start": 10, "end": 25, "text": "此外这里还有一段重要的恢复操作，需要停止服务再恢复原始记录，防止覆盖新的业务结果。"},
    ])
    quality = build_quality(transcript, _article(transcript["segments"][0]["text"]))
    reason = next(x for x in quality["reasons"] if x["code"] == "article_uncovered_segments")
    assert reason["segment_start_index"] == 1
    assert reason["start"] == 10


def test_claiming_source_indices_does_not_hide_substantive_omission():
    source = "今天介绍备份。恢复之前必须停止后台服务，并核对归档记录与原始资料，确认无误才能继续运行。"
    quality = build_quality(_transcript(source), _article("今天介绍备份。"))
    assert quality["status"] == "needs_review"
    assert "article_substantive_omission" in {x["code"] for x in quality["reasons"]}


def test_invented_substantive_content_is_flagged():
    source = "今天我们介绍数据备份，需要保存原始文件以便后续核对。"
    quality = build_quality(_transcript(source), _article(source + "我建议公司立即采购全新的服务器集群并且开通专业订阅服务，这样可以显著提高业务收入。"))
    assert "article_substantive_addition" in {x["code"] for x in quality["reasons"]}


def test_missing_source_indices_is_unknown_not_clean():
    quality = build_quality(_transcript(), {"sections": [{"paragraphs": [{"text": "整理内容"}]}]})
    assert quality["status"] in {"unknown", "needs_review"}
    assert quality["checks"]["article_fidelity"]["status"] != "clean"


def test_quality_text_keeps_all_reason_messages():
    quality = build_quality(_transcript("今天需要等待 30 秒，然后检查备份记录是否已经保存成功。"),
        _article("今天需要等待 300 分钟，然后检查备份记录是否已经保存成功。"))
    text = quality_text(quality)
    assert "需复查" in text
    assert all(x["message"] in text for x in quality["reasons"])


def test_unchanged_english_code_and_backtick_formatting_are_clean():
    source = "Run `git status` before checking the repository and then preserve the output."
    cleaned = source.replace("`", "")
    assert build_quality(_transcript(source, language="en"), _article(cleaned))["status"] == "clean"


def test_spoken_chinese_quantity_can_be_formatted_as_digits():
    raw = "等待三十秒，然后检查三份文件是否已经保存到归档目录，核对完成才能离开。"
    cleaned = raw.replace("三十秒", "30秒")
    assert build_quality(_transcript(raw), _article(cleaned))["status"] == "clean"


def test_changed_chinese_quantity_is_flagged():
    raw = "等待三十秒，然后检查所有文件是否已经保存到归档目录，核对完成才能离开。"
    quality = build_quality(_transcript(raw), _article(raw.replace("三十秒", "三百秒")))
    assert "article_numbers_changed" in {x["code"] for x in quality["reasons"]}


def test_malformed_historical_checks_are_unknown_instead_of_crashing():
    quality = build_quality(_transcript(transcript_quality_check={"status": [], "warnings": None}))
    assert quality["status"] == "unknown"


def test_malformed_historical_paragraphs_are_not_clean():
    article = _article("placeholder")
    article["sections"][0]["paragraphs"] = None
    quality = build_quality(_transcript(), article)
    assert quality["status"] != "clean"
