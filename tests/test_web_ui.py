import json
import re
import shutil
import subprocess
import textwrap
from html.parser import HTMLParser

import pytest

from bilifan.web.ui import render_app_html


class _TitleAndHeadingParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._stack = []
        self.title_parts = []
        self.h1_parts = []

    def handle_starttag(self, tag, attrs):
        self._stack.append(tag)

    def handle_endtag(self, tag):
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if not self._stack:
            return
        if self._stack[-1] == "title":
            self.title_parts.append(data)
        if self._stack[-1] == "h1":
            self.h1_parts.append(data)

    @property
    def title(self):
        return "".join(self.title_parts).strip()

    @property
    def h1_texts(self):
        return [text.strip() for text in self.h1_parts if text.strip()]


def test_render_app_html_contains_workbench_contract():
    html = render_app_html()
    parser = _TitleAndHeadingParser()
    parser.feed(html)

    assert parser.title == "Bilifan Web UI"
    assert parser.h1_texts[0] == "Bilifan Web UI"
    required_strings = [
        "Bilifan Web UI",
        "history-list",
        "url-input",
        "format-select",
        "summary-template-select",
        "language-select",
        "force-whisper",
        "with-diagrams",
        "with-frames",
        "实验性图解",
        "实验性截图",
        "辅助理解",
        "require-pdf",
        "allow-long-video",
        "start-button",
        "advanced-settings",
        "current-options-summary",
        "stage-list",
        "result-links",
        "failure-panel",
        "cancel-button",
        "preflight",
        "metadata",
        "audio",
        "transcript",
        "chunking",
        "summarization",
        "render",
        "URLSearchParams",
        "X-Bilifan-Token",
        "只影响 Whisper；已有字幕默认优先使用。",
        "/api/config",
        "/api/history",
        "/api/jobs",
        "/api/jobs/current",
        "setInterval",
        "打开笔记",
        "下载 PDF",
        "导出",
        "AI 自动判断",
        "逐字稿 TXT",
        "字幕 SRT",
        "Markdown",
        "更多",
        "结构化数据",
        "纳百川",
        "诊断信息",
        "文件列表",
        "batch-nabaichuan-button",
        "batch-urls",
        "batch-submit-button",
        "queue-clear-completed-button",
        "queue-list",
        "任务中心",
        "/api/jobs/batch",
        "/api/jobs/queue",
        "/api/jobs/queue/clear-completed",
        "exportNabaichuan",
        "音频文件",
        "data-folder-url",
        "openFolder",
        "retryAction",
        "重新生成总结",
        "教程步骤",
        "观点提炼",
        "会议纪要",
    ]

    for marker in required_strings:
        assert marker in html


