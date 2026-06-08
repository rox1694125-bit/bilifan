import json
import subprocess
from pathlib import Path

import pytest

from bilifan.bilibili import parse_bilibili_url
from bilifan.metadata import (
    MetadataIngestError,
    fetch_current_part_metadata,
    metadata_from_yt_dlp_json,
)


def test_fetch_yt_dlp_uses_sanitized_url_and_keeps_cookies_out_of_metadata(tmp_path):
    raw_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=2&spm_id_from=333.999&vd_source=tracking-secret"
    )
    ref = parse_bilibili_url(raw_url)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = {
            "id": ref.bvid,
            "cid": "987654",
            "title": "Top level title",
            "uploader": "Uploader",
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    result = fetch_current_part_metadata(
        ref,
        tmp_path,
        cookies_from_browser="chrome",
        cookies_file=Path("/Users/jack/Downloads/bili-cookies.txt"),
        runner=fake_run,
    )

    cmd = calls[0][0]
    assert "--dump-single-json" in cmd
    assert "--skip-download" in cmd
    assert "--no-warnings" in cmd
    assert ref.sanitized_url in cmd
    assert raw_url not in cmd
    assert "spm_id_from" not in " ".join(cmd)
    assert "vd_source" not in " ".join(cmd)
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    assert "--cookies" in cmd
    assert "/Users/jack/Downloads/bili-cookies.txt" in cmd

    result_text = json.dumps(result, ensure_ascii=False)
    assert result["input_url_sanitized"] == ref.sanitized_url
    assert result["video_id"] == ref.bvid
    assert result["part_index"] == 2
    assert "chrome" not in result_text
    assert "bili-cookies.txt" not in result_text
    assert "/Users/jack" not in result_text


def test_metadata_from_yt_dlp_json_maps_current_part_fields():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    payload = {
        "id": ref.bvid,
        "title": "Collection title",
        "description": "Description text",
        "uploader": "Owner Name",
        "tags": ["tag-a", "tag-b"],
        "thumbnail": "https://i0.hdslb.com/bfs/archive/cover.jpg",
        "duration": 618,
        "entries": [
            {
                "page": 1,
                "cid": "111",
                "part": "Part one",
                "title": "Part one title",
                "duration": 300,
            },
            {
                "page": 2,
                "cid": "222",
                "part": "Part two",
                "title": "Part two title",
                "duration": 318,
            },
        ],
        "subtitles": {
            "zh-Hans": [
                {
                    "name": "Chinese",
                    "url": "https://example.com/subtitle.srt",
                    "ext": "srt",
                }
            ]
        },
    }

    result = metadata_from_yt_dlp_json(
        ref,
        payload,
        generated_at="2026-06-08T00:00:00+00:00",
        yt_dlp_version="2026.3.17",
        ffmpeg_version="",
        cover_path="assets/cover.jpg",
    )

    assert result["bilifan_version"] == "0.1.0"
    assert result["generated_at"] == "2026-06-08T00:00:00+00:00"
    assert result["input_url_sanitized"] == ref.sanitized_url
    assert result["video_id"] == ref.bvid
    assert result["part_index"] == 2
    assert result["cid"] == "222"
    assert result["title"] == "Collection title"
    assert result["part_title"] == "Part two"
    assert result["owner_name"] == "Owner Name"
    assert result["description"] == "Description text"
    assert result["tags"] == ["tag-a", "tag-b"]
    assert result["cover_url"] == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert result["cover_path"] == "assets/cover.jpg"
    assert result["duration"] == 318
    assert result["parts"] == [
        {"part_index": 1, "cid": "111", "title": "Part one", "duration": 300},
        {"part_index": 2, "cid": "222", "title": "Part two", "duration": 318},
    ]
    assert result["subtitles"] == [
        {
            "language": "zh-Hans",
            "name": "Chinese",
            "url": "https://example.com/subtitle.srt",
            "ext": "srt",
        }
    ]
    assert result["yt_dlp_version"] == "2026.3.17"
    assert result["ffmpeg_version"] == ""


def test_fetch_current_part_metadata_raises_redacted_error_on_yt_dlp_failure(tmp_path):
    raw_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=1&vd_source=tracking-secret&token=secret-token"
    )
    ref = parse_bilibili_url(raw_url)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            23,
            "",
            (
                "failed with --cookies-file /Users/jack/Downloads/bili-cookies.txt "
                f"for {raw_url} Cookie: SESSDATA=secret; bili_jct=token"
            ),
        )

    with pytest.raises(MetadataIngestError) as excinfo:
        fetch_current_part_metadata(
            ref,
            tmp_path,
            cookies_file=Path("/Users/jack/Downloads/bili-cookies.txt"),
            runner=fake_run,
        )

    message = str(excinfo.value)
    assert excinfo.value.source_exit_code == 23
    assert "yt-dlp failed" in message
    assert "BV1abcDEF12G?p=1" in message
    assert "vd_source" not in message
    assert "secret-token" not in message
    assert "bili-cookies.txt" not in message
    assert "/Users/jack" not in message
    assert "SESSDATA=secret" not in message
