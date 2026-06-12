import json
import subprocess
import sys
from pathlib import Path


def _bundle(path: Path, platform: str) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "bundle_id": f"{platform}:source:p1",
                "source": {
                    "platform": platform,
                    "id": "source",
                    "part_id": "p1",
                    "canonical_url": "https://example.com/video",
                    "title": "Title",
                    "author": "Author",
                    "duration_seconds": 120,
                    "language": "en",
                },
                "summary": {
                    "style": "学习笔记",
                    "chapters": [
                        {
                            "chapter_index": 1,
                            "title": "Chapter",
                            "summary": "Summary",
                            "start": 0,
                            "end": 60,
                            "timestamp_url": "https://example.com/video?t=0",
                            "key_points": ["Point"],
                        }
                    ],
                },
                "transcript": {"segments": [{"start": 0, "end": 35, "text": "Hello"}]},
                "artifacts": {},
                "provenance": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_content_bundle_to_nabaichuan_outputs_jsonl(tmp_path):
    bundle_path = tmp_path / "content_bundle.json"
    output_path = tmp_path / "out.jsonl"
    _bundle(bundle_path, "bilibili")

    result = subprocess.run(
        [
            sys.executable,
            "examples/content_bundle_to_nabaichuan.py",
            str(bundle_path),
            "--out",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["type"] for row in rows] == [
        "video",
        "chapter",
        "transcript_segment",
    ]
    for row in rows:
        assert row["record_id"]
        assert row["content_hash"]
        assert row["source"]["platform"] == "bilibili"
        assert row["source"]["canonical_url"] == "https://example.com/video"

    assert rows[0]["type"] == "video"
    assert rows[0]["record_id"] == "bilibili:source:p1:video"
    assert rows[1]["type"] == "chapter"
    assert rows[1]["record_id"] == "bilibili:source:p1:chapter:1"
    assert rows[1]["chapter_id"] == "bilibili:source:p1:chapter:1"
    assert rows[1]["parent_record_id"] == rows[0]["record_id"]
    assert rows[1]["timestamp_url"].endswith("t=0")
    assert rows[2]["type"] == "transcript_segment"
    assert rows[2]["record_id"] == "bilibili:source:p1:transcript_segment:1:0-35000"
    assert rows[2]["parent_record_id"] == rows[0]["record_id"]
    assert rows[2]["chapter_id"] == rows[1]["chapter_id"]
    assert rows[2]["start"] == 0
    assert rows[2]["end"] == 35
    assert rows[2]["text"] == "Hello"
    assert rows[2]["timestamp_url"].endswith("t=0")
    assert str(tmp_path) not in output_path.read_text(encoding="utf-8")


def test_content_bundle_to_nabaichuan_keeps_include_transcript_compatible(tmp_path):
    bundle_path = tmp_path / "content_bundle.json"
    output_path = tmp_path / "out.jsonl"
    _bundle(bundle_path, "youtube")

    result = subprocess.run(
        [
            sys.executable,
            "examples/content_bundle_to_nabaichuan.py",
            str(bundle_path),
            "--out",
            str(output_path),
            "--include-transcript",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert rows[2]["type"] == "transcript_segment"
    assert rows[2]["text"] == "Hello"


def test_content_bundle_to_nabaichuan_can_disable_transcript(tmp_path):
    bundle_path = tmp_path / "content_bundle.json"
    output_path = tmp_path / "out.jsonl"
    _bundle(bundle_path, "youtube")

    result = subprocess.run(
        [
            sys.executable,
            "examples/content_bundle_to_nabaichuan.py",
            str(bundle_path),
            "--out",
            str(output_path),
            "--no-transcript",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [row["type"] for row in rows] == ["video", "chapter"]
