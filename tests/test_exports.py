from pathlib import Path

import pytest

from bilifan.exports import (
    ExportError,
    format_srt_timestamp,
    render_notes_markdown,
    render_transcript_srt,
    render_transcript_text,
    write_notes_markdown,
    write_transcript_exports,
)


def _metadata():
    return {
        "title": "测试视频",
        "part_title": "当前 P",
        "owner_name": "UP 主",
        "duration": 125,
        "metadata_source": "yt-dlp",
        "input_url_sanitized": "https://www.bilibili.com/video/BV1abcDEF12G?p=2",
    }


def _transcript():
    return {
        "source": "whisper",
        "language": "zh",
        "model": "turbo",
        "segments": [
            {"start": 0, "end": 2.5, "text": "第一段"},
            {"start": 62.25, "end": 65, "text": "第二段"},
        ],
        "transcript_check": {"status": "ok"},
    }


def _chapters():
    return {
        "style": "学习笔记",
        "chapters": [
            {
                "chapter_index": 1,
                "title": "开场",
                "start": 0,
                "end": 65,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "summary": "讲清楚问题。",
                "key_points": ["要点一", "要点二"],
                "quotes": ["关键句"],
                "visual_anchors": ["白板"],
            }
        ],
    }


def test_format_srt_timestamp_uses_subrip_precision():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(62.3456) == "00:01:02,346"
    assert format_srt_timestamp(3661.2) == "01:01:01,200"
    assert format_srt_timestamp(-3) == "00:00:00,000"


def test_render_transcript_text_contains_summary_and_segment_lines():
    text = render_transcript_text(_metadata(), _transcript())

    assert text.endswith("\n")
    assert "Title: 测试视频" in text
    assert "Part: 当前 P" in text
    assert "UP: UP 主" in text
    assert "Source: whisper" in text
    assert "Model: turbo" in text
    assert "Language: zh" in text
    assert "Check: ok" in text
    assert "[00:00] 第一段" in text
    assert "[01:02] 第二段" in text


def test_render_transcript_srt_writes_numbered_subrip_blocks():
    srt = render_transcript_srt(_transcript())

    assert srt == (
        "1\n"
        "00:00:00,000 --> 00:00:02,500\n"
        "第一段\n\n"
        "2\n"
        "00:01:02,250 --> 00:01:05,000\n"
        "第二段\n"
    )


def test_render_notes_markdown_contains_learning_note_sections():
    markdown = render_notes_markdown(_metadata(), _transcript(), _chapters())

    assert markdown.endswith("\n")
    assert markdown.startswith("# 测试视频\n")
    assert "- UP: UP 主" in markdown
    assert "- 当前 P: 当前 P" in markdown
    assert "- 时长: 2:05" in markdown
    assert "- 转写来源: whisper" in markdown
    assert "- 原视频: https://www.bilibili.com/video/BV1abcDEF12G?p=2" in markdown
    assert "## 总摘要" in markdown
    assert "## 目录" in markdown
    assert "- [00:00 开场](https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0)" in markdown
    assert "## 章节" in markdown
    assert "## 1. 开场" in markdown
    assert "时间戳: 00:00" in markdown
    assert "链接: https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0" in markdown
    assert "### 摘要" in markdown
    assert "### 要点" in markdown
    assert "### 关键引用" in markdown
    assert "> 关键句" in markdown
    assert "### 视觉锚点" in markdown


def test_renderers_tolerate_missing_fields_non_lists_and_empty_text():
    metadata = {"title": 123, "duration": "bad", "input_url_sanitized": ""}
    transcript = {
        "segments": [
            {"start": "bad", "end": None, "text": ""},
            "ignored",
            {"start": 3, "end": 3, "text": 456},
        ],
        "transcript_check": "bad",
    }
    chapters = {"chapters": {"not": "a-list"}}

    text = render_transcript_text(metadata, transcript)
    srt = render_transcript_srt(transcript)
    markdown = render_notes_markdown(metadata, transcript, chapters)

    assert "Title: 123" in text
    assert "[00:00] " in text
    assert "[00:03] 456" in text
    assert srt.endswith("\n")
    assert "456" in srt
    assert "# 123\n" in markdown
    assert "No chapters available." in markdown


def test_write_exports_skips_existing_files_unless_overwrite(tmp_path):
    (tmp_path / "transcript.txt").write_text("existing", encoding="utf-8")

    artifacts = write_transcript_exports(tmp_path, _metadata(), _transcript())

    assert artifacts == ["transcript.txt", "transcript.srt"]
    assert (tmp_path / "transcript.txt").read_text(encoding="utf-8") == "existing"
    assert (tmp_path / "transcript.srt").read_text(encoding="utf-8").startswith("1\n")

    write_transcript_exports(tmp_path, _metadata(), _transcript(), overwrite=True)

    assert "Title: 测试视频" in (tmp_path / "transcript.txt").read_text(encoding="utf-8")


def test_write_notes_markdown_returns_stable_artifact_name(tmp_path):
    notes_path = Path(tmp_path / "notes.md")
    notes_path.write_text("existing", encoding="utf-8")

    artifacts = write_notes_markdown(tmp_path, _metadata(), _transcript(), _chapters())

    assert artifacts == ["notes.md"]
    assert notes_path.read_text(encoding="utf-8") == "existing"

    write_notes_markdown(tmp_path, _metadata(), _transcript(), _chapters(), overwrite=True)

    assert notes_path.read_text(encoding="utf-8").startswith("# 测试视频\n")


def test_write_transcript_exports_wraps_directory_creation_error(tmp_path, monkeypatch):
    def fail_mkdir(self, *args, **kwargs):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    with pytest.raises(ExportError, match="Failed to create export directory"):
        write_transcript_exports(tmp_path / "missing", _metadata(), _transcript())