def test_render_app_html_can_embed_token_for_fixed_entrypoint():
    html = render_app_html(token="embedded-token")
    script = _extract_inline_script(html)

    _run_node_ui_harness(
        script,
        location_search="",
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({
            path,
            method: options.method || "GET",
            token: options.headers ? options.headers.get("X-Bilifan-Token") : ""
          });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "教程步骤" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(fetchCalls.length > 0);
        assert(fetchCalls.every((call) => call.token === "embedded-token"));
        """,
    )


def test_render_app_html_contains_frontend_state_guards():
    html = render_app_html()

    assert "downloads current-P audio for local processing" in html
    assert "Codex CLI to summarize transcript chunks" in html
    assert "send transcript text to the model service" in html
    assert 'type="url"' in html
    assert "required" in html
    assert "state.currentStatus" in html
    assert (
        'elements.startButton.disabled = state.authExpired || !state.consentAccepted || ["running", "canceling"].includes(state.currentStatus)'
        in html
    )
    assert "markAuthExpired" in html
    assert "token 已失效" in html
    assert "请输入 B 站 URL。" in html
    assert "if (!payload.url)" in html
    assert "await loadConfig();" in html
    assert 'input[type="url"]' in html


def test_current_task_advanced_options_are_collapsed_by_default():
    html = render_app_html()

    advanced_start = html.index('<details id="advanced-settings"')
    advanced_tag = html[advanced_start : html.index(">", advanced_start)]

    assert "open" not in advanced_tag
    assert "高级设置" in html
    assert "current-options-summary" in html


def test_render_app_script_disables_start_without_consent_or_while_running():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: false }, defaults: { format: "html,pdf", language: "auto" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(elements["start-button"].disabled, true);
        assert.equal(elements["consent-banner"].classList.contains("active"), true);
        """,
    )

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "会议纪要" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "running",
              stage: "metadata",
              message: "Fetching metadata.",
              progress: [{ stage: "metadata", status: "running" }],
              artifacts: {},
              run_key: null
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(elements["start-button"].disabled, true);
        assert.equal(elements["job-message"].textContent, "Fetching metadata.");
        """,
    )


def test_render_app_script_blocks_empty_url_before_posting_job():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "教程步骤" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs") return jsonResponse({ job_id: "should-not-post" });
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        elements["url-input"].value = "   ";
        await elements["job-form"].listeners.submit({ preventDefault() {} });
        await flush();

        assert.equal(elements["job-message"].textContent, "请输入 B 站 URL。");
        assert.equal(elements["url-input"].focused, true);
        assert.equal(fetchCalls.filter((call) => call.path === "/api/jobs").length, 0);
        """,
    )


def test_render_app_script_defaults_summary_template_to_auto_when_config_omits_it():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(elements["summary-template-select"].value, "AI 自动判断");
        """,
    )


def test_render_app_script_submits_language_and_renders_export_actions():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "en", summary_template: "教程步骤" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "历史",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "succeeded",
                stage: "render",
                artifacts: {
                  html: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html?token=test-token",
                  pdf: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.pdf?token=test-token",
                  txt: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt?token=test-token",
                  srt: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.srt?token=test-token",
                  md: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/notes.md?token=test-token",
                  bundle: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json?token=test-token",
                  nabaichuan: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl?token=test-token",
                  audio: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/media/audio.mp3?token=test-token",
                  folder: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder?token=test-token"
                }
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {
                html: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.html",
                pdf: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/report.pdf",
                txt: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt",
                srt: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.srt",
                md: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/notes.md",
                bundle: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json",
                nabaichuan: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl",
                audio: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/media/audio.mp3",
                folder: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder"
              },
              run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000"
            });
          }
          if (path === "/api/jobs") {
            return jsonResponse({ job_id: "job-1", status: "running" });
          }
          if (path === "/api/jobs/batch") {
            return jsonResponse({ counts: { queued: 0, running: 0, succeeded: 2, failed: 0, canceled: 0 }, items: [] });
          }
          if (path.includes("/open-folder")) return jsonResponse({ ok: true });
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(elements["language-select"].value, "en");
        assert.equal(elements["summary-template-select"].value, "教程步骤");
        assert(elements["history-list"].innerHTML.includes("打开笔记"));
        assert(elements["history-list"].innerHTML.includes("下载 PDF"));
        assert(elements["history-list"].innerHTML.includes("逐字稿 TXT"));
        assert(elements["history-list"].innerHTML.includes("字幕 SRT"));
        assert(elements["history-list"].innerHTML.includes("Markdown"));
        assert(elements["history-list"].innerHTML.includes("结构化数据"));
        assert(elements["history-list"].innerHTML.includes("纳百川"));
        assert(elements["history-list"].innerHTML.includes("音频文件"));
        assert(elements["history-list"].innerHTML.includes("打开本地文件夹"));
        assert(elements["result-links"].innerHTML.includes("逐字稿 TXT"));
        assert(elements["result-links"].innerHTML.includes("字幕 SRT"));
        assert(elements["result-links"].innerHTML.includes("Markdown"));
        assert(elements["result-links"].innerHTML.includes("结构化数据"));
        assert(elements["result-links"].innerHTML.includes("纳百川"));
        assert(elements["result-links"].innerHTML.includes("音频文件"));
        assert(!elements["history-list"].innerHTML.includes(">HTML<"));
        assert(!elements["history-list"].innerHTML.includes(">diagnostics<"));
        assert(!elements["history-list"].innerHTML.includes(">file list<"));

        elements["url-input"].value = "https://www.bilibili.com/video/BV1abcDEF12G";
        elements["language-select"].value = "en";
        elements["summary-template-select"].value = "观点提炼";
        elements["with-diagrams"].checked = true;
        elements["with-frames"].checked = true;
        await elements["job-form"].listeners.submit({ preventDefault() {} });
        await flush();
        const jobCall = fetchCalls.find((call) => call.path === "/api/jobs");
        assert.equal(JSON.parse(jobCall.body).language, "en");
        assert.equal(JSON.parse(jobCall.body).summary_template, "观点提炼");
        assert.equal(JSON.parse(jobCall.body).with_diagrams, true);
        assert.equal(JSON.parse(jobCall.body).with_frames, true);

        elements["batch-urls"].value = "https://www.bilibili.com/video/BV1abcDEF12G\\nhttps://www.youtube.com/watch?v=dQw4w9WgXcQ";
        await elements["batch-submit-button"].listeners.click();
        await flush();
        const batchCall = fetchCalls.find((call) => call.path === "/api/jobs/batch");
        const batchBody = JSON.parse(batchCall.body);
        assert.equal(batchBody.urls.length, 2);
        assert.equal(batchBody.summary_template, "观点提炼");
        assert.equal(batchBody.with_diagrams, true);
        assert.equal(batchBody.with_frames, true);

        const clickTarget = {
          closest(selector) {
            if (selector !== "[data-folder-url]") return null;
            return {
              getAttribute(name) {
                assert.equal(name, "data-folder-url");
                return "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/open-folder?token=test-token";
              }
            };
          }
        };
        await document.listeners.click({ target: clickTarget });
        await flush();
        assert(fetchCalls.some((call) => call.method === "POST" && call.path.includes("/open-folder")));
        """,
    )


