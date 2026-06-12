from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from .bilibili import BilibiliPartRef
from .diagnostics import redact_text


Runner = Callable[..., subprocess.CompletedProcess[str]]
PDF_TIMEOUT_SECONDS = 120


class RenderError(RuntimeError):
    """Raised when report rendering cannot produce the requested artifact."""

    def __init__(self, message: str) -> None:
        self.sanitized_message = redact_text(message)
        super().__init__(self.sanitized_message)


class PdfExportError(RenderError):
    """Raised when Chrome cannot export the HTML report to PDF."""


def render_report_html(
    *,
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    transcript: dict[str, Any],
    chapters: dict[str, Any],
    run_dir: Path,
) -> Path:
    html_path = run_dir / "report.html"
    html_path.write_text(
        _template().render(
            ref=ref,
            metadata=_metadata_view(metadata),
            transcript=_transcript_view(transcript),
            summary=_summary_view(chapters),
            chapters=_chapters_view(chapters),
        )
        + "\n",
        encoding="utf-8",
    )
    return html_path


def export_report_pdf(
    *,
    html_path: Path,
    pdf_path: Path,
    runner: Runner = subprocess.run,
    chrome_path: str | None = None,
) -> Path:
    chrome = chrome_path or find_chrome_executable()
    if not chrome:
        raise PdfExportError("Chrome executable was not found for PDF export.")

    cmd = [
        chrome,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.resolve().as_uri(),
    ]
    try:
        result = runner(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=PDF_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PdfExportError(
            f"Chrome PDF export timed out after {PDF_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise PdfExportError(f"Chrome PDF export failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr or result.stdout or "Chrome returned no output."
        raise PdfExportError(
            f"Chrome PDF export failed with exit code {result.returncode}: {detail}"
        )
    if not pdf_path.is_file():
        raise PdfExportError("Chrome PDF export did not produce report.pdf.")
    return pdf_path


def find_chrome_executable() -> str:
    env_chrome = os.environ.get("BILIFAN_CHROME") or os.environ.get("CHROME_BIN")
    if env_chrome and Path(env_chrome).is_file():
        return env_chrome

    for candidate in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "Google Chrome",
    ):
        found = shutil.which(candidate)
        if found:
            return found

    mac_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    return mac_path if Path(mac_path).is_file() else ""


def _metadata_view(metadata: dict[str, Any]) -> dict[str, Any]:
    tags = metadata.get("tags") if isinstance(metadata.get("tags"), list) else []
    return {
        "title": _first_text(metadata.get("title"), metadata.get("part_title")),
        "part_title": _first_text(metadata.get("part_title")),
        "owner_name": _first_text(metadata.get("owner_name")),
        "description": _first_text(metadata.get("description")),
        "tags": [_first_text(tag) for tag in tags if _first_text(tag)],
        "cover_path": _first_text(metadata.get("cover_path")),
        "duration_label": _format_time(_float_value(metadata.get("duration")) or 0),
        "input_url": _first_text(metadata.get("input_url_sanitized")),
        "metadata_source": _first_text(metadata.get("metadata_source")),
    }


def _transcript_view(transcript: dict[str, Any]) -> dict[str, Any]:
    check = transcript.get("transcript_check")
    return {
        "source": _first_text(transcript.get("source")),
        "language": _first_text(transcript.get("language")),
        "model": _first_text(transcript.get("model")),
        "segment_count": len(transcript.get("segments", []))
        if isinstance(transcript.get("segments"), list)
        else 0,
        "check_status": _first_text(check.get("status")) if isinstance(check, dict) else "",
    }


def _summary_view(chapters: dict[str, Any]) -> dict[str, Any]:
    validation = (
        chapters.get("summary_validation")
        if isinstance(chapters.get("summary_validation"), dict)
        else {}
    )
    checks = validation.get("checks") if isinstance(validation.get("checks"), dict) else {}
    warnings = validation.get("warnings") if isinstance(validation.get("warnings"), list) else []
    return {
        "style": _first_text(chapters.get("style")) or "学习笔记",
        "validation_status": _first_text(validation.get("status")) or "unknown",
        "validation_warnings": [_first_text(warning) for warning in warnings if _first_text(warning)],
        "validation_checks": [
            f"{key}: {value}"
            for key, value in checks.items()
            if isinstance(value, bool)
        ],
    }


def _chapters_view(chapters: dict[str, Any]) -> list[dict[str, Any]]:
    raw_chapters = chapters.get("chapters")
    if not isinstance(raw_chapters, list):
        return []

    view: list[dict[str, Any]] = []
    for raw_chapter in raw_chapters:
        if not isinstance(raw_chapter, dict):
            continue
        start = _float_value(raw_chapter.get("start")) or 0
        end = _float_value(raw_chapter.get("end")) or start
        view.append(
            {
                "chapter_index": raw_chapter.get("chapter_index"),
                "title": _first_text(raw_chapter.get("title")),
                "start_label": _format_time(start),
                "end_label": _format_time(end),
                "timestamp_url": _first_text(raw_chapter.get("timestamp_url")),
                "summary": _first_text(raw_chapter.get("summary")),
                "key_points": _string_list(raw_chapter.get("key_points")),
                "quotes": _string_list(raw_chapter.get("quotes")),
                "visual_anchors": _string_list(raw_chapter.get("visual_anchors")),
                "evidence": _evidence_view(raw_chapter.get("evidence")),
                "diagram": _diagram_view(raw_chapter.get("diagram")),
                "frame": _frame_view(raw_chapter.get("frame")),
            }
        )
    return view


def _evidence_view(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    evidence: list[dict[str, Any]] = []
    for raw_item in value:
        if not isinstance(raw_item, dict):
            continue
        start = _float_value(raw_item.get("start")) or 0
        end = _float_value(raw_item.get("end")) or start
        evidence.append(
            {
                "start_label": _format_time(start),
                "end_label": _format_time(end),
                "timestamp_url": _first_text(raw_item.get("timestamp_url")),
                "text_preview": _first_text(raw_item.get("text_preview")),
            }
        )
    return evidence


def _diagram_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    svg = _first_text(value.get("svg"))
    if not svg.startswith("<svg") or "<script" in svg.lower():
        return None
    return {
        "type": _first_text(value.get("type")),
        "caption": _first_text(value.get("caption")),
        "svg": Markup(svg),
    }


def _frame_view(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    path = _first_text(value.get("path"))
    if not path or path.startswith("/") or ".." in Path(path).parts:
        return None
    timestamp = _float_value(value.get("timestamp")) or 0
    return {
        "path": path,
        "timestamp_label": _format_time(timestamp),
        "timestamp_url": _first_text(value.get("timestamp_url")),
        "caption": _first_text(value.get("caption")) or f"视频时间戳：{_format_time(timestamp)}",
    }


def _template():
    env = Environment(autoescape=select_autoescape(["html", "xml"]))
    return env.from_string(
        """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ metadata.title }} - Bilifan 学习笔记</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #1f2933;
      --muted: #667085;
      --line: #d8dee8;
      --panel: #f7f9fc;
      --accent: #0b6bcb;
      --accent-soft: #e6f0fb;
      --mark: #8a5a00;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: #ffffff;
      color: var(--ink);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.68;
    }
    main { max-width: 920px; margin: 0 auto; padding: 32px 24px 56px; }
    header { border-bottom: 1px solid var(--line); padding-bottom: 22px; }
    .kicker { color: var(--accent); font-size: 13px; font-weight: 700; }
    h1 { font-size: 32px; line-height: 1.22; margin: 8px 0 12px; letter-spacing: 0; }
    .meta { display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); font-size: 14px; }
    .cover { width: 100%; max-height: 360px; object-fit: cover; margin-top: 18px; border: 1px solid var(--line); }
    .description { margin-top: 18px; white-space: pre-wrap; color: #344054; }
    .tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
    .tag { background: var(--panel); border: 1px solid var(--line); padding: 2px 8px; font-size: 13px; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 22px 0; }
    .stat { border: 1px solid var(--line); background: var(--panel); padding: 12px; }
    .stat strong { display: block; font-size: 18px; color: var(--ink); }
    .stat span { color: var(--muted); font-size: 12px; }
    section.chapter { border-top: 1px solid var(--line); padding: 26px 0; break-inside: avoid; }
    .chapter-head { display: flex; align-items: baseline; justify-content: space-between; gap: 16px; }
    h2 { font-size: 22px; line-height: 1.3; margin: 0; letter-spacing: 0; }
    .time {
      color: var(--accent);
      background: var(--accent-soft);
      text-decoration: none;
      font-weight: 700;
      padding: 2px 8px;
      white-space: nowrap;
    }
    .summary { margin: 14px 0; font-size: 16px; }
    .qa { border: 1px solid var(--line); background: var(--panel); padding: 10px 12px; margin: 18px 0; color: var(--muted); font-size: 13px; }
    .qa strong { color: var(--ink); }
    h3 { font-size: 15px; margin: 18px 0 6px; color: #344054; }
    ul { margin: 6px 0 0; padding-left: 22px; }
    li { margin: 4px 0; }
    blockquote {
      margin: 10px 0 0;
      padding: 8px 12px;
      border-left: 3px solid var(--mark);
      background: #fff8e8;
      color: #3b2d12;
    }
    .evidence a { color: var(--accent); font-weight: 700; text-decoration: none; }
    .evidence span { color: var(--muted); }
    .diagram {
      margin-top: 18px;
      border: 1px solid var(--line);
      background: #ffffff;
      padding: 12px;
      overflow-x: auto;
    }
    .diagram svg { max-width: 100%; height: auto; display: block; }
    figure.frame { margin: 18px 0 0; }
    figure.frame img { width: 100%; border: 1px solid var(--line); display: block; }
    figcaption { color: var(--muted); font-size: 13px; margin-top: 6px; }
    footer { border-top: 1px solid var(--line); color: var(--muted); font-size: 12px; padding-top: 18px; }
    @media (max-width: 720px) {
      main { padding: 24px 16px 42px; }
      h1 { font-size: 26px; }
      .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .chapter-head { display: block; }
      .time { display: inline-block; margin-top: 8px; }
    }
    @media print {
      main { max-width: none; padding: 0; }
      a { color: inherit; }
      .time { border: 1px solid var(--line); }
    }
  </style>
</head>
<body>
<main>
  <header>
    <div class="kicker">Bilifan 学习笔记</div>
    <h1>{{ metadata.title }}</h1>
    <div class="meta">
      {% if metadata.owner_name %}<span>UP：{{ metadata.owner_name }}</span>{% endif %}
      {% if metadata.part_title %}<span>当前 P：{{ metadata.part_title }}</span>{% endif %}
      <span>时长：{{ metadata.duration_label }}</span>
      {% if metadata.metadata_source %}<span>metadata：{{ metadata.metadata_source }}</span>{% endif %}
    </div>
    {% if metadata.cover_path %}<img class="cover" src="{{ metadata.cover_path }}" alt="视频封面">{% endif %}
    {% if metadata.description %}<p class="description">{{ metadata.description }}</p>{% endif %}
    {% if metadata.tags %}
    <div class="tags">{% for tag in metadata.tags %}<span class="tag">{{ tag }}</span>{% endfor %}</div>
    {% endif %}
  </header>

  <div class="summary-grid">
    <div class="stat"><strong>{{ chapters|length }}</strong><span>章节</span></div>
    <div class="stat"><strong>{{ transcript.segment_count }}</strong><span>转写片段</span></div>
    <div class="stat"><strong>{{ transcript.source }}</strong><span>转写来源</span></div>
    <div class="stat"><strong>{{ transcript.check_status }}</strong><span>完整性</span></div>
  </div>
  <div class="qa">
    <strong>总结模板：{{ summary.style }}</strong>
    <span> · 总结校验：{{ summary.validation_status }}</span>
    {% if summary.validation_warnings %}
    <span> · warning: {{ summary.validation_warnings|join(", ") }}</span>
    {% endif %}
  </div>

  {% for chapter in chapters %}
  <section class="chapter">
    <div class="chapter-head">
      <h2>{{ chapter.chapter_index }}. {{ chapter.title }}</h2>
      <a class="time" href="{{ chapter.timestamp_url }}">{{ chapter.start_label }}</a>
    </div>
    <p class="summary">{{ chapter.summary }}</p>
    {% if chapter.key_points %}
    <h3>要点</h3>
    <ul>{% for point in chapter.key_points %}<li>{{ point }}</li>{% endfor %}</ul>
    {% endif %}
    {% if chapter.quotes %}
    <h3>关键引用</h3>
    {% for quote in chapter.quotes %}<blockquote>{{ quote }}</blockquote>{% endfor %}
    {% endif %}
    {% if chapter.visual_anchors %}
    <h3>视觉锚点</h3>
    <ul>{% for anchor in chapter.visual_anchors %}<li>{{ anchor }}</li>{% endfor %}</ul>
    {% endif %}
    {% if chapter.evidence %}
    <h3>证据锚点</h3>
    <ul class="evidence">
      {% for evidence in chapter.evidence %}
      <li>
        <a href="{{ evidence.timestamp_url }}">{{ evidence.start_label }}-{{ evidence.end_label }}</a>
        {% if evidence.text_preview %}<span>{{ evidence.text_preview }}</span>{% endif %}
      </li>
      {% endfor %}
    </ul>
    {% endif %}
    {% if chapter.diagram %}
    <h3>图解</h3>
    <figure class="diagram">
      {{ chapter.diagram.svg }}
      {% if chapter.diagram.caption %}<figcaption>{{ chapter.diagram.caption }}</figcaption>{% endif %}
    </figure>
    {% endif %}
    {% if chapter.frame %}
    <h3>真实截图</h3>
    <figure class="frame">
      <a href="{{ chapter.frame.timestamp_url }}"><img src="{{ chapter.frame.path }}" alt="{{ chapter.frame.caption }}"></a>
      <figcaption>{{ chapter.frame.caption }}</figcaption>
    </figure>
    {% endif %}
  </section>
  {% endfor %}

  <footer>
    <p>本文件可离线打开；时间戳链接会跳回原视频网页。图解来自章节内容；真实截图仅在可抽帧时生成。</p>
  </footer>
</main>
</body>
</html>"""
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_first_text(item) for item in value if _first_text(item)]


def _format_time(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _float_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return ""
