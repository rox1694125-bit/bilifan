import json

import pytest

from bilifan.exports import (
    NABAICHUAN_EXPORT_CONTRACT,
    NABAICHUAN_EXPORT_SCHEMA_VERSION,
    build_nabaichuan_records,
    write_nabaichuan_jsonl,
)


def _bundle():
    return {
        "schema_version": 1,
        "bundle_id": "bilibili:BV1abcDEF12G:p1",
        "source": {
            "platform": "bilibili",
            "id": "BV1abcDEF12G",
            "part_id": "p1",
            "canonical_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
            "title": "Title",
            "author": "Author",
            "duration_seconds": 120,
            "language": "zh",
        },
        "summary": {
            "style": "学习笔记",
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": "开场",
                    "start": 0,
                    "end": 60,
                    "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                    "summary": "摘要一",
                    "key_points": ["要点一"],
                },
                {
                    "chapter_index": 2,
                    "title": "后半段",
                    "start": 60,
                    "end": 120,
                    "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=60",
                    "summary": "摘要二",
                    "key_points": ["要点二"],
                },
            ],
        },
        "transcript": {
            "source": "whisper",
            "language": "zh",
            "segments": [
                {"start": 0, "end": 10, "text": "第一段"},
                {"start": 10, "end": 31, "text": "第二段"},
                {"start": 31, "end": 61, "text": "第三段"},
                {"start": 61, "end": 91, "text": "第四段"},
            ],
        },
        "artifacts": {"all": ["report.html", "media/audio.mp3"]},
        "provenance": {"llm_model": "gpt-5.5"},
    }


def test_build_nabaichuan_records_outputs_video_chapter_and_transcript_records():
    records = build_nabaichuan_records(_bundle())

    assert [record["type"] for record in records] == [
        "video",
        "chapter",
        "chapter",
        "transcript_segment",
        "transcript_segment",
    ]
    assert records[0]["record_id"] == "bilibili:BV1abcDEF12G:p1:video"
    assert records[0]["content_hash"]
    assert records[1]["parent_record_id"] == records[0]["record_id"]
    assert records[1]["chapter_id"] == "bilibili:BV1abcDEF12G:p1:chapter:1"
    assert records[3]["chapter_id"] == "bilibili:BV1abcDEF12G:p1:chapter:1"
    assert records[4]["chapter_id"] == "bilibili:BV1abcDEF12G:p1:chapter:2"
    assert records[3]["start"] == 0
    assert 30 <= records[3]["end"] - records[3]["start"] <= 90
    assert 30 <= records[4]["end"] - records[4]["start"] <= 90
    assert "第一段" in records[3]["text"]
    assert "第四段" in records[4]["text"]
    assert records[3]["timestamp_url"].endswith("t=0")


def test_nabaichuan_records_include_stable_export_contract_metadata():
    records = build_nabaichuan_records(
        _bundle(),
        run_key="BV1abcDEF12G_p1/runs/2026-06-08_120000",
    )
    same_content_other_run = build_nabaichuan_records(
        _bundle(),
        run_key="BV1abcDEF12G_p1/runs/2026-06-09_120000",
    )

    assert all(
        record["schema_version"] == NABAICHUAN_EXPORT_SCHEMA_VERSION
        for record in records
    )
    assert all(record["export_contract"] == NABAICHUAN_EXPORT_CONTRACT for record in records)
    assert all(record["bundle_id"] == "bilibili:BV1abcDEF12G:p1" for record in records)
    assert all(record["run_key"] == "BV1abcDEF12G_p1/runs/2026-06-08_120000" for record in records)
    assert [record["content_hash"] for record in records] == [
        record["content_hash"] for record in same_content_other_run
    ]


def test_nabaichuan_transcript_records_split_long_segments_into_30_to_90_second_ranges():
    bundle = _bundle()
    bundle["transcript"]["segments"] = [
        {"start": 0, "end": 180, "text": "长片段" * 90},
    ]

    records = build_nabaichuan_records(bundle)
    transcript_records = [
        record for record in records if record["type"] == "transcript_segment"
    ]

    assert len(transcript_records) == 2
    assert all(
        30 <= record["end"] - record["start"] <= 90
        for record in transcript_records
    )


def test_nabaichuan_expands_short_transcript_windows_when_source_is_long():
    bundle = _bundle()
    bundle["source"]["duration_seconds"] = 120
    bundle["transcript"]["segments"] = [
        {"start": 0, "end": 1, "text": "异常短字幕"},
    ]

    records = build_nabaichuan_records(bundle)
    transcript_records = [
        record for record in records if record["type"] == "transcript_segment"
    ]

    assert len(transcript_records) == 1
    assert transcript_records[0]["start"] == 0
    assert transcript_records[0]["end"] == 30
    assert transcript_records[0]["text"] == "异常短字幕"


def test_nabaichuan_allows_short_windows_for_truly_short_sources():
    bundle = _bundle()
    bundle["source"]["duration_seconds"] = 12
    bundle["transcript"]["segments"] = [
        {"start": 0, "end": 8, "text": "短视频"},
    ]

    records = build_nabaichuan_records(bundle)
    transcript_records = [
        record for record in records if record["type"] == "transcript_segment"
    ]

    assert len(transcript_records) == 1
    assert transcript_records[0]["start"] == 0
    assert transcript_records[0]["end"] == 8


def test_nabaichuan_content_hash_changes_only_when_content_changes():
    original = build_nabaichuan_records(_bundle())
    same = build_nabaichuan_records(_bundle())
    changed_bundle = _bundle()
    changed_bundle["summary"]["chapters"][0]["summary"] = "新摘要"
    changed = build_nabaichuan_records(changed_bundle)

    assert [record["content_hash"] for record in same] == [
        record["content_hash"] for record in original
    ]
    assert changed[1]["record_id"] == original[1]["record_id"]
    assert changed[1]["content_hash"] != original[1]["content_hash"]
    assert changed[0]["content_hash"] == original[0]["content_hash"]


def test_write_nabaichuan_jsonl_writes_strict_json_without_local_paths(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    bundle = _bundle()
    bundle["source"]["title"] = "Title /Users/jack/private/raw.txt"
    bundle["summary"]["chapters"][0]["summary"] = "OPENAI_API_KEY=sk-test-secret"
    bundle["transcript"]["segments"][0]["text"] = "local /Volumes/mySSD/raw.wav"
    (run_dir / "content_bundle.json").write_text(
        json.dumps(bundle, ensure_ascii=False),
        encoding="utf-8",
    )

    artifact = write_nabaichuan_jsonl(run_dir)
    rows = [
        json.loads(line)
        for line in (run_dir / artifact).read_text(encoding="utf-8").splitlines()
    ]

    assert artifact == "nabaichuan.jsonl"
    assert rows[0]["type"] == "video"
    serialized = (run_dir / artifact).read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert "/Users/jack" not in serialized
    assert "/Volumes/mySSD" not in serialized
    assert "sk-test-secret" not in serialized
    assert "OPENAI_API_KEY=<redacted>" in serialized


def test_write_nabaichuan_jsonl_rejects_missing_bundle(tmp_path):
    with pytest.raises(Exception, match="content_bundle"):
        write_nabaichuan_jsonl(tmp_path)