def test_render_app_script_updates_current_options_summary_and_keeps_advanced_options_active():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({
              consent: { local_processing: true },
              defaults: {
                format: "html,pdf",
                language: "auto",
                summary_template: "AI 自动判断",
                with_diagrams: false,
                with_frames: false,
                require_pdf: false
              }
            });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs") return jsonResponse({ job_id: "job-1", status: "running" });
          if (path === "/api/jobs/batch") return jsonResponse({ counts: {}, items: [] });
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["current-options-summary"].textContent.includes("HTML + PDF"));
        assert(elements["current-options-summary"].textContent.includes("AI 自动判断"));
        assert(elements["current-options-summary"].textContent.includes("自动语言"));

        elements["summary-template-select"].value = "观点提炼";
        elements["language-select"].value = "en";
        elements["with-diagrams"].checked = true;
        elements["require-pdf"].checked = true;
        elements["summary-template-select"].listeners.change();
        elements["language-select"].listeners.change();
        elements["with-diagrams"].listeners.change();
        elements["require-pdf"].listeners.change();

        assert(elements["current-options-summary"].textContent.includes("观点提炼"));
        assert(elements["current-options-summary"].textContent.includes("英文"));
        assert(elements["current-options-summary"].textContent.includes("图解"));
        assert(elements["current-options-summary"].textContent.includes("必须 PDF"));

        elements["url-input"].value = "https://www.bilibili.com/video/BV1abcDEF12G";
        await elements["job-form"].listeners.submit({ preventDefault() {} });
        await flush();
        const jobCall = fetchCalls.find((call) => call.path === "/api/jobs");
        const jobBody = JSON.parse(jobCall.body);
        assert.equal(jobBody.summary_template, "观点提炼");
        assert.equal(jobBody.language, "en");
        assert.equal(jobBody.with_diagrams, true);
        assert.equal(jobBody.require_pdf, true);

        elements["batch-urls"].value = "https://www.bilibili.com/video/BV1queueTEST";
        await elements["batch-submit-button"].listeners.click();
        await flush();
        const batchCall = fetchCalls.find((call) => call.path === "/api/jobs/batch");
        const batchBody = JSON.parse(batchCall.body);
        assert.equal(batchBody.summary_template, "观点提炼");
        assert.equal(batchBody.language, "en");
        assert.equal(batchBody.with_diagrams, true);
        assert.equal(batchBody.require_pdf, true);
        """,
    )


def test_render_app_script_preserves_open_action_menu_after_refresh():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "学习笔记" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "历史",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "succeeded",
                stage: "render",
                artifacts: {
                  md: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/notes.md",
                  txt: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/transcript.txt"
                }
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        const menuKey = "history:BV1abcDEF12G_p1/runs/2026-06-08_120000:export";
        assert(elements["history-list"].innerHTML.includes(`data-menu-key="${menuKey}"`));
        assert(!elements["history-list"].innerHTML.includes(`data-menu-key="${menuKey}" open`));

        rememberOpenMenu(menuKey, true);
        await loadHistory();
        await flush();

        assert(elements["history-list"].innerHTML.includes(`data-menu-key="${menuKey}" open`));
        """,
    )


