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
              --bg: #f4f0e8;
              --bg-grid: rgba(34, 44, 52, 0.055);
              --panel: #fffdfa;
              --panel-muted: #f8f6f1;
              --panel-strong: #f1ebe1;
              --border: #d7d0c3;
              --border-strong: #a99d8d;
              --text: #20252a;
              --muted: #66717b;
              --accent: #176b87;
              --accent-strong: #0f4f65;
              --accent-soft: #e4f0f3;
              --paper: #fff8ea;
              --warn: #9a6400;
              --danger: #b0443d;
              --success: #2b7050;
              --shadow: 0 14px 34px rgba(54, 45, 31, 0.08);
              font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", sans-serif;
            }

            * { box-sizing: border-box; }
            body {
              margin: 0;
              background:
                linear-gradient(90deg, var(--bg-grid) 1px, transparent 1px),
                linear-gradient(0deg, var(--bg-grid) 1px, transparent 1px),
                var(--bg);
              background-size: 28px 28px;
              color: var(--text);
            }
            .shell {
              min-height: 100vh;
              padding: 18px;
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
              font-size: 22px;
              font-weight: 800;
            }
            .panel {
              min-width: 0;
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
            .panel-heading-row {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 10px;
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
            textarea,
            button {
              font: inherit;
            }
            input[type="text"],
            input[type="url"],
            select,
            textarea {
              width: 100%;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fffefa;
              color: var(--text);
              padding: 10px 12px;
            }
            textarea {
              min-height: 100px;
              resize: vertical;
            }
            input[type="text"]:focus,
            input[type="url"]:focus,
            select:focus,
            textarea:focus,
            button:focus {
              outline: 2px solid rgba(23, 107, 135, 0.18);
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
            .options-summary {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              align-items: center;
              min-height: 40px;
              padding: 10px 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--accent-soft);
              color: var(--accent-strong);
              font-size: 13px;
              font-weight: 700;
            }
            .advanced-settings {
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              padding: 0;
            }
            .advanced-settings summary {
              cursor: pointer;
              display: flex;
              justify-content: space-between;
              gap: 12px;
              padding: 10px 12px;
              color: var(--text);
              font-weight: 700;
              list-style: none;
            }
            .advanced-settings summary::-webkit-details-marker {
              display: none;
            }
            .advanced-settings summary::after {
              content: "展开";
              color: var(--accent);
              font-size: 12px;
              font-weight: 700;
            }
            .advanced-settings[open] summary::after {
              content: "收起";
            }
            .advanced-settings-body {
              display: grid;
              gap: 12px;
              padding: 0 12px 12px;
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
              background: #fffefa;
              color: var(--text);
              cursor: pointer;
            }
            button.primary {
              border-color: var(--accent);
              background: var(--accent);
              color: #fff;
            }
            button.compact {
              padding: 6px 9px;
              font-size: 12px;
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
              min-width: 0;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              padding: 12px;
            }
            .history-item {
              display: grid;
              gap: 8px;
            }
            .history-item-title,
            .stage-name {
              font-size: 13px;
              font-weight: 700;
              line-height: 1.45;
              overflow-wrap: anywhere;
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
            .history-meta span,
            .stage-meta span {
              overflow-wrap: anywhere;
            }
            .queue-url {
              font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
              font-size: 11px;
            }
            .action-groups {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              align-items: center;
            }
            .primary-actions,
            .secondary-actions {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              align-items: center;
            }
            .action-link,
            .link-button,
            .action-menu summary {
              display: inline-flex;
              align-items: center;
              min-height: 30px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fffefa;
              color: var(--accent);
              padding: 6px 10px;
              font-size: 12px;
              line-height: 1.2;
              text-decoration: none;
            }
            .action-link.primary-action {
              border-color: var(--accent);
              background: var(--accent);
              color: #fff;
              font-weight: 700;
            }
            .action-link.secondary-action {
              border-color: #b7d3dc;
              background: var(--accent-soft);
              color: var(--accent-strong);
            }
            .action-link.warning-action,
            .link-button.warning-action {
              border-color: #dfc286;
              background: var(--paper);
              color: var(--warn);
            }
            .action-link:hover,
            .link-button:hover,
            .action-menu summary:hover {
              border-color: var(--accent);
              color: var(--accent-strong);
            }
            .link-button {
              cursor: pointer;
            }
            .action-menu {
              position: relative;
            }
            .action-menu summary {
              cursor: pointer;
              list-style: none;
            }
            .action-menu summary::-webkit-details-marker {
              display: none;
            }
            .action-menu summary::after {
              content: "⌄";
              margin-left: 6px;
              color: var(--muted);
            }
            .action-menu[open] summary::after {
              content: "⌃";
            }
            .action-menu-items {
              display: flex;
              flex-wrap: wrap;
              gap: 8px;
              margin-top: 8px;
              padding: 8px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fffefa;
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
            .pill.queued { color: var(--warn); border-color: #dfc286; }
            .pill.canceled { color: var(--muted); border-color: var(--border); }
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
              .shell {
                padding: 10px;
              }
              .layout,
              .field-grid,
              .checks {
                grid-template-columns: minmax(0, 1fr);
              }
              .brandbar,
              .panel-heading-row,
              .banner-row,
              .actions {
                align-items: stretch;
                flex-direction: column;
              }
              .action-groups {
                align-items: flex-start;
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
                  <div class="panel-heading-row">
                    <div>
                      <h1>历史记录</h1>
                      <p class="subtle">latest run / artifacts</p>
                    </div>
                    <button id="batch-nabaichuan-button" class="compact" type="button">批量导出 Nabaichuan</button>
                  </div>
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
                      <label for="url-input">
                        视频 URL
                        <input id="url-input" name="url" type="url" required autocomplete="off" spellcheck="false">
                      </label>

                      <div id="current-options-summary" class="options-summary">HTML + PDF · AI 自动判断 · 自动语言</div>

                      <details id="advanced-settings" class="advanced-settings">
                        <summary>高级设置</summary>
                        <div class="advanced-settings-body">
                          <div class="field-grid">
                            <label for="format-select">
                              输出格式
                              <select id="format-select" name="format">
                                <option value="html">HTML</option>
                                <option value="html,pdf">HTML + PDF</option>
                              </select>
                            </label>
                            <label for="summary-template-select">
                              总结模板
                              <select id="summary-template-select" name="summary_template">
                                <option value="AI 自动判断">AI 自动判断</option>
                                <option value="学习笔记">学习笔记</option>
                                <option value="教程步骤">教程步骤</option>
                                <option value="观点提炼">观点提炼</option>
                                <option value="会议纪要">会议纪要</option>
                              </select>
                            </label>
                            <label for="language-select">
                              语言
                              <select id="language-select" name="language">
                                <option value="auto">自动</option>
                                <option value="zh">中文</option>
                                <option value="en">英文</option>
                              </select>
                              <span class="hint">只影响 Whisper；已有字幕默认优先使用。</span>
                            </label>
                          </div>

                          <div class="checks">
                            <label class="check" for="force-whisper">
                              <input id="force-whisper" name="force_whisper" type="checkbox">
                              <span>强制 Whisper</span>
                            </label>
                            <label class="check" for="with-diagrams">
                              <input id="with-diagrams" name="with_diagrams" type="checkbox">
                              <span>实验性图解</span>
                            </label>
                            <label class="check" for="with-frames">
                              <input id="with-frames" name="with_frames" type="checkbox">
                              <span>实验性截图</span>
                            </label>
                            <label class="check" for="require-pdf">
                              <input id="require-pdf" name="require_pdf" type="checkbox">
                              <span>PDF 失败时报错</span>
                            </label>
                            <label class="check" for="allow-long-video">
                              <input id="allow-long-video" name="allow_long_video" type="checkbox">
                              <span>允许长视频</span>
                            </label>
                          </div>
                          <p class="hint">任务中心里的批量任务会使用这里的当前设置；图解和截图目前只作为辅助理解，不作为稳定证据链。</p>
                        </div>
                      </details>

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
                    <h1>任务中心</h1>
                    <p class="subtle">单个任务和批量任务</p>
                  </div>
                  <div class="panel-body stack">
                    <label for="batch-urls">
                      批量 URL
                      <textarea id="batch-urls" rows="4" placeholder="每行一个 B 站或 YouTube URL"></textarea>
                    </label>
                    <div class="actions">
                      <div id="queue-summary" class="status-line">队列空闲。</div>
                      <div style="display:flex; gap:8px; align-items:center;">
                        <button id="queue-pause-button" type="button">暂停队列</button>
                        <button id="queue-resume-button" type="button">恢复队列</button>
                        <button id="queue-clear-completed-button" type="button">清除已完成</button>
                        <button id="batch-submit-button" class="primary" type="button">加入队列</button>
                      </div>
                    </div>
                    <ul id="queue-list" class="history-list"></ul>
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
            const STAGE_LABELS = {
              preflight: "准备检查",
              metadata: "读取视频信息",
              audio: "下载音频",
              transcript: "获取逐字稿",
              chunking: "拆分内容",
              summarization: "生成总结",
              render: "生成文件",
              interrupted: "服务中断",
              canceled: "已取消",
            };
            const STAGE_DESCRIPTIONS = {
              preflight: "检查参数、本地依赖和运行条件",
              metadata: "读取标题、作者、时长、分 P 和字幕信息",
              audio: "下载当前视频音频并校验时长",
              transcript: "优先使用已有字幕，必要时调用 Whisper",
              chunking: "按时长和上下文拆成可总结片段",
              summarization: "调用 Codex 生成学习笔记内容",
              render: "生成 HTML、PDF 和导出文件",
              interrupted: "服务重启或任务中断，需要重新排队",
              canceled: "任务已取消",
            };
            const embeddedToken = __BILIFAN_EMBEDDED_TOKEN__;
            const token = new URLSearchParams(location.search).get("token") || embeddedToken;

            const state = {
              authExpired: false,
              consentAccepted: false,
              currentStatus: "idle",
              currentRunKey: "",
              openMenus: new Set(),
              pollingTimer: null,
            };

            const elements = {
              historyList: document.getElementById("history-list"),
              jobForm: document.getElementById("job-form"),
              urlInput: document.getElementById("url-input"),
              currentOptionsSummary: document.getElementById("current-options-summary"),
              formatSelect: document.getElementById("format-select"),
              summaryTemplateSelect: document.getElementById("summary-template-select"),
              languageSelect: document.getElementById("language-select"),
              forceWhisper: document.getElementById("force-whisper"),
              withDiagrams: document.getElementById("with-diagrams"),
              withFrames: document.getElementById("with-frames"),
              requirePdf: document.getElementById("require-pdf"),
              allowLongVideo: document.getElementById("allow-long-video"),
              startButton: document.getElementById("start-button"),
              cancelButton: document.getElementById("cancel-button"),
              batchNabaichuanButton: document.getElementById("batch-nabaichuan-button"),
              batchUrls: document.getElementById("batch-urls"),
              batchSubmitButton: document.getElementById("batch-submit-button"),
              queuePauseButton: document.getElementById("queue-pause-button"),
              queueResumeButton: document.getElementById("queue-resume-button"),
              queueClearCompletedButton: document.getElementById("queue-clear-completed-button"),
              queueSummary: document.getElementById("queue-summary"),
              queueList: document.getElementById("queue-list"),
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
              elements.batchNabaichuanButton.disabled = state.authExpired || !state.consentAccepted;
              elements.batchSubmitButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queuePauseButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queueResumeButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queueClearCompletedButton.disabled = state.authExpired || !state.consentAccepted;
            }

            function renderStageList(progress, activeStage, jobStatus) {
              const items = Array.isArray(progress) && progress.length ? progress : STAGES.map((stage) => ({ stage, status: "pending" }));
              elements.stageList.innerHTML = items.map((item) => {
                const stage = typeof item.stage === "string" ? item.stage : "";
                const status = typeof item.status === "string" ? item.status : "pending";
                const active = stage === activeStage ? " 当前" : "";
                const statusClass = ["pending", "running", "done", "failed", "succeeded", "queued", "canceled"].includes(status) ? status : "pending";
                const description = stageDescription(stage);
                return `
                  <li class="stage-item">
                    <div class="stage-name">${escapeHtml(stageLabel(stage))}</div>
                    ${description ? `<div class="history-meta"><span>${escapeHtml(description)}</span></div>` : ""}
                    <div class="stage-meta">
                      <span class="pill ${statusClass}">${escapeHtml(statusLabel(status))}${escapeHtml(active)}</span>
                      <span>任务: ${escapeHtml(statusLabel(jobStatus || "idle"))}</span>
                    </div>
                  </li>
                `;
              }).join("");
            }

            function renderLinks(artifacts, runKey, status = "idle") {
              const markup = artifactActionGroups(artifacts, runKey, status, {
                menuScope: `current:${runKey || status || "idle"}`,
              });
              elements.resultLinks.innerHTML = markup
                ? markup
                : '<div class="muted-panel">当前没有可用 artifacts。</div>';
            }

            function artifactActionGroups(artifacts, runKey, status = "idle", options = {}) {
              const safeArtifacts = artifacts && typeof artifacts === "object" ? artifacts : {};
              const primary = [];
              const exports = [];
              const advanced = [];

              if (safeArtifacts.html) primary.push(linkItem("打开笔记", safeArtifacts.html, "primary-action"));
              if (safeArtifacts.pdf) primary.push(linkItem("下载 PDF", safeArtifacts.pdf, "secondary-action"));
              if (safeArtifacts.md) exports.push(linkItem("Markdown", safeArtifacts.md));
              if (safeArtifacts.txt) exports.push(linkItem("逐字稿 TXT", safeArtifacts.txt));
              if (safeArtifacts.srt) exports.push(linkItem("字幕 SRT", safeArtifacts.srt));
              if (safeArtifacts.bundle) advanced.push(linkItem("结构化数据", safeArtifacts.bundle));
              if (safeArtifacts.nabaichuan) advanced.push(linkItem("纳百川文件", safeArtifacts.nabaichuan));
              if (!safeArtifacts.nabaichuan && safeArtifacts.bundle && runKey && status === "succeeded") {
                advanced.push(nabaichuanButton("导出到纳百川", runKey));
              }
              if (runKey && status === "succeeded") {
                advanced.push(resummarizeButton("重新生成总结", runKey));
              }
              if (safeArtifacts.audio) advanced.push(linkItem("音频文件", safeArtifacts.audio));
              if (safeArtifacts.diagnostics) advanced.push(linkItem("诊断信息", safeArtifacts.diagnostics));
              if (safeArtifacts.folder) advanced.push(folderButton("打开本地文件夹", safeArtifacts.folder));
              if (runKey && options.includeFiles !== false) {
                advanced.push(linkItem("文件列表", runFilesUrl(runKey)));
              }

              return actionGroups(primary, exports, advanced, options.menuScope || "");
            }

            function actionGroups(primary, exports, advanced, menuScope = "") {
              const groups = [];
              if (primary.length) {
                groups.push(`<div class="primary-actions">${primary.join("")}</div>`);
              }
              if (exports.length) {
                groups.push(actionMenu("导出", exports, menuScope ? `${menuScope}:export` : ""));
              }
              if (advanced.length) {
                groups.push(actionMenu("更多", advanced, menuScope ? `${menuScope}:more` : ""));
              }
              return groups.length ? `<div class="action-groups">${groups.join("")}</div>` : "";
            }

            function rememberOpenMenu(menuKey, isOpen) {
              if (!menuKey) return;
              if (isOpen) {
                state.openMenus.add(menuKey);
              } else {
                state.openMenus.delete(menuKey);
              }
            }

            function actionMenu(label, items, menuKey = "") {
              const keyAttr = menuKey ? ` data-menu-key="${escapeAttr(menuKey)}"` : "";
              const openAttr = menuKey && state.openMenus.has(menuKey) ? " open" : "";
              return `
                <details class="action-menu"${keyAttr}${openAttr}>
                  <summary>${escapeHtml(label)}</summary>
                  <div class="action-menu-items">${items.join("")}</div>
                </details>
              `;
            }

            function linkItem(label, href, variant = "") {
              const url = withToken(href);
              const classes = ["action-link", variant].filter(Boolean).join(" ");
              return `<a class="${escapeAttr(classes)}" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`;
            }

            function folderButton(label, href, variant = "") {
              const url = withToken(href);
              const classes = ["link-button", variant].filter(Boolean).join(" ");
              return `<button class="${escapeAttr(classes)}" type="button" data-folder-url="${escapeAttr(url)}">${escapeHtml(label)}</button>`;
            }

            function nabaichuanButton(label, runKey, variant = "") {
              const classes = ["link-button", variant].filter(Boolean).join(" ");
              return `<button class="${escapeAttr(classes)}" type="button" data-nabaichuan-run-key="${escapeAttr(runKey)}">${escapeHtml(label)}</button>`;
            }

            function renderFailure(stage, message, diagnostics, runKey, friendlyError, retryActions) {
              const links = [];
              if (diagnostics) {
                links.push(linkItem("诊断信息", diagnostics));
              }
              if (runKey) {
                links.push(linkItem("文件列表", runFilesUrl(runKey)));
              }
              const linkMarkup = links.length ? `<div class="action-groups">${links.join("")}</div>` : "";
              const friendly = friendlyError && typeof friendlyError === "object" ? friendlyError : null;
              const title = friendly && friendly.title ? friendly.title : "任务失败";
              const cause = friendly && friendly.cause ? friendly.cause : (message || "Unknown error.");
              const nextAction = friendly && friendly.next_action ? `<div>${escapeHtml(friendly.next_action)}</div>` : "";
              const retryButtons = Array.isArray(retryActions) && retryActions.length && runKey
                ? `<div class="action-groups">${retryActions.map((retryStage) => `<button class="link-button warning-action" type="button" data-retry-stage="${escapeAttr(retryStage)}" data-retry-run-key="${escapeAttr(runKey)}">${escapeHtml(retryLabel(retryStage))}</button>`).join("")}</div>`
                : "";
              elements.failurePanel.innerHTML = `
                <div class="stack" style="gap:6px;">
                  <h2>${escapeHtml(title)}</h2>
                  <div>阶段: ${escapeHtml(stageLabel(stage || "preflight"))}</div>
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
                const historyKey = item.run_key || item.output_id || item.title || "history";
                const actionMarkup = artifactActionGroups(artifacts, item.run_key, item.status, {
                  menuScope: `history:${historyKey}`,
                });
                const friendly = item.friendly_error && typeof item.friendly_error === "object" ? item.friendly_error : null;
                const retryActions = Array.isArray(item.retry_actions) ? item.retry_actions : [];
                const retryButtons = retryActions.length && item.run_key
                  ? `<div class="action-groups">${retryActions.map((retryStage) => `<button class="link-button warning-action" type="button" data-retry-stage="${escapeAttr(retryStage)}" data-retry-run-key="${escapeAttr(item.run_key)}">${escapeHtml(retryLabel(retryStage))}</button>`).join("")}</div>`
                  : "";
                const failureDetail = friendly
                  ? `<div class="history-meta"><span>${escapeHtml(friendly.title || "任务失败")}</span><span>${escapeHtml(friendly.cause || "")}</span><span>${escapeHtml(friendly.next_action || "")}</span></div>`
                  : "";
                const stageMeta = item.status === "failed"
                  ? `<span>失败阶段: ${escapeHtml(stageLabel(item.stage))}</span>`
                  : (item.status && item.status !== "succeeded" ? `<span>阶段: ${escapeHtml(stageLabel(item.stage))}</span>` : "");
                const transcriptMeta = transcriptSourceMeta(item);
                return `
                  <li class="history-item">
                    <div class="history-item-title">${escapeHtml(item.title || item.output_id || "-")}</div>
                    <div class="history-meta">
                      <span>${escapeHtml(item.output_id || "-")}</span>
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(statusLabel(item.status))}</span>
                      ${stageMeta}
                      ${transcriptMeta}
                    </div>
                    ${failureDetail}
                    ${retryButtons}
                    ${actionMarkup}
                  </li>
                `;
              }).join("");
            }

            function renderQueue(queue) {
              const totalCounts = queue && queue.queue_counts ? queue.queue_counts : (queue && queue.counts ? queue.counts : {});
              const counts = queue && queue.visible_counts ? queue.visible_counts : totalCounts;
              const hiddenCompleted = Number.isFinite(Number(queue && queue.hidden_completed)) ? Number(queue.hidden_completed) : 0;
              const hiddenReplaced = Number.isFinite(Number(queue && queue.hidden_replaced)) ? Number(queue.hidden_replaced) : 0;
              const summaryParts = [
                `排队 ${counts.queued || 0}`,
                `运行 ${counts.running || 0}`,
                `已生成 ${counts.succeeded || 0}`,
                `失败 ${counts.failed || 0}`,
                `已取消 ${counts.canceled || 0}`,
              ];
              if (hiddenCompleted > 0) {
                summaryParts.push(`隐藏 ${hiddenCompleted} 条已完成`);
              }
              if (hiddenReplaced > 0) {
                summaryParts.push(`隐藏 ${hiddenReplaced} 条已重试失败记录`);
              }
              elements.queueSummary.textContent = summaryParts.join(" · ");
              elements.queueClearCompletedButton.disabled = state.authExpired || !state.consentAccepted || !(totalCounts.succeeded || 0);
              const items = queue && Array.isArray(queue.items) ? queue.items : [];
              if (!items.length) {
                elements.queueList.innerHTML = '<li class="muted-panel">暂无队列任务。</li>';
                return;
              }
              elements.queueList.innerHTML = items.map((item) => {
                const artifacts = item && typeof item.artifacts === "object" ? item.artifacts : {};
                const queueKey = item.job_id || item.run_key || "queue";
                const actionMarkup = artifactActionGroups(artifacts, item.run_key, item.status, {
                  menuScope: `queue:${queueKey}`,
                });
                const queueControls = [];
                const isQueueItem = item.source !== "current";
                if (isQueueItem && item.status === "queued") queueControls.push(`<button class="link-button warning-action" type="button" data-queue-cancel="${escapeAttr(item.job_id || "")}">取消排队</button>`);
                if (isQueueItem && ["failed", "canceled"].includes(item.status)) queueControls.push(`<button class="link-button warning-action" type="button" data-queue-retry="${escapeAttr(item.job_id || "")}">重新排队</button>`);
                const request = item.request && typeof item.request === "object" ? item.request : {};
                const requestUrl = typeof request.url === "string" ? request.url : "";
                const displayTitle = queueDisplayTitle(item, requestUrl);
                const compactUrl = compactSourceUrl(requestUrl);
                const sourceLabel = item.source === "current" ? "当前任务" : "队列任务";
                const transcriptMeta = transcriptSourceMeta(item);
                return `
                  <li class="history-item">
                    <div class="history-item-title">${escapeHtml(displayTitle)}</div>
                    <div class="history-meta">
                      <span>${escapeHtml(sourceLabel)}</span>
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(statusLabel(item.status))}</span>
                      <span>阶段: ${escapeHtml(stageLabel(item.stage))}</span>
                      ${transcriptMeta}
                      ${compactUrl ? `<span class="queue-url">${escapeHtml(compactUrl)}</span>` : ""}
                    </div>
                    <div class="history-meta"><span>${escapeHtml(item.message || "")}</span></div>
                    ${queueControls.length ? `<div class="action-groups">${queueControls.join("")}</div>` : ""}
                    ${actionMarkup}
                  </li>
                `;
              }).join("");
            }

            function stageLabel(stage) {
              return STAGE_LABELS[stage] || stage || "-";
            }

            function transcriptSourceMeta(item) {
              const label = item && typeof item.transcript_source_label === "string"
                ? item.transcript_source_label.trim()
                : "";
              return label ? `<span>逐字稿：${escapeHtml(label)}</span>` : "";
            }

            function stageDescription(stage) {
              return STAGE_DESCRIPTIONS[stage] || "";
            }

            function statusLabel(status) {
              const labels = {
                queued: "排队中",
                running: "运行中",
                succeeded: "已生成",
                failed: "失败",
                canceled: "已取消",
                canceling: "取消中",
                idle: "空闲",
                pending: "待处理",
                done: "完成",
              };
              return labels[status] || status || "-";
            }

            function queueDisplayTitle(item, requestUrl) {
              if (item && typeof item.title === "string" && item.title.trim()) {
                return item.title.trim();
              }
              if (item && ["queued", "running"].includes(item.status)) {
                return "待读取标题";
              }
              return compactSourceUrl(requestUrl) || (item && item.job_id) || "-";
            }

            function compactSourceUrl(url) {
              if (!url) return "";
              try {
                const parsed = new URL(url);
                const pathParts = parsed.pathname.split("/").filter(Boolean);
                const lastPath = pathParts[pathParts.length - 1] || parsed.hostname;
                if (parsed.hostname.includes("bilibili.com")) {
                  const page = parsed.searchParams.get("p");
                  return page ? `${lastPath}?p=${page}` : lastPath;
                }
                if (parsed.hostname.includes("youtube.com")) {
                  const videoId = parsed.searchParams.get("v");
                  return videoId ? `YouTube ${videoId}` : `YouTube ${lastPath}`;
                }
                if (parsed.hostname.includes("youtu.be")) {
                  return `YouTube ${lastPath}`;
                }
                return `${parsed.hostname}${parsed.pathname}`;
              } catch (error) {
                return url;
              }
            }

            function updateOptionsSummary() {
              const parts = [
                formatLabel(elements.formatSelect.value),
                elements.summaryTemplateSelect.value || "AI 自动判断",
                languageLabel(elements.languageSelect.value),
              ];
              if (elements.forceWhisper.checked) parts.push("强制 Whisper");
              if (elements.withDiagrams.checked) parts.push("实验性图解");
              if (elements.withFrames.checked) parts.push("实验性截图");
              if (elements.requirePdf.checked) parts.push("必须 PDF");
              if (elements.allowLongVideo.checked) parts.push("长视频");
              elements.currentOptionsSummary.textContent = parts.join(" · ");
            }

            function formatLabel(value) {
              if (value === "html") return "HTML";
              if (value === "html,pdf") return "HTML + PDF";
              return value || "HTML + PDF";
            }

            function languageLabel(value) {
              const labels = {
                auto: "自动语言",
                zh: "中文",
                en: "英文",
              };
              return labels[value] || value || "自动语言";
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
              if (stage === "bundle") return "重试结构化导出";
              return `重试 ${stage}`;
            }

            function resummarizeButton(label, runKey, variant = "") {
              const classes = ["link-button", variant].filter(Boolean).join(" ");
              return `<button class="${escapeAttr(classes)}" type="button" data-resummarize-run-key="${escapeAttr(runKey)}">${escapeHtml(label)}</button>`;
            }

            async function loadConfig() {
              const data = await apiFetch("/api/config");
              const defaults = data.defaults || {};
              const consent = data.consent || {};
              state.consentAccepted = Boolean(consent.local_processing);
              elements.formatSelect.value = defaults.format || "html,pdf";
              elements.summaryTemplateSelect.value = defaults.summary_template || "AI 自动判断";
              elements.languageSelect.value = defaults.language || "auto";
              elements.forceWhisper.checked = Boolean(defaults.force_whisper);
              elements.withDiagrams.checked = Boolean(defaults.with_diagrams);
              elements.withFrames.checked = Boolean(defaults.with_frames);
              elements.requirePdf.checked = Boolean(defaults.require_pdf);
              elements.allowLongVideo.checked = Boolean(defaults.allow_long_video);
              updateOptionsSummary();
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

            async function loadQueue() {
              if (state.authExpired) return;
              try {
                const data = await apiFetch("/api/jobs/queue");
                renderQueue(data);
              } catch (error) {
                if (state.authExpired) return;
                elements.queueList.innerHTML = `<li class="muted-panel">${escapeHtml(error.message || "Queue load failed.")}</li>`;
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
                renderLinks(data.artifacts, data.run_key, data.status);
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
                    loadQueue();
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
                summary_template: elements.summaryTemplateSelect.value,
                language: elements.languageSelect.value,
                force_whisper: elements.forceWhisper.checked,
                with_diagrams: elements.withDiagrams.checked,
                with_frames: elements.withFrames.checked,
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

            function currentOptionsPayload() {
              return {
                format: elements.formatSelect.value,
                summary_template: elements.summaryTemplateSelect.value,
                language: elements.languageSelect.value,
                force_whisper: elements.forceWhisper.checked,
                with_diagrams: elements.withDiagrams.checked,
                with_frames: elements.withFrames.checked,
                require_pdf: elements.requirePdf.checked,
                allow_long_video: elements.allowLongVideo.checked,
              };
            }

            async function submitBatch() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              const urls = elements.batchUrls.value.split(/\\r?\\n/).map((line) => line.trim()).filter(Boolean);
              if (!urls.length) {
                setJobMessage("请输入至少一个批量 URL。", true);
                elements.batchUrls.focus();
                return;
              }
              const payload = { urls, ...currentOptionsPayload() };
              const data = await apiFetch("/api/jobs/batch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
              });
              renderQueue(data);
              setJobMessage(`已加入队列: ${urls.length} 个 URL。`);
            }

            async function queueAction(path) {
              const data = await apiFetch(path, { method: "POST" });
              renderQueue(data);
            }

            async function clearCompletedQueue() {
              const data = await apiFetch("/api/jobs/queue/clear-completed", { method: "POST" });
              renderQueue(data);
              setJobMessage("已清除已完成的队列任务。");
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
                  summary_template: elements.summaryTemplateSelect.value,
                  with_diagrams: elements.withDiagrams.checked,
                  with_frames: elements.withFrames.checked,
                  require_pdf: elements.requirePdf.checked,
                }),
              });
              state.currentStatus = typeof data.status === "string" ? data.status : "running";
              updateStartButton();
              clearFailure();
              setJobMessage(`${retryLabel(stage)}已提交。`);
              await loadCurrentJob();
            }

            async function exportNabaichuan(runKey) {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              if (!runKey) {
                setJobMessage("没有可导出的 run。", true);
                return;
              }
              const data = await apiFetch(`/api/runs/${runKey}/exports/nabaichuan`, { method: "POST" });
              await loadHistory();
              await loadCurrentJob();
              const artifact = data && typeof data.artifact === "string" ? withToken(data.artifact) : "";
              setJobMessage(artifact ? `Nabaichuan JSONL 已生成: ${artifact}` : "Nabaichuan JSONL 已生成。");
            }

            async function exportNabaichuanBatch() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              const data = await apiFetch("/api/exports/nabaichuan/batch", { method: "POST" });
              const count = Number.isFinite(Number(data.exported_runs)) ? Number(data.exported_runs) : 0;
              const skipped = Number.isFinite(Number(data.skipped_runs)) ? Number(data.skipped_runs) : 0;
              const records = Number.isFinite(Number(data.records_written)) ? Number(data.records_written) : 0;
              const artifact = data && typeof data.artifact === "string" ? withToken(data.artifact) : "";
              const report = data && typeof data.report === "string" ? withToken(data.report) : "";
              setJobMessage(
                artifact
                  ? `已批量导出 ${count} 个 run、${records} 条记录，跳过 ${skipped} 个: ${artifact}${report ? `；报告: ${report}` : ""}`
                  : `已批量导出 ${count} 个 run、${records} 条记录，跳过 ${skipped} 个。`
              );
            }

            function init() {
              renderStageList([], "preflight", "idle");
              renderLinks({}, "");
              loadConfig().catch((error) => setJobMessage(error.message || "配置读取失败。", true));
              loadHistory();
              loadCurrentJob();
              loadQueue();
              elements.consentButton.addEventListener("click", acceptConsent);
              elements.jobForm.addEventListener("submit", startJob);
              elements.cancelButton.addEventListener("click", cancelJob);
              [
                elements.formatSelect,
                elements.summaryTemplateSelect,
                elements.languageSelect,
                elements.forceWhisper,
                elements.withDiagrams,
                elements.withFrames,
                elements.requirePdf,
                elements.allowLongVideo,
              ].forEach((element) => element.addEventListener("change", updateOptionsSummary));
              elements.batchNabaichuanButton.addEventListener("click", () => {
                exportNabaichuanBatch().catch((error) => {
                  setJobMessage(error.message || "批量导出失败。", true);
                });
              });
              elements.batchSubmitButton.addEventListener("click", () => {
                submitBatch().catch((error) => {
                  setJobMessage(error.message || "批量加入队列失败。", true);
                });
              });
              elements.queuePauseButton.addEventListener("click", () => {
                queueAction("/api/jobs/queue/pause").catch((error) => {
                  setJobMessage(error.message || "暂停队列失败。", true);
                });
              });
              elements.queueResumeButton.addEventListener("click", () => {
                queueAction("/api/jobs/queue/resume").catch((error) => {
                  setJobMessage(error.message || "恢复队列失败。", true);
                });
              });
              elements.queueClearCompletedButton.addEventListener("click", () => {
                clearCompletedQueue().catch((error) => {
                  setJobMessage(error.message || "清除已完成失败。", true);
                });
              });
              document.addEventListener("toggle", (event) => {
                const target = event.target;
                if (!target || !target.getAttribute || !target.classList || !target.classList.contains("action-menu")) return;
                rememberOpenMenu(target.getAttribute("data-menu-key"), Boolean(target.open));
              }, true);
              document.addEventListener("click", (event) => {
                const queueCancelTarget = event.target && event.target.closest
                  ? event.target.closest("[data-queue-cancel]")
                  : null;
                if (queueCancelTarget) {
                  queueAction(`/api/jobs/queue/${queueCancelTarget.getAttribute("data-queue-cancel")}/cancel`).catch((error) => {
                    setJobMessage(error.message || "取消排队失败。", true);
                  });
                  return;
                }
                const queueRetryTarget = event.target && event.target.closest
                  ? event.target.closest("[data-queue-retry]")
                  : null;
                if (queueRetryTarget) {
                  queueAction(`/api/jobs/queue/${queueRetryTarget.getAttribute("data-queue-retry")}/retry`).catch((error) => {
                    setJobMessage(error.message || "重新排队失败。", true);
                  });
                  return;
                }
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
                const nabaichuanTarget = event.target && event.target.closest
                  ? event.target.closest("[data-nabaichuan-run-key]")
                  : null;
                if (nabaichuanTarget) {
                  exportNabaichuan(nabaichuanTarget.getAttribute("data-nabaichuan-run-key")).catch((error) => {
                    setJobMessage(error.message || "Nabaichuan 导出失败。", true);
                  });
                  return;
                }
                const resummarizeTarget = event.target && event.target.closest
                  ? event.target.closest("[data-resummarize-run-key]")
                  : null;
                if (resummarizeTarget) {
                  retryAction(
                    "summarization",
                    resummarizeTarget.getAttribute("data-resummarize-run-key"),
                  ).catch((error) => {
                    setJobMessage(error.message || "重总结失败。", true);
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
              state.pollingTimer = setInterval(() => {
                loadCurrentJob();
                loadQueue();
              }, 1000);
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
