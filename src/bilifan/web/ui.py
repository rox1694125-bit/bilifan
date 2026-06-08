from textwrap import dedent


def render_app_html() -> str:
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
            select,
            button {
              font: inherit;
            }
            input[type="text"],
            select {
              width: 100%;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fff;
              color: var(--text);
              padding: 10px 12px;
            }
            input[type="text"]:focus,
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
            .link-list a {
              color: var(--accent);
              text-decoration: none;
            }
            .history-links a:hover,
            .link-list a:hover {
              text-decoration: underline;
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
                        <button id="start-button" class="primary" type="submit">开始</button>
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
            const token = new URLSearchParams(location.search).get("token") || "";

            const state = {
              consentAccepted: false,
              currentStatus: "idle",
              pollingTimer: null,
            };

            const elements = {
              historyList: document.getElementById("history-list"),
              jobForm: document.getElementById("job-form"),
              urlInput: document.getElementById("url-input"),
              formatSelect: document.getElementById("format-select"),
              forceWhisper: document.getElementById("force-whisper"),
              requirePdf: document.getElementById("require-pdf"),
              allowLongVideo: document.getElementById("allow-long-video"),
              startButton: document.getElementById("start-button"),
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

            function setJobMessage(message, isError = false) {
              elements.jobMessage.textContent = message;
              elements.jobMessage.className = isError ? "status-line error" : "status-line";
            }

            function updateStartButton() {
              elements.startButton.disabled = !state.consentAccepted || state.currentStatus === "running";
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
                if (artifacts.diagnostics) links.push(linkItem("diagnostics", artifacts.diagnostics));
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

            function renderFailure(stage, message, diagnostics, runKey) {
              const links = [];
              if (diagnostics) {
                links.push(`<a href="${escapeAttr(withToken(diagnostics))}" target="_blank" rel="noopener noreferrer">diagnostics</a>`);
              }
              if (runKey) {
                links.push(`<a href="${escapeAttr(runFilesUrl(runKey))}" target="_blank" rel="noopener noreferrer">file list</a>`);
              }
              const linkMarkup = links.length ? `<div class="history-links">${links.join("")}</div>` : "";
              elements.failurePanel.innerHTML = `
                <div class="stack" style="gap:6px;">
                  <h2>任务失败</h2>
                  <div>stage: ${escapeHtml(stage || "preflight")}</div>
                  <div>${escapeHtml(message || "Unknown error.")}</div>
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
                if (artifacts.diagnostics) links.push(linkItem("diagnostics", artifacts.diagnostics));
                if (item.run_key) links.push(linkItem("file list", `/api/runs/${item.run_key}/files`));
                return `
                  <li class="history-item">
                    <div class="history-item-title">${escapeHtml(item.title || item.output_id || "-")}</div>
                    <div class="history-meta">
                      <span>${escapeHtml(item.output_id || "-")}</span>
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(item.status || "-")}</span>
                      <span>stage: ${escapeHtml(item.stage || "-")}</span>
                    </div>
                    <div class="history-links">${links.join("")}</div>
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

            async function loadConfig() {
              const data = await apiFetch("/api/config");
              const defaults = data.defaults || {};
              const consent = data.consent || {};
              state.consentAccepted = Boolean(consent.local_processing);
              elements.formatSelect.value = defaults.format || "html,pdf";
              elements.forceWhisper.checked = Boolean(defaults.force_whisper);
              elements.requirePdf.checked = Boolean(defaults.require_pdf);
              elements.allowLongVideo.checked = Boolean(defaults.allow_long_video);
              elements.consentBanner.classList.toggle("active", !state.consentAccepted);
              updateStartButton();
            }

            async function loadHistory() {
              try {
                const data = await apiFetch("/api/history");
                renderHistory(data.items || []);
              } catch (error) {
                elements.historyList.innerHTML = `<li class="muted-panel">${escapeHtml(error.message || "History load failed.")}</li>`;
              }
            }

            async function loadCurrentJob() {
              try {
                const data = await apiFetch("/api/jobs/current");
                state.currentStatus = typeof data.status === "string" ? data.status : "idle";
                updateStartButton();
                renderStageList(data.progress, data.stage, data.status);
                renderLinks(data.artifacts, data.run_key);
                if (data.status === "failed") {
                  renderFailure(data.stage, data.message, data.artifacts && data.artifacts.diagnostics, data.run_key);
                  setJobMessage(data.message || "任务失败。", true);
                } else {
                  clearFailure();
                  if (data.status === "running") {
                    setJobMessage(data.message || `运行中: ${data.stage || "preflight"}`);
                  } else if (data.status === "succeeded") {
                    setJobMessage(data.message || "Report ready.");
                    loadHistory();
                  } else {
                    setJobMessage("等待输入。");
                  }
                }
              } catch (error) {
                setJobMessage(error.message || "状态读取失败。", true);
              }
            }

            async function acceptConsent() {
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
              if (!state.consentAccepted) {
                setJobMessage("请先接受本地处理告知。", true);
                return;
              }
              clearFailure();
              const payload = {
                url: elements.urlInput.value.trim(),
                format: elements.formatSelect.value,
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

            function init() {
              renderStageList([], "preflight", "idle");
              renderLinks({}, "");
              loadConfig().catch((error) => setJobMessage(error.message || "配置读取失败。", true));
              loadHistory();
              loadCurrentJob();
              elements.consentButton.addEventListener("click", acceptConsent);
              elements.jobForm.addEventListener("submit", startJob);
              state.pollingTimer = setInterval(loadCurrentJob, 1000);
            }

            init();
          </script>
        </body>
        </html>
        """
    )