def test_render_app_script_queue_can_clear_completed_jobs():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "学习笔记" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs/queue") {
            return jsonResponse({
              counts: { queued: 0, running: 0, succeeded: 5, failed: 0, canceled: 0 },
              total_items: 5,
              hidden_completed: 2,
              items: [{
                job_id: "job-5",
                status: "succeeded",
                stage: "render",
                message: "Report ready.",
                request: { url: "https://www.bilibili.com/video/BV1abcDEF12G?p=5" },
                run_key: "BV1abcDEF12G_p5/runs/2026-06-08_120000",
                artifacts: {}
              }]
            });
          }
          if (path === "/api/jobs/queue/clear-completed") {
            return jsonResponse({
              counts: { queued: 0, running: 0, succeeded: 0, failed: 0, canceled: 0 },
              total_items: 0,
              hidden_completed: 0,
              items: []
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["queue-summary"].textContent.includes("隐藏 2"));
        assert.equal(elements["queue-clear-completed-button"].disabled, false);

        await elements["queue-clear-completed-button"].listeners.click();
        await flush();

        assert(fetchCalls.some((call) => call.method === "POST" && call.path === "/api/jobs/queue/clear-completed"));
        assert(elements["queue-list"].innerHTML.includes("暂无队列任务"));
        """,
    )


def test_render_app_script_queue_item_uses_video_title_as_primary_label():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "AI 自动判断" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs/queue") {
            return jsonResponse({
              counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              visible_counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              total_items: 1,
              hidden_completed: 0,
              hidden_replaced: 0,
              items: [{
                job_id: "job-1",
                title: "真正的视频标题",
                status: "succeeded",
                stage: "render",
                message: "Report ready.",
                request: { url: "https://www.bilibili.com/video/BV1abcDEF12G?p=1" },
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                artifacts: {}
              }]
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["queue-list"].innerHTML.includes("真正的视频标题"));
        assert(elements["queue-list"].innerHTML.includes("BV1abcDEF12G?p=1"));
        assert(!elements["queue-list"].innerHTML.includes("<div class=\\"history-item-title\\">https://www.bilibili.com"));
        """,
    )


def test_render_app_script_task_center_shows_current_job_item():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "AI 自动判断" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              job_id: "current-1",
              status: "succeeded",
              stage: "render",
              message: "Report ready.",
              title: "单个入口视频标题",
              request: { url: "https://www.bilibili.com/video/BV1abcDEF12G?p=1" },
              progress: [],
              artifacts: {},
              run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000"
            });
          }
          if (path === "/api/jobs/queue") {
            return jsonResponse({
              counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              visible_counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              queue_counts: { queued: 0, running: 0, succeeded: 0, failed: 0, canceled: 0 },
              total_items: 1,
              hidden_completed: 0,
              hidden_replaced: 0,
              items: [{
                source: "current",
                job_id: "current-1",
                title: "单个入口视频标题",
                status: "succeeded",
                stage: "render",
                message: "Report ready.",
                request: { url: "https://www.bilibili.com/video/BV1abcDEF12G?p=1" },
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                artifacts: {}
              }]
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["queue-list"].innerHTML.includes("当前任务"));
        assert(elements["queue-list"].innerHTML.includes("单个入口视频标题"));
        assert(elements["queue-list"].innerHTML.includes("BV1abcDEF12G?p=1"));
        assert(!elements["queue-list"].innerHTML.includes("重新排队"));
        assert.equal(elements["queue-clear-completed-button"].disabled, true);
        """,
    )


def test_render_app_script_shows_transcript_source_labels():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "AI 自动判断" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "历史视频",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "succeeded",
                stage: "render",
                transcript_source_label: "B站字幕",
                artifacts: {}
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs/queue") {
            return jsonResponse({
              counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              visible_counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              queue_counts: { queued: 0, running: 0, succeeded: 1, failed: 0, canceled: 0 },
              total_items: 1,
              hidden_completed: 0,
              hidden_replaced: 0,
              items: [{
                source: "queue",
                job_id: "job-1",
                title: "队列视频",
                status: "succeeded",
                stage: "render",
                message: "Report ready.",
                transcript_source_label: "Whisper turbo",
                request: { url: "https://www.bilibili.com/video/BV1abcDEF12H?p=1" },
                run_key: "BV1abcDEF12H_p1/runs/2026-06-08_120000",
                artifacts: {}
              }]
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["history-list"].innerHTML.includes("逐字稿：B站字幕"));
        assert(elements["queue-list"].innerHTML.includes("逐字稿：Whisper turbo"));
        """,
    )


def test_render_app_script_renders_stage_names_in_chinese():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "学习笔记" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "失败历史",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "failed",
                stage: "summarization",
                artifacts: {}
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "running",
              stage: "audio",
              message: "Downloading audio.",
              progress: [
                { stage: "metadata", status: "done" },
                { stage: "audio", status: "running" },
                { stage: "transcript", status: "pending" }
              ],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs/queue") {
            return jsonResponse({
              counts: { queued: 0, running: 1, succeeded: 0, failed: 1, canceled: 0 },
              visible_counts: { queued: 0, running: 1, succeeded: 0, failed: 1, canceled: 0 },
              total_items: 2,
              hidden_completed: 0,
              hidden_replaced: 0,
              items: [{
                job_id: "job-1",
                status: "failed",
                stage: "interrupted",
                message: "Service restarted before this queue job finished.",
                request: { url: "https://www.bilibili.com/video/BV1abcDEF12G" },
                artifacts: {}
              }]
            });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["stage-list"].innerHTML.includes("读取视频信息"));
        assert(elements["stage-list"].innerHTML.includes("下载音频"));
        assert(elements["stage-list"].innerHTML.includes("获取逐字稿"));
        assert(elements["stage-list"].innerHTML.includes("运行中 当前"));
        assert(elements["stage-list"].innerHTML.includes("待处理"));
        assert(elements["stage-list"].innerHTML.includes("任务: 运行中"));
        assert(!elements["stage-list"].innerHTML.includes(">audio<"));
        assert(elements["queue-list"].innerHTML.includes("服务中断"));
        assert(elements["history-list"].innerHTML.includes("失败阶段: 生成总结"));
        """,
    )


def test_render_app_script_exports_nabaichuan_from_history_and_batch_button():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "会议纪要" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "历史",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "succeeded",
                stage: "render",
                artifacts: {
                  bundle: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json?token=test-token"
                }
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "succeeded",
              stage: "render",
              message: "",
              progress: [],
              artifacts: {
                bundle: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/content_bundle.json"
              },
              run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000"
            });
          }
          if (path === "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/exports/nabaichuan") {
            return jsonResponse({ ok: true, artifact: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/nabaichuan.jsonl" });
          }
          if (path === "/api/exports/nabaichuan/batch") {
            return jsonResponse({ ok: true, artifact: "/api/exports/nabaichuan_batch_20260612_120000.jsonl", exported_runs: 1, skipped_runs: 0 });
          }
          if (path === "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry") {
            return jsonResponse({ status: "running" });
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["history-list"].innerHTML.includes("导出到纳百川"));
        assert(elements["result-links"].innerHTML.includes("导出到纳百川"));
        assert(elements["history-list"].innerHTML.includes("重新生成总结"));
        assert(elements["result-links"].innerHTML.includes("重新生成总结"));

        const nabaichuanTarget = {
          closest(selector) {
            if (selector !== "[data-nabaichuan-run-key]") return null;
            return {
              getAttribute(name) {
                assert.equal(name, "data-nabaichuan-run-key");
                return "BV1abcDEF12G_p1/runs/2026-06-08_120000";
              }
            };
          }
        };
        await document.listeners.click({ target: nabaichuanTarget });
        await flush();
        assert(fetchCalls.some((call) => call.method === "POST" && call.path.endsWith("/exports/nabaichuan")));

        const resummarizeTarget = {
          closest(selector) {
            if (selector !== "[data-resummarize-run-key]") return null;
            return {
              getAttribute(name) {
                assert.equal(name, "data-resummarize-run-key");
                return "BV1abcDEF12G_p1/runs/2026-06-08_120000";
              }
            };
          }
        };
        await document.listeners.click({ target: resummarizeTarget });
        await flush();
        const resummarizeCall = fetchCalls.find((call) => call.method === "POST" && call.path.endsWith("/retry"));
        assert.equal(JSON.parse(resummarizeCall.body).from_stage, "summarization");
        assert.equal(JSON.parse(resummarizeCall.body).summary_template, "会议纪要");
        assert.equal(JSON.parse(resummarizeCall.body).with_diagrams, false);
        assert.equal(JSON.parse(resummarizeCall.body).with_frames, false);

        await elements["batch-nabaichuan-button"].listeners.click();
        await flush();
        assert(fetchCalls.some((call) => call.method === "POST" && call.path === "/api/exports/nabaichuan/batch"));
        assert(elements["job-message"].textContent.includes("已批量导出 1 个 run"));
        """,
    )


