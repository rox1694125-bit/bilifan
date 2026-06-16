import subprocess

import pytest

import bilifan.renderer as renderer
from bilifan.bilibili import BilibiliPartRef
from bilifan.renderer import PdfExportError, export_report_pdf, render_report_html


REF = BilibiliPartRef(
    bvid="BV1abcDEF12G",
    part_index=2,
    sanitized_url="https://www.bilibili.com/video/BV1abcDEF12G?p=2",
)


def _metadata():
    return {
        "title": "测试视频",
        "part_title": "当前 P",
        "owner_name": "UP 主",
        "description": "简介",
        "tags": ["AI", "教程"],
        "cover_path": "assets/cover.jpg",
        "duration": 125,
        "metadata_source": "yt-dlp",
    }


def _transcript():
    return {
        "source": "whisper",
        "language": "zh",
        "model": "turbo",
        "segments": [{"start": 0, "end": 120, "text": "转写"}],
        "transcript_check": {"status": "ok"},
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
                "end": 120,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "summary": "讲清楚问题。",
                "key_points": ["要点一"],
                "quotes": ["关键句"],
                "visual_anchors": ["白板"],
                "evidence": [
                    {
                        "segment_start_index": 0,
                        "segment_end_index": 0,
                        "start": 0,
                        "end": 120,
                        "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                        "text_preview": "转写",
                    }
                ],
                "diagram": {
                    "type": "flow",
                    "caption": "图解：开场",
                    "svg": '<svg xmlns="http://www.w3.org/2000/svg"><text>要点一</text></svg>',
                },
                "frame": {
                    "path": "media/frames/chapter_001_000030.jpg",
                    "timestamp": 30,
                    "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=30",
                    "caption": "视频时间戳：0:30",
                },
            }
        ],
    }


def test_render_report_html_writes_offline_html_with_timestamp_links(tmp_path):
    html_path = render_report_html(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=_chapters(),
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "<style>" in html
    assert "report.css" not in html
    assert 'src="assets/cover.jpg"' in html
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2&amp;t=0" in html
    assert "总结校验：passed" in html
    assert "证据锚点" in html
    assert "0:00-2:00" in html
    assert "图解：开场" in html
    assert "<svg" in html
    assert 'src="media/frames/chapter_001_000030.jpg"' in html
    assert "视频时间戳：0:30" in html
    assert "图解来自章节内容；真实截图仅在可抽帧时生成" in html


def test_export_report_pdf_invokes_chrome_headless(tmp_path):
    html_path = tmp_path / "report.html"
    pdf_path = tmp_path / "report.pdf"
    html_path.write_text("<html></html>", encoding="utf-8")
    calls = []

    def fake_runner(cmd, **kwargs):
        calls.append({"cmd": cmd, **kwargs})
        pdf_path.write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    export_report_pdf(
        html_path=html_path,
        pdf_path=pdf_path,
        chrome_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        runner=fake_runner,
    )

    cmd = calls[0]["cmd"]
    assert cmd[0].endswith("Google Chrome")
    assert "--headless=new" in cmd
    assert "--no-pdf-header-footer" in cmd
    assert f"--print-to-pdf={pdf_path}" in cmd
    assert html_path.resolve().as_uri() in cmd


def test_export_report_pdf_raises_when_chrome_fails(tmp_path):
    html_path = tmp_path / "report.html"
    pdf_path = tmp_path / "report.pdf"
    html_path.write_text("<html></html>", encoding="utf-8")

    def fake_runner(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="",
            stderr="failed /Users/jack/raw.html",
        )

    with pytest.raises(PdfExportError) as exc_info:
        export_report_pdf(
            html_path=html_path,
            pdf_path=pdf_path,
            chrome_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            runner=fake_runner,
        )

    assert "Chrome PDF export failed" in str(exc_info.value)
    assert "/Users/jack" not in str(exc_info.value)


def _article():
    return {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "人工智能工作流",
                "start": 0,
                "end": 90,
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "source_segment_start_index": 0,
                "source_segment_end_index": 1,
                "paragraphs": [
                    {
                        "text": "今天我们讲人工智能和工作流。这个地方很重要。",
                        "emphasis": [{"text": "人工智能", "kind": "strong"}],
                    }
                ],
                "key_terms": ["人工智能", "工作流"],
                "warnings": [],
            }
        ],
        "warnings": ["部分术语可能未能确认"],
    }


