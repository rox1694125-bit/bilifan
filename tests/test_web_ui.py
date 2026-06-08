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
        "force-whisper",
        "require-pdf",
        "allow-long-video",
        "start-button",
        "stage-list",
        "result-links",
        "failure-panel",
        "preflight",
        "metadata",
        "audio",
        "transcript",
        "chunking",
        "summarization",
        "render",
        "URLSearchParams",
        "X-Bilifan-Token",
        "/api/config",
        "/api/history",
        "/api/jobs",
        "/api/jobs/current",
        "setInterval",
    ]

    for marker in required_strings:
        assert marker in html


def test_render_app_html_contains_frontend_state_guards():
    html = render_app_html()

    assert 'type="url"' in html
    assert "required" in html
    assert "state.currentStatus" in html
    assert (
        'elements.startButton.disabled = !state.consentAccepted || state.currentStatus === "running"'
        in html
    )
    assert "请输入 B 站 URL。" in html
    assert "if (!payload.url)" in html
    assert "await loadConfig();" in html


def test_render_app_script_disables_start_without_consent_or_while_running():
    script = _extract_inline_script(render_app_html())

    _run_node_ui_harness(
        script,
        fetch_logic="""
        async function fetchMock(path, options = {}) {
          fetchCalls.push({ path, method: options.method || "GET", body: options.body || "" });
          if (path === "/api/config") {
            return jsonResponse({ consent: { local_processing: false }, defaults: { format: "html,pdf" } });
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
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf" } });
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
            return jsonResponse({ consent: { local_processing: true }, defaults: { format: "html,pdf" } });
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
              defaults: { format: "html,pdf" }
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


def test_render_app_html_has_no_external_http_resources():
    html = render_app_html()

    assert "http://" not in html
    assert "https://" not in html


def _extract_inline_script(html):
    match = re.search(r"<script>(.*?)</script>", html, re.DOTALL)
    assert match is not None
    return match.group(1)


def _run_node_ui_harness(script, *, fetch_logic, assertions):
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
      getElementById(id) {{
        if (!elements[id]) elements[id] = new Element(id);
        return elements[id];
      }}
    }};
    global.location = {{ search: "?token=test-token", origin: "http://127.0.0.1:8765" }};
    global.window = {{ location: global.location }};
    global.setInterval = (callback, interval) => {{
      global.__poll = {{ callback, interval }};
      return 1;
    }};

    function jsonResponse(payload, ok = true, statusText = "OK") {{
      return {{
        ok,
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