def test_render_app_script_cancels_running_job_and_retries_failed_run():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        let jobPolls = 0;
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "会议纪要" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            jobPolls += 1;
            if (jobPolls === 1) {
              return jsonResponse({
                status: "running",
                stage: "audio",
                message: "Downloading audio.",
                progress: [{ stage: "audio", status: "running" }],
                artifacts: {},
                run_key: null,
                retry_actions: []
              });
            }
            return jsonResponse({
              status: "failed",
              stage: "summarization",
              message: "codex missing",
              progress: [{ stage: "summarization", status: "failed" }],
              artifacts: { diagnostics: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json" },
              run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
              retry_actions: ["summarization", "bundle"],
              friendly_error: {
                title: "Codex CLI 未找到",
                cause: "找不到 codex。",
                next_action: "在 Terminal 中修复 codex。"
              }
            });
          }
          if (path === "/api/jobs/current/cancel") return jsonResponse({ status: "canceling" });
          if (path === "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry") return jsonResponse({ status: "running" });
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(elements["cancel-button"].disabled, false);
        await elements["cancel-button"].listeners.click();
        await flush();
        assert(fetchCalls.some((call) => call.method === "POST" && call.path === "/api/jobs/current/cancel"));

        await loadCurrentJob();
        await flush();
        assert(elements["failure-panel"].innerHTML.includes("Codex CLI 未找到"));

        const retryTarget = {
          closest(selector) {
            if (selector !== "[data-retry-stage]") return null;
            return {
              getAttribute(name) {
                if (name === "data-retry-stage") return "summarization";
                if (name === "data-retry-run-key") return "BV1abcDEF12G_p1/runs/2026-06-08_120000";
                return "";
              }
            };
          }
        };
        await document.listeners.click({ target: retryTarget });
        await flush();
        const retryCall = fetchCalls.find((call) => call.method === "POST" && call.path.includes("/retry"));
        assert.equal(JSON.parse(retryCall.body).from_stage, "summarization");
        assert.equal(JSON.parse(retryCall.body).summary_template, "会议纪要");
        assert.equal(JSON.parse(retryCall.body).with_diagrams, false);
        assert.equal(JSON.parse(retryCall.body).with_frames, false);
        """,
    )


def test_render_app_script_retries_failed_history_item_with_its_run_key():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto", summary_template: "观点提炼" } });
          }
          if (path === "/api/history") {
            return jsonResponse({
              items: [{
                title: "失败历史",
                output_id: "BV1abcDEF12G_p1",
                run_key: "BV1abcDEF12G_p1/runs/2026-06-08_120000",
                status: "failed",
                stage: "summarization",
                artifacts: { diagnostics: "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/files/diagnostics.json" },
                retry_actions: ["summarization"],
                friendly_error: {
                  title: "Codex CLI 未找到",
                  cause: "找不到 codex。",
                  next_action: "在 Terminal 中修复 codex。"
                }
              }]
            });
          }
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null,
              retry_actions: []
            });
          }
          if (path === "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry") return jsonResponse({ status: "running" });
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert(elements["history-list"].innerHTML.includes("Codex CLI 未找到"));
        assert(elements["history-list"].innerHTML.includes("找不到 codex。"));
        assert(elements["history-list"].innerHTML.includes("重试总结"));

        const retryTarget = {
          closest(selector) {
            if (selector !== "[data-retry-stage]") return null;
            return {
              getAttribute(name) {
                if (name === "data-retry-stage") return "summarization";
                if (name === "data-retry-run-key") return "BV1abcDEF12G_p1/runs/2026-06-08_120000";
                return "";
              }
            };
          }
        };
        await document.listeners.click({ target: retryTarget });
        await flush();

        const retryCall = fetchCalls.find((call) => call.method === "POST" && call.path.includes("/retry"));
        assert.equal(retryCall.path, "/api/runs/BV1abcDEF12G_p1/runs/2026-06-08_120000/retry");
        assert.equal(JSON.parse(retryCall.body).from_stage, "summarization");
        assert.equal(JSON.parse(retryCall.body).summary_template, "观点提炼");
        assert.equal(JSON.parse(retryCall.body).with_diagrams, false);
        assert.equal(JSON.parse(retryCall.body).with_frames, false);
        """,
    )