def test_render_transcript_html_writes_readable_article_without_line_timestamps(tmp_path):
    html_path = renderer.render_transcript_html(
        ref=REF,
        metadata=_metadata(),
        article=_article(),
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert html_path.name == "transcript.html"
    assert "逐字稿文章" in html
    assert "人工智能工作流" in html
    assert "<strong>人工智能</strong>" in html
    assert "[0:00]" not in html
    assert "回到视频" in html
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2&amp;t=0" in html


def test_export_html_pdf_can_write_transcript_pdf(tmp_path):
    html_path = tmp_path / "transcript.html"
    pdf_path = tmp_path / "transcript.pdf"
    html_path.write_text("<html></html>", encoding="utf-8")

    def fake_runner(cmd, **kwargs):
        pdf_path.write_bytes(b"%PDF")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    result = renderer.export_html_pdf(
        html_path=html_path,
        pdf_path=pdf_path,
        chrome_path="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        runner=fake_runner,
    )

    assert result == pdf_path


def test_render_transcript_html_escapes_malicious_article_and_drops_unsafe_link(
    tmp_path,
):
    metadata = _metadata()
    metadata["title"] = "<script>alert(1)</script>"
    metadata["cover_path"] = ""
    article = {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": '<img src=x onerror="alert(1)">',
                "timestamp_url": "javascript:alert(1)",
                "paragraphs": [
                    {
                        "text": (
                            "正文 <script>alert(1)</script> "
                            '<img src=x onerror="alert(1)">'
                        ),
                        "emphasis": [
                            {"text": "<script>alert(1)</script>", "kind": "strong"}
                        ],
                    }
                ],
                "key_terms": [
                    "<script>alert(1)</script>",
                    '<img src=x onerror="alert(1)">',
                ],
                "warnings": ['<img src=x onerror="alert(1)">'],
            },
            {
                "section_index": 2,
                "title": "非标准 URL",
                "timestamp_url": "https:alert(2)",
                "paragraphs": [{"text": "这一节不应该出现回链", "emphasis": []}],
                "key_terms": [],
                "warnings": [],
            }
        ],
        "warnings": ["<script>alert(1)</script>"],
    }

    html_path = renderer.render_transcript_html(
        ref=REF,
        metadata=metadata,
        article=article,
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "javascript:alert(1)" not in html
    assert "https:alert(2)" not in html
    assert "回到视频" not in html
    assert "<script>" not in html
    assert "</script>" not in html
    assert "<img" not in html
    assert 'onerror="alert(1)"' not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in html
    assert "<strong>&lt;script&gt;alert(1)&lt;/script&gt;</strong>" in html


def test_render_transcript_html_keeps_ambiguous_emphasis_plain_and_escaped(tmp_path):
    article = {
        "schema_version": 1,
        "source": "whisper",
        "cleaning_level": "strong",
        "sections": [
            {
                "section_index": 1,
                "title": "强调边界",
                "timestamp_url": "https://www.bilibili.com/video/BV1abcDEF12G?p=2&t=0",
                "paragraphs": [
                    {
                        "text": "AI AI <script>alert(1)</script>",
                        "emphasis": [{"text": "AI", "kind": "strong"}],
                    },
                    {
                        "text": "abcdef <img src=x onerror=\"alert(1)\">",
                        "emphasis": [
                            {"text": "abc", "kind": "strong"},
                            {"text": "bcd", "kind": "mark"},
                        ],
                    },
                ],
                "key_terms": [],
                "warnings": [],
            }
        ],
        "warnings": [],
    }

    html_path = renderer.render_transcript_html(
        ref=REF,
        metadata=_metadata(),
        article=article,
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "<strong>AI</strong>" not in html
    assert "<strong>abc</strong>" not in html
    assert "<mark>bcd</mark>" not in html
    assert "AI AI &lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "abcdef &lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in html


def test_render_report_html_drops_unsafe_timestamp_hrefs(tmp_path):
    chapters = _chapters()
    chapter = chapters["chapters"][0]
    chapter["timestamp_url"] = "javascript:alert(1)"
    chapter["evidence"][0]["timestamp_url"] = "javascript:alert(2)"
    chapter["frame"]["timestamp_url"] = "javascript:alert(3)"

    html_path = render_report_html(
        ref=REF,
        metadata=_metadata(),
        transcript=_transcript(),
        chapters=chapters,
        run_dir=tmp_path,
    )

    html = html_path.read_text(encoding="utf-8")
    assert "javascript:alert" not in html
    assert 'href=""' not in html
