import subprocess

import pytest

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
    assert "第一阶段 MVP 不包含 SVG 图解和视频截图" in html


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
