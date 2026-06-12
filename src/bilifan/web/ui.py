import json
from textwrap import dedent


def render_app_html(token: str = "") -> str:
    embedded_token = json.dumps(token)
    return dedent(
        """\
        <!doctype html>
        <html lang="zh-CN">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Bilifan Web UI</title>
          <style>
            :root {
              color-scheme: light;
              --bg: #f3f5f7;
              --panel: #ffffff;
              --panel-muted: #f7f8fa;
              --border: #d7dde3;
              --border-strong: #b9c2cb;
              --text: #16202a;
              --muted: #5c6977;
              --accent: #235ea7;
              --accent-strong: #18497f;
              --warn: #a66300;
              --danger: #b03737;
              --success: #1e6a45;
              --shadow: 0 8px 24px rgba(17, 24, 39, 0.06);
              font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }

            * { box-sizing: border-box; }
            body {
              margin: 0;
              background: var(--bg);
              color: var(--text);
            }
            .shell {
              min-height: 100vh;
              padding: 16px;
            }
            .layout {
              display: grid;
              grid-template-columns: 320px minmax(0, 1fr);
              gap: 16px;
              align-items: start;
            }
            .brandbar {
              display: flex;
              align-items: baseline;
              justify-content: space-between;
              gap: 12px;
              margin-bottom: 16px;
            }
            .brandbar h1 {
              font-size: 20px;
            }
            .panel {
              background: var(--panel);
              border: 1px solid var(--border);
              border-radius: 8px;
              box-shadow: var(--shadow);
            }
            .panel-header,
            .panel-body {
              padding: 14px 16px;
            }
            .panel-header {
              border-bottom: 1px solid var(--border);
            }
            h1, h2, h3, p { margin: 0; }
            h1 {
              font-size: 18px;
              font-weight: 700;
            }
            h2 {
              font-size: 14px;
              font-weight: 700;
            }
            .subtle {
              color: var(--muted);
              font-size: 12px;
            }
            .stack {
              display: grid;
              gap: 12px;
            }
            .field-grid {
              display: grid;
              grid-template-columns: minmax(0, 1fr) 180px;
              gap: 12px;
            }
            label {
              display: grid;
              gap: 6px;
              font-size: 12px;
              color: var(--muted);
            }
            input[type="text"],
            input[type="url"],
            select,
            button {
              font: inherit;
            }
            input[type="text"],
            input[type="url"],
            select {
              width: 100%;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fff;
              color: var(--text);
              padding: 10px 12px;
            }
            input[type="text"]:focus,
            input[type="url"]:focus,
            select:focus,
            button:focus {
              outline: 2px solid rgba(35, 94, 167, 0.18);
              outline-offset: 1px;
              border-color: var(--accent);
            }
            .checks {
              display: grid;
              grid-template-columns: repeat(3, minmax(0, 1fr));
              gap: 10px;
            }
            .check {
              display: flex;
              align-items: center;
              gap: 8px;
              min-height: 42px;
              padding: 10px 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              color: var(--text);
            }
            .check input {
              margin: 0;
              inline-size: 15px;
              block-size: 15px;
            }
            .field {
              min-height: 42px;
              padding: 10px 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
            }
            .field select {
              padding: 7px 10px;
            }
            .hint {
              color: var(--muted);
              font-size: 11px;
            }
            .actions {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 12px;
            }
            button {
              border: 1px solid var(--border-strong);
              border-radius: 6px;
              padding: 10px 14px;
              background: #fff;
              color: var(--text);
              cursor: pointer;
            }
            button.primary {
              border-color: var(--accent);
              background: var(--accent);
              color: #fff;
            }
            button.primary:hover { background: var(--accent-strong); }
            button.danger {
              border-color: #c77f7f;
              color: var(--danger);
              background: #fff8f8;
            }
            button:disabled {
              cursor: not-allowed;
              opacity: 0.55;
            }
            .banner {
              display: none;
              margin-bottom: 12px;
              padding: 12px 14px;
              border: 1px solid #e3c894;
              border-radius: 8px;
              background: #fff8ea;
            }
            .banner.active { display: block; }
            .banner-row {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 12px;
            }
            .status-line {
              padding: 10px 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              font-size: 13px;
            }
            .status-line.error {
              border-color: #e4b0b0;
              background: #fff3f3;
              color: var(--danger);
            }
            ul {
              list-style: none;
              padding: 0;
              margin: 0;
            }
            .history-list,
            .stage-list,
            .link-list {
              display: grid;
              gap: 10px;
            }
            .history-item,
            .stage-item {
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              padding: 10px 12px;
            }
            .history-item-title,
            .stage-name {
              font-size: 13px;
              font-weight: 600;
            }
            .history-meta,
            .history-links,
            .stage-meta {
              display: flex;
              flex-wrap: wrap;
              gap: 8px 12px;
              margin-top: 6px;
              font-size: 12px;
              color: var(--muted);
            }
            .history-links a,
            .link-list a,
            .link-button {
              color: var(--accent);
              text-decoration: none;
            }
            .history-links a:hover,
            .link-list a:hover,
            .link-button:hover {
              text-decoration: underline;
            }
            .link-button {
              border: 0;
              background: transparent;
              padding: 0;
              font-size: 12px;
              cursor: pointer;
            }
            .pill {
              display: inline-flex;
              align-items: center;
              padding: 2px 8px;
              border-radius: 999px;
              border: 1px solid var(--border);
              background: #fff;
              color: var(--muted);
            }
            .pill.running { color: var(--accent); border-color: #bcd0ea; }
            .pill.done,
            .pill.succeeded { color: var(--success); border-color: #b7d8c7; }
            .pill.failed { color: var(--danger); border-color: #e2bbbb; }
            .muted-panel {
              border: 1px dashed var(--border);
              border-radius: 6px;
              padding: 12px;
              color: var(--muted);
              font-size: 13px;
              background: #fbfcfd;
            }
            .failure-panel {
              display: none;
              border: 1px solid #e4b0b0;
              border-radius: 6px;
              padding: 12px;
              background: #fff3f3;
              color: var(--danger);
            }
            .failure-panel.active { display: block; }

            @media (max-width: 900px) {
              .layout,
              .field-grid,
              .checks {
                grid-template-columns: 1fr;
              }
              .brandbar,
              .banner-row,
              .actions {
                align-items: stretch;
                flex-direction: column;
              }
            }
          </style>
        </head>
        <body>
          <main class="shell">
            <header class="brandbar">
              <h1>Bilifan Web UI</h1>
              <p class="subtle">local summary workbench</p>
            </header>
            <div class="layout">
              <aside class="panel">
                <div class="panel-header">
                  <h1>历史记录</h1>
                  <p class="subtle">latest run / artifacts</p>
                </div>
                <div class="panel-body">
                  <ul id="history-list" class="history-list"></ul>
                </div>
              </aside>

              <section class="stack">
                <section class="panel">
                  <div class="panel-header">
                    <h1>当前任务</h1>
                    <p class="subtle">本地工作台</p>
                  </div>
                  <div class="panel-body stack">
                    <div id="consent-banner" class="banner" role="status" aria-live="polite">
                      <div class="banner-row">
                        <div class="stack" style="gap:4px;">
                          <h2>需要先确认本地处理告知</h2>
                          <p class="subtle">Bilifan prepares runs locally on this machine, downloads current-P audio for local processing, and writes output files under ./outputs. By default it calls your configured Codex CLI to summarize transcript chunks, which may send transcript text to the model service behind that Codex account.</p>
                          <p class="subtle">未接受前不会启动新任务。</p>
                        </div>
                        <button id="consent-button" type="button">接受并继续</button>
                      </div>
                    </div>

                    <form id="job-form" class="stack">
                      <div class="field-grid">
                        <label for="url-input">
                          视频 URL
                          <input id="url-input" name="url" type="url" required autocomplete="off" spellcheck="false">
                        </label>
                        <label for="format-select">
                          输出格式
                          <select id="format-select" name="format">
                            <option value="html">html</option>
                            <option value="html,pdf">html,pdf</option>
                          </select>
                        </label>
                      </div>

                      <div class="checks">
                        <label class="field" for="language-select">
                          <span>语言</span>
                          <select id="language-select" name="language">
                            <option value="auto">auto</option>
                            <option value="zh">中文</option>
                            <option value="en">英文</option>
                          </select>
                          <span class="hint">只影响 Whisper；已有字幕默认优先使用。</span>
                        </label>
                        <label class="check" for="force-whisper">
                          <input id="force-whisper" name="force_whisper" type="checkbox">
                          <span>Force Whisper</span>
                        </label>
                        <label class="check" for="require-pdf">
                          <input id="require-pdf" name="require_pdf" type="checkbox">
                          <span>Require PDF</span>
                        </label>
                        <label class="check" for="allow-long-video">
                          <input id="allow-long-video" name="allow_long_video" type="checkbox">
                          <span>Allow long video</span>
                        </label>
                      </div>

                      <div class="actions">
                        <div id="job-message" class="status-line">等待输入。</div>
                        <div style="display:flex; gap:8px; align-items:center;">
                          <button id="cancel-button" class="danger" type="button">取消</button>
                          <button id="start-button" class="primary" type="submit">开始</button>
                        </div>
                      </div>
                    </form>
                  </div>
                </section>

                <section class="panel">
                  <div class="panel-header">
                    <h1>进度</h1>
                    <p class="subtle">/api/jobs/current</p>
                  </div>
                  <div class="panel-body stack">
                    <ul id="stage-list" class="stage-list"></ul>
                    <div id="result-links" class="link-list"></div>
                    <div id="failure-panel" class="failure-panel"></div>
                  </div>
                </section>
              </section>
            </div>
          </main>

          <script>
            const STAGES = ["preflight", "metadata", "audio", "transcript", "chunking", "summarization", "render"];
            const embeddedToken = __BILIFAN_EMBEDDED_TOKEN__;
            const token = new URLSearchParams(location.search).get("token") || embeddedToken;

            const state = {
              authExpired: false,
              consentAccepted: false,
              currentStatus: "idle",
              currentRunKey: "",
              pollingTimer: null,
            };

            const elements = {
              historyList: document.getElementById("history-list"),
              jobForm: document.getElementById("job-form"),
              urlInput: document.getElementById("url-input"),
              formatSelect: document.getElementById("format-select"),
              languageSelect: document.getElementById("language-select"),
              forceWhisper: document.getElementById("force-whisper"),
              requirePdf: document.getElementById("require-pdf"),
              allowLongVideo: document.getElementById("allow-long-video"),
              startButton: document.getElementById("start-button"),
              cancelButton: document.getElementById("cancel-button"),
              jobMessage: document.getElementById("job-message"),
              consentBanner: document.getElementById("consent-banner"),
              consentButton: document.getElementById("consent-button"),
              stageList: document.getElementById("stage-list"),
              resultLinks: document.getElementById("result-links"),
              failurePanel: document.getElementById("failure-panel"),
            };

            function withToken(url) {
              if (!url) return "";
              const resolved = new URL(url, location.origin);
              if (token && !resolved.searchParams.get("token")) {
                resolved.searchParams.set("token", token);
              }
              return resolved.pathname + resolved.search;
            }

            function runFilesUrl(runKey) {
              return runKey ? withToken(`/api/runs/${runKey}/files`) : "";
            }

            async function apiFetch(path, options = {}) {
              const headers = new Headers(options.headers || {});
              if (token) {
                headers.set("X-Bilifan-Token", token);
              }
              const response = await fetch(path, { ...options, headers });
              if (!response.ok) {
                if (response.status === 403) {
                  throw new Error(markAuthExpired());
                }
                let detail = response.statusText || "Request failed.";
                try {
                  const payload = await response.json();
                  if (payload && typeof payload.detail === "string") {
                    detail = payload.detail;
                  }
                } catch (error) {
                  // ignore json parse failure
                }
                throw new Error(detail);
              }
              return response.json();
            }

            function stopPolling() {
              if (state.pollingTimer) {
                clearInterval(state.pollingTimer);
                state.pollingTimer = null;
              }
            }

            function markAuthExpired() {
              const message = "当前 Web UI token 已失效，请使用 Terminal 最新打印的地址重新打开页面。";
              state.authExpired = true;
              state.currentStatus = "idle";
              stopPolling();
              updateStartButton();
              setJobMessage(message, true);
              return message;
            }

            function setJobMessage(message, isError = false) {
              elements.jobMessage.textContent = message;
              elements.jobMessage.className = isError ? "status-line error" : "status-line";
            }

            function updateStartButton() {
              elements.startButton.disabled = state.authExpired || !state.consentAccepted || ["running", "canceling"].includes(state.currentStatus);
              elements.cancelButton.disabled = state.authExpired || state.currentStatus !== "running";
            }

            function renderStageList(progress, activeStage, jobStatus) {
              const items = Array.isArray(progress) && progress.length ? progress : STAGES.map((stage) => ({ stage, status: "pending" }));
              elements.stageList.innerHTML = items.map((item) => {
                const stage = typeof item.stage === "string" ? item.stage : "";
                const status = typeof item.status === "string" ? item.status : "pending";
                const active = stage === activeStage ? " 当前" : "";
                const statusClass = ["pending", "running", "done", "failed", "succeeded"].includes(status) ? status : "pending";
                return `
                  <li class="stage-item">
                    <div class="stage-name">${escapeHtml(stage)}</div>
                    <div class="stage-meta">
                      <span class="pill ${statusClass}">${escapeHtml(status)}${escapeHtml(active)}</span>
                      <span>job: ${escapeHtml(jobStatus || "idle")}</span>
                    </div>
                  </li>
                `;
              }).join("");
            }

            function renderLinks(artifacts, runKey) {
              const links = [];
              if (artifacts && typeof artifacts === "object") {
                if (artifacts.html) links.push(linkItem("report.html", artifacts.html));
                if (artifacts.pdf) links.push(linkItem("report.pdf", artifacts.pdf));
                if (artifacts.txt) links.push(linkItem("TXT", artifacts.txt));
                if (artifacts.srt) links.push(linkItem("SRT", artifacts.srt));
                if (artifacts.md) links.push(linkItem("MD", artifacts.md));
                if (artifacts.bundle) links.push(linkItem("Bundle", artifacts.bundle));
                if (artifacts.audio) links.push(linkItem("audio", artifacts.audio));
                if (artifacts.diagnostics) links.push(linkItem("diagnostics", artifacts.diagnostics));
                if (artifacts.folder) links.push(folderButton("打开本地文件夹", artifacts.folder));
              }
              if (runKey) {
                links.push(linkItem("file list", runFilesUrl(runKey)));
              }
              elements.resultLinks.innerHTML = links.length
                ? links.join("")
                : '<div class="muted-panel">当前没有可用 artifacts。</div>';
            }

            function linkItem(label, href) {
              const url = withToken(href);
              return `<a href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
            }

            function folderButton(label, href) {
              const url = withToken(href);
              return `<button class="link-button" type="button" data-folder-url="${escapeAttr(url)}">${escapeHtml(label)}</button>`;
            }

            function renderFailure(stage, message, diagnostics, runKey, friendlyError, retryActions) {
              const links = [];
              if (diagnostics) {
                links.push(`<a href="${escapeAttr(withToken(diagnostics))}" target="_blank" rel="noopener noreferrer">diagnostics</a>`);
              }
              if (runKey) {
                links.push(`<a href="${escapeAttr(runFilesUrl(runKey))}" target="_blank" rel="noopener noreferrer">file list</a>`);
              }
              const linkMarkup = links.length ? `<div class="history-links">${links.join("")}</div>` : "";
              const friendly = friendlyError && typeof friendlyError === "object" ? friendlyError : null;
              const title = friendly && friendly.title ? friendly.title : "任务失败";
              const cause = friendly && friendly.cause ? friendly.cause : (message || "Unknown error.");
              const nextAction = friendly && friendly.next_action ? `<div>${escapeHtml(friendly.next_action)}</div>` : "";
              const retryButtons = Array.isArray(retryActions) && retryActions.length && runKey
                ? `<div class="history-links">${retryActions.map((retryStage) => `<button class="link-button" type="button" data-retry-stage="${escapeAttr(retryStage)}" data-retry-run-key="${escapeAttr(runKey)}">${escapeHtml(retryLabel(retryStage))}</button>`).join("")}</div>`
                : "";
              elements.failurePanel.innerHTML = `
                <div class="stack" style="gap:6px;">
                  <h2>${escapeHtml(title)}</h2>
                  <div>stage: ${escapeHtml(stage || "preflight")}</div>
                  <div>${escapeHtml(cause)}</div>
                  ${nextAction}
                  ${retryButtons}
                  ${linkMarkup}
                </div>
              `;
              elements.failurePanel.classList.add("active");
            }

            function clearFailure() {
              elements.failurePanel.textContent = "";
              elements.failurePanel.classList.remove("active");
            }

            function renderHistory(items) {
              if (!Array.isArray(items) || items.length === 0) {
                elements.historyList.innerHTML = '<li class="muted-panel">暂无 latest run。</li>';
                return;
              }
              elements.historyList.innerHTML = items.map((item) => {
                const artifacts = item && typeof item.artifacts === "object" ? item.artifacts : {};
                const links = [];
                if (artifacts.html) links.push(linkItem("HTML", artifacts.html));
                if (artifacts.pdf) links.push(linkItem("PDF", artifacts.pdf));
                if (artifacts.txt) links.push(linkItem("TXT", artifacts.txt));
                if (artifacts.srt) links.push(linkItem("SRT", artifacts.srt));
                if (artifacts.md) links.push(linkItem("MD", artifacts.md));
                if (artifacts.bundle) links.push(linkItem("Bundle", artifacts.bundle));
                if (artifacts.audio) links.push(linkItem("audio", artifacts.audio));
                if (artifacts.diagnostics) links.push(linkItem("diagnostics", artifacts.diagnostics));
                if (artifacts.folder) links.push(folderButton("打开本地文件夹", artifacts.folder));
                if (item.run_key) links.push(linkItem("file list", `/api/runs/${item.run_key}/files`));
                const friendly = item.friendly_error && typeof item.friendly_error === "object" ? item.friendly_error : null;
                const retryActions = Array.isArray(item.retry_actions) ? item.retry_actions : [];
                const retryButtons = retryActions.length && item.run_key
                  ? retryActions.map((retryStage) => `<button class="link-button" type="button" data-retry-stage="${escapeAttr(retryStage)}" data-retry-run-key="${escapeAttr(item.run_key)}">${escapeHtml(retryLabel(retryStage))}</button>`).join("")
                  : "";
                const failureDetail = friendly
                  ? `<div class="history-meta"><span>${escapeHtml(friendly.title || "任务失败")}</span><span>${escapeHtml(friendly.cause || "")}</span><span>${escapeHtml(friendly.next_action || "")}</span></div>`
                  : "";
                return `
                  <li class="history-item">
                    <div class="history-item-title">${escapeHtml(item.title || item.output_id || "-")}</div>
                    <div class="history-meta">
                      <span>${escapeHtml(item.output_id || "-")}</span>
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(item.status || "-")}</span>
                      <span>stage: ${escapeHtml(item.stage || "-")}</span>
                    </div>
                    ${failureDetail}
                    <div class="history-links">${links.join("")}${retryButtons}</div>
                  </li>
                `;
              }).join("");
            }

            function escapeHtml(value) {
              return String(value)
                .replaceAll("&", "&amp;")
                .replaceAll("<", "&lt;")
                .replaceAll(">", "&gt;")
                .replaceAll('"', "&quot;")
                .replaceAll("'", "&#39;");
            }

            function escapeAttr(value) {
              return escapeHtml(value);
            }

            function retryLabel(stage) {
              if (stage === "summarization") return "重试总结";
              if (stage === "render") return "重试渲染";
              if (stage === "bundle") return "重试 Bundle";
              return `重试 ${stage}`;
            }

            async function loadConfig() {
              const data = await apiFetch("/api/config");
              const defaults = data.defaults || {};
              const consent = data.consent || {};
              state.consentAccepted = Boolean(consent.local_processing);
              elements.formatSelect.value = defaults.format || "html,pdf";
              elements.languageSelect.value = defaults.language || "auto";
              elements.forceWhisper.checked = Boolean(defaults.force_whisper);
              elements.requirePdf.checked = Boolean(defaults.require_pdf);
              elements.allowLongVideo.checked = Boolean(defaults.allow_long_video);
              elements.consentBanner.classList.toggle("active", !state.consentAccepted);
              updateStartButton();
            }

            async function loadHistory() {
              if (state.authExpired) return;
              try {
                const data = await apiFetch("/api/history");
                renderHistory(data.items || []);
              } catch (error) {
                if (state.authExpired) return;
                elements.historyList.innerHTML = `<li class="muted-panel">${escapeHtml(error.message || "History load failed.")}</li>`;
              }
            }

            async function loadCurrentJob() {
              if (state.authExpired) return;
              try {
                const data = await apiFetch("/api/jobs/current");
                state.currentStatus = typeof data.status === "string" ? data.status : "idle";
                state.currentRunKey = typeof data.run_key === "string" ? data.run_key : "";
                updateStartButton();
                renderStageList(data.progress, data.stage, data.status);
                renderLinks(data.artifacts, data.run_key);
                if (data.status === "failed") {
                  renderFailure(data.stage, data.message, data.artifacts && data.artifacts.diagnostics, data.run_key, data.friendly_error, data.retry_actions);
                  setJobMessage(data.message || "任务失败。", true);
                } else {
                  clearFailure();
                  if (data.status === "running") {
                    setJobMessage(data.message || `运行中: ${data.stage || "preflight"}`);
                  } else if (data.status === "canceling") {
                    setJobMessage(data.message || "正在取消任务。");
                  } else if (data.status === "canceled") {
                    setJobMessage(data.message || "任务已取消。");
                  } else if (data.status === "succeeded") {
                    setJobMessage(data.message || "Report ready.");
                    loadHistory();
                  } else {
                    setJobMessage("等待输入。");
                  }
                }
              } catch (error) {
                if (state.authExpired) return;
                setJobMessage(error.message || "状态读取失败。", true);
              }
            }

            async function acceptConsent() {
              if (state.authExpired) return;
              try {
                await apiFetch("/api/consent", { method: "POST" });
                await loadConfig();
                setJobMessage("已接受本地处理告知。");
              } catch (error) {
                setJobMessage(error.message || "Consent failed.", true);
              }
            }

            async function startJob(event) {
              event.preventDefault();
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              if (!state.consentAccepted) {
                setJobMessage("请先接受本地处理告知。", true);
                return;
              }
              clearFailure();
              const payload = {
                url: elements.urlInput.value.trim(),
                format: elements.formatSelect.value,
                language: elements.languageSelect.value,
                force_whisper: elements.forceWhisper.checked,
                require_pdf: elements.requirePdf.checked,
                allow_long_video: elements.allowLongVideo.checked,
              };
              if (!payload.url) {
                setJobMessage("请输入 B 站 URL。", true);
                elements.urlInput.focus();
                return;
              }
              try {
                state.currentStatus = "running";
                updateStartButton();
                const data = await apiFetch("/api/jobs", {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify(payload),
                });
                setJobMessage(`任务已提交: ${data.job_id || "-"}`);
                await loadCurrentJob();
              } catch (error) {
                const message = error.message || "启动失败。";
                const consentError = message.includes("consent");
                const runningConflict = message.includes("already running");
                if (consentError) {
                  state.consentAccepted = false;
                  state.currentStatus = "idle";
                  await loadConfig();
                } else if (runningConflict) {
                  state.currentStatus = "running";
                  await loadCurrentJob();
                } else {
                  state.currentStatus = "idle";
                  updateStartButton();
                }
                setJobMessage(message, consentError || runningConflict || Boolean(message));
              }
            }

            async function cancelJob() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              try {
                const data = await apiFetch("/api/jobs/current/cancel", { method: "POST" });
                state.currentStatus = typeof data.status === "string" ? data.status : "canceling";
                updateStartButton();
                setJobMessage("正在取消任务。");
                await loadCurrentJob();
              } catch (error) {
                setJobMessage(error.message || "取消失败。", true);
              }
            }

            async function retryAction(stage, runKey) {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              if (!stage) return;
              const targetRunKey = runKey || state.currentRunKey;
              if (!targetRunKey) {
                setJobMessage("没有可重试的 run。", true);
                return;
              }
              const data = await apiFetch(`/api/runs/${targetRunKey}/retry`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  from_stage: stage,
                  format: elements.formatSelect.value,
                  require_pdf: elements.requirePdf.checked,
                }),
              });
              state.currentStatus = typeof data.status === "string" ? data.status : "running";
              updateStartButton();
              clearFailure();
              setJobMessage(`${retryLabel(stage)}已提交。`);
              await loadCurrentJob();
            }

            function init() {
              renderStageList([], "preflight", "idle");
              renderLinks({}, "");
              loadConfig().catch((error) => setJobMessage(error.message || "配置读取失败。", true));
              loadHistory();
              loadCurrentJob();
              elements.consentButton.addEventListener("click", acceptConsent);
              elements.jobForm.addEventListener("submit", startJob);
              elements.cancelButton.addEventListener("click", cancelJob);
              document.addEventListener("click", (event) => {
                const retryTarget = event.target && event.target.closest
                  ? event.target.closest("[data-retry-stage]")
                  : null;
                if (retryTarget) {
                  retryAction(
                    retryTarget.getAttribute("data-retry-stage"),
                    retryTarget.getAttribute("data-retry-run-key"),
                  ).catch((error) => {
                    setJobMessage(error.message || "重试失败。", true);
                  });
                  return;
                }
                const target = event.target && event.target.closest
                  ? event.target.closest("[data-folder-url]")
                  : null;
                if (!target) return;
                openFolder(target.getAttribute("data-folder-url")).catch((error) => {
                  setJobMessage(error.message || "打开文件夹失败。", true);
                });
              });
              state.pollingTimer = setInterval(loadCurrentJob, 1000);
            }

            async function openFolder(url) {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              await apiFetch(url, { method: "POST" });
              setJobMessage("已请求打开本地文件夹。");
            }

            init();
          </script>
        </body>
        </html>
        """
    ).replace("__BILIFAN_EMBEDDED_TOKEN__", embedded_token)
