import json

import pytest

from bilifan.bundle import BundleError, build_content_bundle, write_content_bundle


def _metadata():
    return {
        "bilifan_version": "0.1.0",
        "generated_at": "2026-06-09T00:00:00+00:00",
        "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=1",
        "video_id": "BV1abcDEF12G",
        "part_index": 1,
        "title": "测试视频",
        "part_title": "测试视频",
        "owner_name": "UP",
        "duration": 120,
        "tags": ["AI"],
        "metadata_source": "bilibili-public-api",
    }


def _metadata_with_secrets():
    metadata = _metadata()
    metadata.update(
        {
            "description": (
                "local=/Volumes/mySSD/projects/bilifan/raw.txt "
                "OPENAI_API_KEY=sk-test-secret "
                "Cookie: SESSDATA=session-secret"
            ),
            "owner_name": "UP /Users/jack/private/path.txt",
        }
    )
    return metadata


def _transcript():
    return {
        "source": "whisper",
        "language": "zh",
        "model": "turbo",
        "segments": [{"start": 0, "end": 3.2, "text": "第一段"}],
        "transcript_check": {"status": "ok", "segment_count": 1},
    }


def _chapters():
    return {
        "style": "学习笔记",
        "summary_validation": {
            "status": "passed",
            "checks": {
                "required_fields_present": True,
                "timestamps_anchored": True,
                "chapter_timestamps_within_chunk": True,
                "evidence_anchors_present": True,
            },
            "warnings": [],
        },
        "chapters": [
            {
                "chapter_index": 1,
                "title": "开场",
                "start": 0,
                "end": 3.2,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                "summary": "讲开场。",
                "key_points": ["要点"],
                "quotes": [],
                "visual_anchors": [],
                "evidence": [
                    {
                        "segment_start_index": 0,
                        "segment_end_index": 0,
                        "start": 0,
                        "end": 3.2,
                        "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=0",
                        "text_preview": "第一段",
                    }
                ],
                "diagram": {
                    "type": "flow",
                    "caption": "图解：开场",
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg"><text>要点</text></svg>',
                },
                "frame": {
                    "path": "media/frames/chapter_001_000001.jpg",
                    "timestamp": 1.6,
                    "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=1&t=1",
                    "caption": "视频时间戳：0:01",
                },
            }
        ],
    }


def test_build_content_bundle_writes_source_summary_and_transcript():
    bundle = build_content_bundle(
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
        artifact_paths=[
            "report.html",
            "notes.md",
            "transcript.txt",
            "nabaichuan.jsonl",
        ],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
    )

    assert bundle["schema_version"] == 1
    assert bundle["bundle_id"] == "bilibili:BV1abcDEF12G:p1"
    assert bundle["source"]["platform"] == "bilibili"
    assert bundle["source"]["title"] == "测试视频"
    assert bundle["summary"]["chapters"][0]["title"] == "开场"
    assert bundle["summary"]["summary_validation"]["status"] == "passed"
    assert bundle["summary"]["chapters"][0]["evidence"][0]["text_preview"] == "第一段"
    assert bundle["summary"]["chapters"][0]["diagram"]["type"] == "flow"
    assert bundle["summary"]["chapters"][0]["frame"]["path"] == "media/frames/chapter_001_000001.jpg"
    assert bundle["transcript"]["segments"][0]["text"] == "第一段"
    assert bundle["artifacts"]["report_html"] == "report.html"
    assert bundle["artifacts"]["content_bundle_json"] == "content_bundle.json"
    assert bundle["artifacts"]["nabaichuan_jsonl"] == "nabaichuan.jsonl"
    assert "content_bundle.json" in bundle["artifacts"]["all"]


def test_write_content_bundle_rejects_absolute_artifact_paths(tmp_path):
    with pytest.raises(BundleError, match="relative"):
        build_content_bundle(
            metadata=_metadata(),
            transcript=_transcript(),
            chapters=_chapters(),
            artifact_paths=[str(tmp_path / "report.html")],
            platform="bilibili",
            source_id="BV1abcDEF12G",
            part_id="p1",
        )


def test_write_content_bundle_outputs_strict_json_without_local_paths(tmp_path):
    path = write_content_bundle(
        run_dir=tmp_path,
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
        artifact_paths=["report.html", "notes.md"],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(data, ensure_ascii=False)
    assert path.name == "content_bundle.json"
    assert str(tmp_path) not in serialized
    assert "Cookie" not in serialized


def test_write_content_bundle_redacts_sensitive_input_fields(tmp_path):
    transcript = _transcript()
    transcript["segments"][0]["text"] = (
        "local=/Users/jack/private/raw.txt OPENAI_API_KEY=sk-test-secret"
    )
    path = write_content_bundle(
        run_dir=tmp_path,
        metadata=_metadata_with_secrets(),
        transcript=transcript,
        chapters=_chapters(),
        artifact_paths=["report.html", "notes.md"],
        platform="bilibili",
        source_id="BV1abcDEF12G",
        part_id="p1",
        llm_provider="codex-exec",
        llm_model="gpt-5.5",
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(data, ensure_ascii=False)
    assert "/Volumes/mySSD" not in serialized
    assert "/Users/jack" not in serialized
    assert "sk-test-secret" not in serialized
    assert "session-secret" not in serialized
    assert data["provenance"]["llm_provider"] == "codex-exec"
    assert data["provenance"]["llm_model"] == "gpt-5.5"
