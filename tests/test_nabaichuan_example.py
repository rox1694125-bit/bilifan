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
                },
                "summary": {
                    "style": "学习笔记",
                    "chapters": [
                        {
                            "chapter_index": 1,
                            "title": "Chapter",
                            "summary": "Summary",
                            "timestamp_url": "https://example.com/video?t=0",
                            "key_points": ["Point"],
                        }
                    ],
                },
                "transcript": {"segments": [{"start": 0, "end": 1, "text": "Hello"}]},
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
    assert rows[0]["type"] == "video"
    assert rows[1]["type"] == "chapter"
    assert rows[1]["source_url"].endswith("t=0")
    assert str(tmp_path) not in output_path.read_text(encoding="utf-8")


def test_content_bundle_to_nabaichuan_can_include_transcript(tmp_path):
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