def test_render_app_script_reloads_config_after_consent_conflict():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        let configCalls = 0;
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            configCalls += 1;
            return jsonResponse({
              consent: { local_processing: configCalls === 1 },
              defaults: { format: "html,pdf", language: "auto" }
            });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({
              status: "idle",
              stage: "preflight",
              message: "",
              progress: [],
              artifacts: {},
              run_key: null
            });
          }
          if (path === "/api/jobs") {
            return jsonResponse(
              { detail: "Local processing consent is required before starting a job." },
              false,
              "Conflict"
            );
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        elements["url-input"].value = "https://www.bilibili.com/video/BV1abcDEF12G";
        await elements["job-form"].listeners.submit({ preventDefault() {} });
        await flush();

        assert.equal(fetchCalls.filter((call) => call.path === "/api/config").length, 2);
        assert.equal(elements["consent-banner"].classList.contains("active"), true);
        assert.equal(elements["start-button"].disabled, true);
        assert.equal(elements["job-message"].textContent, "Local processing consent is required before starting a job.");
        """,
    )


def test_render_app_script_stops_polling_when_token_is_invalid():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf", language: "auto" } });
          }
          if (path === "/api/history") return jsonResponse({ items: [] });
          if (path === "/api/jobs/current") {
            return jsonResponse({ detail: "Invalid Bilifan Web UI token." }, false, "Forbidden", 403);
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        """,
        assertions="""
        assert.equal(global.__clearedInterval, 1);
        assert.equal(elements["start-button"].disabled, true);
        assert(elements["job-message"].className.includes("error"));
        assert(elements["job-message"].textContent.includes("token 已失效"));

        await global.__poll.callback();
        await flush();
        assert.equal(fetchCalls.filter((call) => call.path === "/api/jobs/current").length, 1);
        """,
    )


def test_render_app_html_has_no_external_http_resources():
    html = render_app_html()

    assert "http://" not in html
    assert "https://" not in html


def _extract_inline_script(html):
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match is not None
    return match.group(1)


def _run_node_ui_harness(
    script,
    *,
    fetch_logic,
    assertions,
    location_search="?token=test-token",
):
    if shutil.which("node") is None:
        pytest.skip("node is required for UI behavior tests")

    node_program = f"""
    const assert = require("assert");
    const source = {json.dumps(script)};
    const fetchCalls = [];
    const elements = {{}};

    class ClassList {{
      constructor() {{
        this.names = new Set();
      }}
      add(name) {{
        this.names.add(name);
      }}
      remove(name) {{
        this.names.delete(name);
      }}
      toggle(name, force) {{
        if (force === undefined) {{
          if (this.names.has(name)) {{
            this.names.delete(name);
            return false;
          }}
          this.names.add(name);
          return true;
        }}
        if (force) this.names.add(name);
        else this.names.delete(name);
        return Boolean(force);
      }}
      contains(name) {{
        return this.names.has(name);
      }}
    }}

    class Element {{
      constructor(id) {{
        this.id = id;
        this.checked = false;
        this.className = "";
        this.disabled = false;
        this.focused = false;
        this.innerHTML = "";
        this.listeners = {{}};
        this.textContent = "";
        this.value = "";
        this.classList = new ClassList();
      }}
      addEventListener(eventName, callback) {{
        this.listeners[eventName] = callback;
      }}
      focus() {{
        this.focused = true;
      }}
    }}

    global.document = {{
      listeners: {{}},
      addEventListener(eventName, callback) {{
        this.listeners[eventName] = callback;
      }},
      getElementById(id) {{
        if (!elements[id]) elements[id] = new Element(id);
        return elements[id];
      }}
    }};
    global.location = {{ search: {json.dumps(location_search)}, origin: "http://127.0.0.1:8765" }};
    global.window = {{ location: global.location }};
    global.setInterval = (callback, interval) => {{
      global.__poll = {{ callback, interval }};
      return 1;
    }};
    global.clearInterval = (timer) => {{
      global.__clearedInterval = timer;
    }};

    function jsonResponse(payload, ok = true, statusText = "OK", status = ok ? 200 : 500) {{
      return {{
        ok,
        status,
        statusText,
        async json() {{
          return payload;
        }}
      }};
    }}

    {textwrap.dedent(fetch_logic)}
    global.fetch = fetchMock;

    async function flush() {{
      for (let index = 0; index < 6; index += 1) {{
        await new Promise((resolve) => setImmediate(resolve));
      }}
    }}

    (async () => {{
      eval(source);
      await flush();
      {textwrap.dedent(assertions)}
    }})().catch((error) => {{
      console.error(error && error.stack ? error.stack : error);
      process.exit(1);
    }});
    """

    result = subprocess.run(
        ["node", "-e", node_program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
