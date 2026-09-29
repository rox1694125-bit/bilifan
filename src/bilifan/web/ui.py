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
          <title>Bilifan 视频笔记</title>
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
            input[type="search"],
            select,
            textarea,
            button {
              font: inherit;
            }
            input[type="text"],
            input[type="url"],
            input[type="search"],
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
            input[type="search"]:focus,
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
            button.secondary {
              border-color: var(--border);
              background: var(--panel-muted);
              color: var(--muted);
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
            .queue-summary {
              color: var(--text);
              font-weight: 700;
            }
            .collection-preview {
              display: grid;
              gap: 10px;
              padding: 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
            }
            .collection-preview[hidden] {
              display: none;
            }
            .segmented {
              display: flex;
              gap: 6px;
              align-items: center;
            }
            .segmented button.active {
              border-color: var(--accent);
              background: var(--accent-soft);
              color: var(--accent-strong);
              font-weight: 700;
            }
            .part-list {
              display: grid;
              gap: 6px;
              max-height: 220px;
              overflow: auto;
              padding-right: 2px;
            }
            .part-row {
              display: grid;
              grid-template-columns: auto minmax(0, 1fr) auto;
              gap: 8px;
              align-items: center;
              min-height: 34px;
              padding: 7px 8px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: #fffefa;
              font-size: 12px;
              color: var(--text);
            }
            .part-row input {
              margin: 0;
            }
            .part-title {
              overflow-wrap: anywhere;
            }
            .task-liveness {
              display: grid;
              gap: 6px;
              padding: 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--panel-muted);
              color: var(--text);
              font-size: 12px;
            }
            .task-liveness.warning {
              border-color: #dfc286;
              background: var(--paper);
              color: var(--warn);
            }
            .service-status {
              display: grid;
              gap: 6px;
              padding: 12px;
              border: 1px solid var(--border);
              border-radius: 6px;
              background: var(--accent-soft);
              color: var(--accent-strong);
              font-size: 12px;
            }
            .service-status.warning {
              border-color: #dfc286;
              background: var(--paper);
              color: var(--warn);
            }
            .service-status.error {
              border-color: #e4b0b0;
              background: #fff3f3;
              color: var(--danger);
            }
            .service-status-title {
              font-size: 13px;
              font-weight: 800;
            }
            .service-status-meta {
              display: flex;
              flex-wrap: wrap;
              gap: 8px 12px;
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
            .history-tools {
              display: grid;
              gap: 8px;
              margin-bottom: 12px;
            }
            .history-toolbar {
              display: flex;
              align-items: center;
              justify-content: space-between;
              gap: 8px;
            }
            .history-toolbar .subtle {
              min-width: 0;
              overflow-wrap: anywhere;
            }
            .history-search-label {
              display: grid;
              gap: 6px;
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
            .action-link.secondary-action,
            .link-button.secondary-action {
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

            .export-feedback-content { display: grid; gap: 10px; overflow-wrap: anywhere; }
            .export-feedback-content h3 { font-size: 16px; }
            .export-feedback-reasons { margin: 0; padding-left: 22px; max-height: 240px; overflow: auto; }
            .export-feedback-reasons li + li { margin-top: 6px; }
            .export-feedback-content .primary-actions { margin-top: 2px; }

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
              <h1>Bilifan 视频笔记</h1>
              <p class="subtle">本地处理，远程访问</p>
            </header>
            <div class="layout">
              <aside class="panel">
                <div class="panel-header">
                  <div class="panel-heading-row">
                    <div>
                      <h1>历史记录</h1>
                      <p class="subtle">最近生成</p>
                    </div>
                    <button id="batch-nabaichuan-button" class="compact secondary" type="button">批量导出纳百川</button>
                  </div>
                </div>
                <div class="panel-body">
                  <div class="history-tools">
                    <label class="history-search-label">
                      <span>搜索历史</span>
                      <input id="history-search" type="search" placeholder="标题、逐字稿来源">
                    </label>
                    <div class="history-toolbar">
                      <span id="history-summary" class="subtle">正在读取历史...</span>
                      <button id="history-toggle-button" class="compact secondary" type="button" hidden>展开更多</button>
                    </div>
                  </div>
                  <details id="legacy-reports-panel"><summary>历史主报告</summary><ul id="legacy-report-list" class="history-list"></ul></details>
                    <ul id="history-list" class="history-list"></ul>
                </div>
              </aside>

              <section class="stack">
                <section id="export-feedback-panel" class="panel" hidden tabindex="-1" aria-labelledby="export-feedback-heading">
                  <div class="panel-header panel-heading-row">
                    <h2 id="export-feedback-heading">导出结果</h2>
                    <button id="export-feedback-close" class="compact secondary" type="button">收起</button>
                  </div>
                  <div class="panel-body stack">
                    <div id="export-feedback" class="export-feedback-content" role="status" aria-live="polite" aria-atomic="true"></div>
                    <p id="export-review-notice" class="subtle" hidden>主动纳入会保留质量警告，不代表已完成人工核实。</p>
                    <div class="primary-actions">
                      <button id="export-include-button" class="primary" type="button" hidden>仍然导出并保留警告</button>
                    </div>
                  </div>
                </section>
                <section class="panel">
                  <div class="panel-header">
                    <h1>当前任务</h1>
                    <p class="subtle">单个视频</p>
                  </div>
                  <div class="panel-body stack">
                    <div id="service-status" class="service-status">
                      <div class="service-status-title">正在检查访问状态...</div>
                    </div>

                    <div id="consent-banner" class="banner" role="status" aria-live="polite">
                      <div class="banner-row">
                        <div class="stack" style="gap:4px;">
                          <h2>需要先确认本地处理告知</h2>
                          <p class="subtle">Bilifan 会在这台电脑本地处理任务，必要时下载当前 P 音频，并把输出文件保存到 ./outputs。默认会调用你配置的 Codex CLI 整理逐字稿，逐字稿文本可能发送到该 Codex 账号背后的模型服务。</p>
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

                      <div id="current-options-summary" class="options-summary">原始稿 + 整理逐字稿 · HTML + PDF · 自动语言</div>

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
                              <span>强制重新转写</span>
                            </label>
                            <label class="check" for="require-pdf">
                              <input id="require-pdf" name="require_pdf" type="checkbox">
                              <span>必须生成 PDF</span>
                            </label>
                            <label class="check" for="allow-long-video">
                              <input id="allow-long-video" name="allow_long_video" type="checkbox" checked>
                              <span>允许长视频</span>
                            </label>
                          </div>
                          <p class="hint">单条、批量与飞书均保存原稿并生成整理稿，不再生成解读式主报告。</p>
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
                    <p class="subtle">批量处理</p>
                  </div>
                  <div class="panel-body stack">
                    <div class="stack">
                      <label for="collection-url">
                        B 站合集 URL
                        <input id="collection-url" name="collection_url" type="url" autocomplete="off" spellcheck="false" placeholder="粘贴任意一个分 P 视频 URL">
                      </label>
                      <div class="actions">
                        <div class="segmented">
                          <button id="collection-mode-all" class="compact secondary active" type="button">整个合集</button>
                          <button id="collection-mode-current" class="compact secondary" type="button">仅当前 URL</button>
                        </div>
                        <div style="display:flex; gap:8px; align-items:center;">
                          <button id="collection-preview-button" class="compact secondary" type="button">预览合集</button>
                          <button id="collection-submit-button" class="compact primary" type="button">加入选中</button>
                        </div>
                      </div>
                      <div id="collection-preview-panel" class="collection-preview" hidden>
                        <div class="subtle">输入合集 URL 后先预览。</div>
                      </div>
                    </div>

                    <label for="batch-urls">
                      批量 URL
                      <textarea id="batch-urls" name="batch_urls" rows="4" autocomplete="off" spellcheck="false" placeholder="每行一个 B 站或 YouTube URL…"></textarea>
                    </label>
                    <div class="actions">
                      <div id="queue-summary" class="status-line queue-summary">队列空闲。</div>
                      <div style="display:flex; gap:8px; align-items:center;">
                        <button id="queue-pause-button" class="compact secondary" type="button">暂停队列</button>
                        <button id="queue-resume-button" class="compact secondary" type="button">恢复队列</button>
                        <button id="queue-clear-completed-button" class="compact secondary" type="button">清除已结束</button>
                        <button id="batch-submit-button" class="primary" type="button">加入队列</button>
                      </div>
                    </div>
                    <ul id="queue-list" class="history-list"></ul>
                  </div>
                </section>

                <section class="panel">
                  <div class="panel-header">
                    <h1>进度</h1>
                  </div>
                  <div class="panel-body stack">
                    <div id="task-liveness" class="task-liveness">
                      <div>提交视频后，会在这里显示处理进度。</div>
                    </div>
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
            const HISTORY_COLLAPSED_LIMIT = 6;
            const STAGE_LABELS = {
              preflight: "准备检查",
              metadata: "读取视频信息",
              audio: "下载音频",
              media: "下载音频",
              transcript: "获取逐字稿",
              chunking: "拆分内容",
              summarization: "整理逐字稿",
              render: "生成文件",
              interrupted: "服务中断",
              canceled: "已取消",
            };
            const STAGE_DESCRIPTIONS = {
              preflight: "检查参数、本地依赖和运行条件",
              metadata: "读取标题、作者、时长、分 P 和字幕信息",
              audio: "下载当前视频音频并校验时长",
              media: "下载当前视频音频并校验时长",
              transcript: "优先使用已有字幕，必要时调用 Whisper",
              chunking: "按时长和上下文拆分逐字稿，便于分块整理",
              summarization: "调用 Codex 纠错、断句和分段，保留原意",
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
              historyItems: [],
              historyExpanded: false,
              historyQuery: "",
              collectionPreview: null,
              collectionMode: "all",
              openMenus: new Set(),
              historyCompletionKeys: new Set(),
              pollingTimer: null,
              exportBusy: false,
              exportAction: null,
            };

            const elements = {
              historyList: document.getElementById("history-list"),
              historySearch: document.getElementById("history-search"),
              historySummary: document.getElementById("history-summary"),
              historyToggleButton: document.getElementById("history-toggle-button"),
              jobForm: document.getElementById("job-form"),
              urlInput: document.getElementById("url-input"),
              currentOptionsSummary: document.getElementById("current-options-summary"),
              formatSelect: document.getElementById("format-select"),
              languageSelect: document.getElementById("language-select"),
              forceWhisper: document.getElementById("force-whisper"),
              requirePdf: document.getElementById("require-pdf"),
              allowLongVideo: document.getElementById("allow-long-video"),
              startButton: document.getElementById("start-button"),
              cancelButton: document.getElementById("cancel-button"),
              batchNabaichuanButton: document.getElementById("batch-nabaichuan-button"),
              collectionUrl: document.getElementById("collection-url"),
              collectionPreviewButton: document.getElementById("collection-preview-button"),
              collectionModeCurrent: document.getElementById("collection-mode-current"),
              collectionModeAll: document.getElementById("collection-mode-all"),
              collectionSubmitButton: document.getElementById("collection-submit-button"),
              collectionPreviewPanel: document.getElementById("collection-preview-panel"),
              batchUrls: document.getElementById("batch-urls"),
              batchSubmitButton: document.getElementById("batch-submit-button"),
              queuePauseButton: document.getElementById("queue-pause-button"),
              queueResumeButton: document.getElementById("queue-resume-button"),
              queueClearCompletedButton: document.getElementById("queue-clear-completed-button"),
              queueSummary: document.getElementById("queue-summary"),
              queueList: document.getElementById("queue-list"),
              serviceStatus: document.getElementById("service-status"),
              jobMessage: document.getElementById("job-message"),
              consentBanner: document.getElementById("consent-banner"),
              consentButton: document.getElementById("consent-button"),
              stageList: document.getElementById("stage-list"),
              taskLiveness: document.getElementById("task-liveness"),
              resultLinks: document.getElementById("result-links"),
              failurePanel: document.getElementById("failure-panel"),
              exportFeedbackPanel: document.getElementById("export-feedback-panel"),
              exportFeedback: document.getElementById("export-feedback"),
              exportFeedbackClose: document.getElementById("export-feedback-close"),
              exportReviewNotice: document.getElementById("export-review-notice"),
              exportIncludeButton: document.getElementById("export-include-button"),
            };

            state.followedJobId = typeof sessionStorage !== "undefined" ? sessionStorage.getItem("bilifan-followed-job") : null;
            function followJob(jobId) {
              state.followedJobId = jobId || null;
              if (typeof sessionStorage !== "undefined") {
                if (jobId) sessionStorage.setItem("bilifan-followed-job", jobId);
                else sessionStorage.removeItem("bilifan-followed-job");
              }
            }

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
                let responsePayload = {};
                try {
                  const payload = await response.json();
                  responsePayload = payload || {};
                  if (payload && typeof payload.detail === "string") {
                    detail = payload.detail;
                  }
                } catch (error) {
                  // ignore json parse failure
                }
                const requestError = new Error(detail);
                requestError.payload = responsePayload;
                throw requestError;
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
              const message = "当前页面访问已过期：服务可能已重启，旧页面仍在刷新。请重新打开远程入口或刷新当前页面。";
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

            function renderServiceStatus(data) {
              const entrypoint = data && typeof data.entrypoint === "object" ? data.entrypoint : {};
              const currentJob = data && typeof data.current_job === "object" ? data.current_job : {};
              const isRemote = entrypoint.mode === "remote";
              const jobStatus = statusLabel(currentJob.status || "idle");
              const stage = stageLabel(currentJob.stage || "preflight");
              const activeJob = ["running", "failed", "canceling"].includes(currentJob.status);
              const hasCurrentJob = currentJob.status && currentJob.status !== "idle";
              const publicUrl = isRemote && typeof entrypoint.public_url === "string" ? entrypoint.public_url : "";
              const remoteMeta = publicUrl
                ? `<span>远程入口：<a href="${escapeAttr(publicUrl)}" target="_blank" rel="noopener noreferrer">${escapeHtml(publicUrl)}</a></span><span>隧道状态由本机脚本检查</span>`
                : "";
              const activity = hasCurrentJob
                ? `当前任务：${activeJob ? `${jobStatus} · ${stage}` : jobStatus}`
                : "当前没有运行中的任务";
              elements.serviceStatus.className = "service-status";
              elements.serviceStatus.innerHTML = `
                <div class="service-status-title">${escapeHtml(isRemote ? "远程访问正常" : "本机访问正常")}</div>
                <div class="service-status-meta">
                  <span>${escapeHtml(activity)}</span>
                  ${remoteMeta}
                </div>
              `;
            }

            function renderServiceStatusWarning(message) {
              elements.serviceStatus.className = state.authExpired ? "service-status error" : "service-status warning";
              elements.serviceStatus.innerHTML = `
                <div class="service-status-title">访问状态需要刷新</div>
                <div class="service-status-meta">
                  <span>${escapeHtml(message)}</span>
                  <span>如果服务刚重启，请重新打开最新地址。</span>
                </div>
              `;
            }

            function updateStartButton() {
              elements.startButton.disabled = state.authExpired || !state.consentAccepted;
              elements.cancelButton.disabled = state.authExpired || !["running", "queued"].includes(state.currentStatus);
              elements.batchNabaichuanButton.disabled = state.authExpired || !state.consentAccepted || state.exportBusy;
              elements.exportIncludeButton.disabled = state.authExpired || !state.consentAccepted || state.exportBusy;
              elements.exportFeedbackClose.disabled = state.exportBusy;
              elements.collectionPreviewButton.disabled = state.authExpired || !state.consentAccepted;
              elements.collectionModeCurrent.disabled = state.authExpired || !state.consentAccepted || !state.collectionPreview;
              elements.collectionModeAll.disabled = state.authExpired || !state.consentAccepted || !state.collectionPreview;
              elements.collectionSubmitButton.disabled = state.authExpired || !state.consentAccepted || !state.collectionPreview;
              elements.batchSubmitButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queuePauseButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queueResumeButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queueClearCompletedButton.disabled = state.authExpired || !state.consentAccepted;
            }

            function renderStageList(progress, activeStage, jobStatus, timing = {}) {
              const status = jobStatus || "idle";
              if (!["running", "failed", "canceling"].includes(status)) {
                elements.stageList.innerHTML = "";
                return;
              }
              const hasProgress = Array.isArray(progress) && progress.length;
              const items = hasProgress ? progress : fallbackStageItems(activeStage, status);
              const activeStageElapsed = readableDuration(timing.stage_elapsed_seconds);
              elements.stageList.innerHTML = items.map((item) => {
                const stage = typeof item.stage === "string" ? item.stage : "";
                const status = typeof item.status === "string" ? item.status : "pending";
                const active = stage === activeStage ? " 当前" : "";
                const statusClass = ["pending", "running", "done", "failed", "succeeded", "queued", "canceled"].includes(status) ? status : "pending";
                const description = stageDescription(stage);
                const stageTime = active && activeStageElapsed ? `<span>当前步骤 ${escapeHtml(activeStageElapsed)}</span>` : "";
                return `
                  <li class="stage-item">
                    <div class="stage-name">${escapeHtml(stageLabel(stage))}</div>
                    ${description ? `<div class="history-meta"><span>${escapeHtml(description)}</span></div>` : ""}
                    <div class="stage-meta">
                      <span class="pill ${statusClass}">${escapeHtml(statusLabel(status))}${escapeHtml(active)}</span>
                      <span>任务: ${escapeHtml(statusLabel(jobStatus || "idle"))}</span>
                      ${stageTime}
                    </div>
                  </li>
                `;
              }).join("");
            }

            function fallbackStageItems(activeStage, jobStatus) {
              const items = STAGES.map((stage) => ({
                stage,
                status: stage === activeStage ? jobStatus : "pending",
              }));
              if (activeStage && !STAGES.includes(activeStage)) {
                const activeItem = { stage: activeStage, status: jobStatus };
                const insertAfter = activeStage === "media" ? "audio" : "";
                const insertAt = insertAfter ? items.findIndex((item) => item.stage === insertAfter) + 1 : items.length;
                if (insertAt > 0) {
                  items.splice(insertAt, 0, activeItem);
                } else {
                  items.push(activeItem);
                }
              }
              return items;
            }

            function renderTaskLiveness(data) {
              const status = data && typeof data.status === "string" ? data.status : "idle";
              if (!["running", "canceling"].includes(status)) {
                elements.taskLiveness.className = "task-liveness";
                elements.taskLiveness.innerHTML = "<div>提交视频后，会在这里显示处理进度。</div>";
                return;
              }
              const stage = data && typeof data.stage === "string" ? data.stage : "preflight";
              const elapsed = readableDuration(data.elapsed_seconds);
              const stageElapsed = readableDuration(data.stage_elapsed_seconds);
              const hint = slowStageHint(stage, data.stage_elapsed_seconds);
              elements.taskLiveness.className = hint ? "task-liveness warning" : "task-liveness";
              elements.taskLiveness.innerHTML = `
                <div><strong>${escapeHtml(stageLabel(stage))}</strong> 正在处理，页面会自动刷新。</div>
                <div class="service-status-meta">
                  ${elapsed ? `<span>已运行 ${escapeHtml(elapsed)}</span>` : ""}
                  ${stageElapsed ? `<span>当前步骤 ${escapeHtml(stageElapsed)}</span>` : ""}
                </div>
                ${hint ? `<div>${escapeHtml(hint)}</div>` : ""}
              `;
            }

            function renderLinks(artifacts, runKey, status = "idle") {
              const markup = artifactActionGroups(artifacts, runKey, status, {
                menuScope: `current:${runKey || status || "idle"}`,
              });
              elements.resultLinks.innerHTML = markup
                ? markup
                : '<div class="muted-panel">生成完成后，会在这里显示原始转录稿、整理逐字稿和导出文件。</div>';
            }

            function artifactActionGroups(artifacts, runKey, status = "idle", options = {}) {
              const safeArtifacts = artifacts && typeof artifacts === "object" ? artifacts : {};
              const primary = [];
              const exports = [];
              const advanced = [];

              if (safeArtifacts.transcript_html) primary.push(linkItem("整理逐字稿", safeArtifacts.transcript_html, "primary-action"));
              if (safeArtifacts.html) primary.push(linkItem("历史主报告", safeArtifacts.html, "primary-action"));
              if (safeArtifacts.transcript_pdf) primary.push(linkItem("逐字稿 PDF", safeArtifacts.transcript_pdf, "secondary-action"));
              if (safeArtifacts.pdf) primary.push(linkItem("历史报告 PDF", safeArtifacts.pdf, "secondary-action"));
              if (runKey && status === "succeeded") {
                advanced.push(nabaichuanButton("导出到纳百川", runKey));
              }
              if (runKey && status === "succeeded") {
                advanced.push(resummarizeButton("继续整理逐字稿", runKey));
              }
              if (safeArtifacts.raw) primary.push(linkItem("原始转录稿 TXT", safeArtifacts.raw, "secondary-action"));
              if (safeArtifacts.source_zip) exports.push(linkItem("SRT 与质量说明", safeArtifacts.source_zip, "secondary-action"));
              if (runKey && status === "succeeded") advanced.push(`<button type="button" class="link-button" data-force-article="${escapeAttr(runKey)}">重新整理全部内容</button>`);
              if (safeArtifacts.folder) advanced.push(folderButton("打开本地文件夹", safeArtifacts.folder));

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

            function copySourceButton(label, sourceUrl) {
              return `<button class="link-button secondary-action" type="button" data-copy-source-url="${escapeAttr(sourceUrl)}">${escapeHtml(label)}</button>`;
            }

            function renderFailure(stage, message, diagnostics, runKey, friendlyError, retryActions) {
              const friendly = friendlyError && typeof friendlyError === "object" ? friendlyError : null;
              const title = friendly && friendly.title ? friendly.title : "任务失败";
              const cause = friendly && friendly.cause ? friendly.cause : (message || "Unknown error.");
              const nextAction = friendly && friendly.next_action ? `<div>${escapeHtml(friendly.next_action)}</div>` : "";
              const retryButtons = Array.isArray(retryActions) && retryActions.length && runKey
                ? `<div class="stack" style="gap:6px;"><h2>下一步</h2><div>优先尝试重试当前可恢复步骤。</div><div class="action-groups">${retryActions.map((retryStage) => `<button class="link-button warning-action" type="button" data-retry-stage="${escapeAttr(retryStage)}" data-retry-run-key="${escapeAttr(runKey)}">${escapeHtml(retryLabel(retryStage))}</button>`).join("")}</div></div>`
                : "";
              elements.failurePanel.innerHTML = `
                <div class="stack" style="gap:6px;">
                  <h2>${escapeHtml(title)}</h2>
                  <div>阶段: ${escapeHtml(stageLabel(stage || "preflight"))}</div>
                  <div>${escapeHtml(cause)}</div>
                  ${nextAction}
                  ${retryButtons}
                </div>
              `;
              elements.failurePanel.classList.add("active");
            }

            function clearFailure() {
              elements.failurePanel.textContent = "";
              elements.failurePanel.classList.remove("active");
            }

            function renderHistory(items) {
              state.historyItems = Array.isArray(items) ? items : [];
              renderHistoryList();
            }

            function renderHistoryList() {
              const items = state.historyItems;
              const query = state.historyQuery.trim().toLowerCase();
              const matchedItems = query
                ? items.filter((item) => historySearchText(item).includes(query))
                : items;
              const shouldCollapse = !query && !state.historyExpanded && matchedItems.length > HISTORY_COLLAPSED_LIMIT;
              const visibleItems = shouldCollapse ? matchedItems.slice(0, HISTORY_COLLAPSED_LIMIT) : matchedItems;
              renderHistorySummary(items.length, matchedItems.length, visibleItems.length, query);

              if (items.length === 0) {
                elements.historyList.innerHTML = '<li class="muted-panel">暂无历史记录。</li>';
                return;
              }
              if (matchedItems.length === 0) {
                elements.historyList.innerHTML = '<li class="muted-panel">没有匹配的历史记录。</li>';
                return;
              }
              elements.historyList.innerHTML = visibleItems.map((item) => {
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
                const sourceUrl = historySourceUrl(item);
                const copyAction = sourceUrl
                  ? `<div class="action-groups"><div class="primary-actions">${copySourceButton("复制链接", sourceUrl)}</div></div>`
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
                    <div class="history-item-title">${escapeHtml(historyDisplayTitle(item))}</div>
                    <div class="history-meta">
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(statusLabel(item.status))}</span>
                      ${stageMeta}
                      ${transcriptMeta}
                      ${qualityMeta(item)}
                    </div>
                    ${failureDetail}
                    ${retryButtons}
                    ${copyAction}
                    ${actionMarkup}
                  </li>
                `;
              }).join("");
            }

            function renderHistorySummary(totalCount, matchedCount, visibleCount, query) {
              const hasMore = totalCount > HISTORY_COLLAPSED_LIMIT;
              elements.historyToggleButton.hidden = Boolean(query) || !hasMore;
              if (query) {
                elements.historySummary.textContent = `搜索到 ${matchedCount} 条，共 ${totalCount} 条`;
                return;
              }
              if (!totalCount) {
                elements.historySummary.textContent = "暂无历史记录";
                return;
              }
              if (!hasMore) {
                elements.historySummary.textContent = `共 ${totalCount} 条`;
                return;
              }
              if (state.historyExpanded) {
                elements.historySummary.textContent = `已展开全部 ${totalCount} 条`;
                elements.historyToggleButton.textContent = "收起";
                return;
              }
              elements.historySummary.textContent = `显示最近 ${visibleCount} 条，共 ${totalCount} 条`;
              elements.historyToggleButton.textContent = `展开更多 ${totalCount - HISTORY_COLLAPSED_LIMIT} 条`;
            }

            function historySearchText(item) {
              if (!item || typeof item !== "object") return "";
              const friendly = item.friendly_error && typeof item.friendly_error === "object" ? item.friendly_error : {};
              return [
                item.title,
                item.output_id,
                item.run_key,
                item.source_url,
                item.status,
                item.stage,
                item.transcript_source_label,
                friendly.title,
                friendly.cause,
                friendly.next_action,
              ]
                .filter(Boolean)
                .join(" ")
                .toLowerCase();
            }

            function historyDisplayTitle(item) {
              const title = item && typeof item.title === "string" ? item.title.trim() : "";
              if (title && title !== item.output_id) return title;
              return "未命名视频";
            }

            function historySourceUrl(item) {
              const sourceUrl = item && typeof item.source_url === "string" ? item.source_url.trim() : "";
              return sourceUrl;
            }

            function queueSourceLabel(item) {
              if (item && item.source === "current") return "当前任务";
              if (item && item.origin && typeof item.origin.label === "string" && item.origin.label.trim()) {
                return item.origin.label.trim();
              }
              return "队列任务";
            }

            function renderQueue(queue) {
              const totalCounts = queue && queue.queue_counts ? queue.queue_counts : (queue && queue.counts ? queue.counts : {});
              const counts = queue && queue.visible_counts ? queue.visible_counts : totalCounts;
              elements.queueSummary.textContent = queueSummaryText(queue, counts);
              elements.queueClearCompletedButton.disabled = state.authExpired || !state.consentAccepted || !hasFinishedQueueItems(totalCounts);
              updateQueueControls(queue, totalCounts);
              if (queue.storage_error || queue.execution_error) elements.queueSummary.textContent = queue.waiting_for_execution ? `等待其他任务退出，随后自动继续：${queue.execution_error}` : `队列已停止：${queue.storage_error || queue.execution_error}`;
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
                if (isQueueItem && ["queued", "running"].includes(item.status)) queueControls.push(`<button class="link-button warning-action" type="button" data-queue-cancel="${escapeAttr(item.job_id || "")}">${item.status === "running" ? "取消计算" : "取消排队"}</button>`);
                if (isQueueItem && ["failed", "canceled", "interrupted"].includes(item.status)) queueControls.push(`<button class="link-button warning-action" type="button" data-queue-retry="${escapeAttr(item.job_id || "")}">恢复处理</button>`);
                const request = item.request && typeof item.request === "object" ? item.request : {};
                const requestUrl = typeof request.url === "string" ? request.url : "";
                const displayTitle = queueDisplayTitle(item, requestUrl);
                const sourceLabel = queueSourceLabel(item);
                const transcriptMeta = transcriptSourceMeta(item);
                const timingMeta = taskTimingMeta(item);
                const stageMeta = queueStageMeta(item);
                const friendly = item.friendly_error && typeof item.friendly_error === "object" ? item.friendly_error : null;
                const failureDetail = friendly
                  ? `<div class="history-meta"><span>${escapeHtml(friendly.title || "任务失败")}</span><span>${escapeHtml(friendly.cause || "")}</span><span>${escapeHtml(friendly.next_action || "")}</span></div>`
                  : "";
                const messageMarkup = friendly
                  ? ""
                  : `<div class="history-meta"><span>${escapeHtml(item.message || "")}</span></div>`;
                return `
                  <li class="history-item">
                    <div class="history-item-title">${escapeHtml(displayTitle)}</div>
                    <div class="history-meta">
                      <span>${escapeHtml(sourceLabel)}</span>
                      <span class="pill ${(item.status || "").toLowerCase()}">${escapeHtml(statusLabel(item.status))}</span>
                      ${stageMeta}
                      ${transcriptMeta}
                      ${timingMeta}
                    </div>
                    ${qualityMeta(item)}
                    ${item.metrics && Number.isFinite(item.metrics.total_chunks) ? `<div class="history-meta">整理块：${item.metrics.completed_chunks || 0}/${item.metrics.total_chunks}；本次复用 ${item.metrics.cache_hits || 0} 块；待处理 ${item.metrics.remaining_chunks || 0} 块</div>` : ""}
                    ${messageMarkup}
                    ${failureDetail}
                    ${queueControls.length ? `<div class="action-groups">${queueControls.join("")}</div>` : ""}
                    ${actionMarkup}
                  </li>
                `;
              }).join("");
            }

            function queueSummaryText(queue, counts) {
              const safeCounts = counts && typeof counts === "object" ? counts : {};
              const queued = Number(safeCounts.queued || 0);
              const running = Number(safeCounts.running || 0);
              const failed = Number(safeCounts.failed || 0);
              const canceled = Number(safeCounts.canceled || 0);
              const paused = Boolean(queue && queue.paused);
              const parts = [];
              if (paused) parts.push("队列已暂停");
              if (running > 0) parts.push(`正在处理 ${running} 个`);
              if (queued > 0) parts.push(`排队 ${queued} 个`);
              if (failed > 0) parts.push(`${failed} 个失败需要处理`);
              if (canceled > 0) parts.push(`${canceled} 个已取消`);
              return parts.length ? parts.join(" · ") : "队列空闲";
            }

            function hasFinishedQueueItems(counts) {
              const safeCounts = counts && typeof counts === "object" ? counts : {};
              return Boolean(
                Number(safeCounts.succeeded || 0) +
                Number(safeCounts.failed || 0) +
                Number(safeCounts.canceled || 0)
              );
            }

            function updateQueueControls(queue, totalCounts) {
              const paused = Boolean(queue && queue.paused);
              elements.queuePauseButton.hidden = paused;
              elements.queueResumeButton.hidden = !paused;
              elements.queuePauseButton.disabled = state.authExpired || !state.consentAccepted;
              elements.queueResumeButton.disabled = state.authExpired || !state.consentAccepted;
            }

            function stageLabel(stage) {
              return STAGE_LABELS[stage] || stage || "-";
            }

            function qualityMeta(item) {
              const quality = item && item.quality || {status: "unknown", reasons: []};
              const labels = {clean: "自动检查未发现明显异常", needs_review: "需复查", unusable: "不可用", unknown: "未检查"};
              const detail = (Array.isArray(quality.reasons) ? quality.reasons : []).map(reason => reason.message || "").join("；");
              return `<span class="pill ${quality.review_required ? "failed" : ""}" title="${escapeAttr(detail)}">质量：${escapeHtml(labels[quality.status] || "未检查")}</span>`;
            }

            function transcriptSourceMeta(item) {
              const label = item && typeof item.transcript_source_label === "string"
                ? item.transcript_source_label.trim()
                : "";
              return label ? `<span>逐字稿：${escapeHtml(label)}</span>` : "";
            }

            function taskTimingMeta(item) {
              const elapsed = readableDuration(item && item.elapsed_seconds);
              const stageElapsed = readableDuration(item && item.stage_elapsed_seconds);
              const parts = [];
              const active = ["running", "canceling"].includes(item && item.status);
              if (elapsed) parts.push(`${active ? "已运行" : "耗时"} ${elapsed}`);
              if (stageElapsed && active) {
                parts.push(`当前步骤 ${stageElapsed}`);
              }
              return parts.map((part) => `<span>${escapeHtml(part)}</span>`).join("");
            }

            function queueStageMeta(item) {
              const status = item && item.status;
              const stage = item && item.stage;
              if (status === "failed") {
                return `<span>失败阶段: ${escapeHtml(stageLabel(stage))}</span>`;
              }
              if (["running", "canceling"].includes(status)) {
                return `<span>阶段: ${escapeHtml(stageLabel(stage))}</span>`;
              }
              return "";
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
                interrupted: "中断待恢复",
                idle: "空闲",
                pending: "待处理",
                done: "完成",
              };
              return labels[status] || status || "-";
            }

            function readableDuration(seconds) {
              const total = Number(seconds);
              if (!Number.isFinite(total) || total <= 0) return "";
              const rounded = Math.max(0, Math.round(total));
              const hours = Math.floor(rounded / 3600);
              const minutes = Math.floor((rounded % 3600) / 60);
              const remainingSeconds = rounded % 60;
              const parts = [];
              if (hours) parts.push(`${hours} 小时`);
              if (minutes) parts.push(`${minutes} 分`);
              if (!hours && remainingSeconds) parts.push(`${remainingSeconds} 秒`);
              return parts.join(" ") || "0 秒";
            }

            function slowStageHint(stage, seconds) {
              const elapsed = Number(seconds);
              if (!Number.isFinite(elapsed)) return "";
              if (stage === "audio" && elapsed >= 180) {
                return "下载音频耗时较久，可能是网络、B 站限速或视频访问限制，可以继续等待。";
              }
              if (stage === "transcript" && elapsed >= 300) {
                return "本地 Whisper 转写可能需要较长时间，视频越长等待越久，可以继续等待。";
              }
              if (stage === "summarization" && elapsed >= 180) {
                return "Codex 正在整理长视频内容，长视频整理会更久，可以继续等待。";
              }
              if (stage === "render" && elapsed >= 90) {
                return "正在生成文件；PDF 可能较慢，HTML 成功后通常已经可用。";
              }
              return "";
            }

            function queueDisplayTitle(item, requestUrl) {
              if (item && typeof item.title === "string" && item.title.trim()) {
                return item.title.trim();
              }
              if (item && ["queued", "running"].includes(item.status)) {
                return "待读取标题";
              }
              return "未命名视频";
            }

            function updateOptionsSummary() {
              const parts = [
                formatLabel(elements.formatSelect.value),
                languageLabel(elements.languageSelect.value),
              ];
              if (elements.forceWhisper.checked) parts.push("强制重新转写");
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
              if (stage === "summarization") return "继续整理逐字稿";
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
              elements.languageSelect.value = defaults.language || "auto";
              elements.forceWhisper.checked = Boolean(defaults.force_whisper);
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
                const legacy = data.legacy_reports || [];
                document.getElementById("legacy-reports-panel").hidden = !legacy.length;
                document.getElementById("legacy-report-list").innerHTML = legacy.map(item => `<li class="history-item"><div class="history-item-title">${escapeHtml(item.title || "历史主报告")}</div><div class="history-meta">${escapeHtml(item.run_id || "")}</div>${item.artifacts.html ? linkItem("历史主报告", item.artifacts.html) : ""}${item.artifacts.pdf ? linkItem("历史报告 PDF", item.artifacts.pdf) : ""}</li>`).join("");
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

            async function loadServiceStatus() {
              if (state.authExpired) return;
              try {
                const data = await apiFetch("/api/status");
                renderServiceStatus(data);
              } catch (error) {
                const message = state.authExpired
                  ? "当前页面访问已过期，请重新打开最新地址。"
                  : (error.message || "服务状态读取失败。");
                renderServiceStatusWarning(message);
              }
            }

            async function loadCurrentJob() {
              if (state.authExpired) return;
              try {
                const data = await apiFetch(state.followedJobId ? `/api/jobs/${state.followedJobId}` : "/api/jobs/current");
                state.currentStatus = typeof data.status === "string" ? data.status : "idle";
                state.currentRunKey = typeof data.run_key === "string" ? data.run_key : "";
                updateStartButton();
                renderTaskLiveness(data);
                renderStageList(data.progress, data.stage, data.status, data);
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
                  } else if (data.status === "queued") {
                    setJobMessage("任务已排队，前面的任务结束后自动开始。");
                  } else if (data.status === "interrupted") {
                    setJobMessage("任务因服务中断而停止，已完成内容保留，请在任务中心恢复。", true);
                  } else if (data.status === "succeeded") {
                    setJobMessage(data.message || "Report ready.");
                    const completionKey = JSON.stringify([
                      data.job_id || state.followedJobId || data.run_key,
                      data.finished_at || null,
                    ]);
                    if (!state.historyCompletionKeys.has(completionKey)) {
                      state.historyCompletionKeys.add(completionKey);
                      loadHistory();
                      loadQueue();
                    }
                  } else {
                    setJobMessage("等待输入。");
                  }
                }
              } catch (error) {
                if (state.authExpired) return;
                if (state.followedJobId && (error.message || "").includes("Task not found")) followJob(null);
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
                followJob(data.job_id);
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
                language: elements.languageSelect.value,
                force_whisper: elements.forceWhisper.checked,
                require_pdf: elements.requirePdf.checked,
                allow_long_video: elements.allowLongVideo.checked,
              };
            }

            function collectionPartInputId(partIndex) {
              return `collection-part-${partIndex}`;
            }

            function setCollectionMode(mode) {
              state.collectionMode = mode === "current" ? "current" : "all";
              elements.collectionModeCurrent.className = state.collectionMode === "current"
                ? "compact secondary active"
                : "compact secondary";
              elements.collectionModeAll.className = state.collectionMode === "all"
                ? "compact secondary active"
                : "compact secondary";
            }

            function renderCollectionPreview(preview) {
              state.collectionPreview = preview && typeof preview === "object" ? preview : null;
              setCollectionMode("all");
              if (!state.collectionPreview) {
                elements.collectionPreviewPanel.hidden = true;
                elements.collectionPreviewPanel.innerHTML = '<div class="subtle">输入合集 URL 后先预览。</div>';
                updateStartButton();
                return;
              }
              const parts = Array.isArray(state.collectionPreview.parts)
                ? state.collectionPreview.parts
                : [];
              const total = Number(state.collectionPreview.total_parts || parts.length || 0);
              const title = state.collectionPreview.title || state.collectionPreview.bvid || "未命名合集";
              const currentPart = Number(state.collectionPreview.current_part_index || 1);
              const rows = parts.map((part) => {
                const partIndex = Number(part.part_index || 0);
                const partTitle = part.title || `P${partIndex}`;
                const duration = readableDuration(part.duration);
                const current = part.is_current ? "当前 URL" : `P${partIndex}`;
                return `
                  <label class="part-row" for="${escapeAttr(collectionPartInputId(partIndex))}">
                    <input id="${escapeAttr(collectionPartInputId(partIndex))}" type="checkbox">
                    <span class="part-title">${escapeHtml(partTitle)}</span>
                    <span class="subtle">${escapeHtml(duration || current)}</span>
                  </label>
                `;
              }).join("");
              elements.collectionPreviewPanel.hidden = false;
              elements.collectionPreviewPanel.innerHTML = `
                <div>
                  <h2>${escapeHtml(title)}</h2>
                  <p class="subtle">共 ${escapeHtml(total)} 个视频 · 当前 URL: P${escapeHtml(currentPart)}</p>
                </div>
                <div id="collection-part-list" class="part-list">${rows || '<div class="subtle">未读取到分 P 列表。</div>'}</div>
              `;
              parts.forEach((part) => {
                const input = document.getElementById(collectionPartInputId(Number(part.part_index || 0)));
                if (input) input.checked = true;
              });
              updateStartButton();
            }

            async function previewCollection() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              if (!state.consentAccepted) {
                setJobMessage("请先接受本地处理告知。", true);
                return;
              }
              const url = elements.collectionUrl.value.trim();
              if (!url) {
                setJobMessage("请输入 B 站合集 URL。", true);
                elements.collectionUrl.focus();
                return;
              }
              const data = await apiFetch("/api/bilibili/collection/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url }),
              });
              renderCollectionPreview(data);
              const total = Number(data.total_parts || 0);
              setJobMessage(`已读取合集: 共 ${total} 个视频。`);
            }

            function collectionItemPayload(url, title) {
              const item = { url };
              if (typeof title === "string" && title.trim()) item.title = title.trim();
              return item;
            }

            function collectionItemFromPart(part) {
              if (!part || typeof part !== "object" || typeof part.url !== "string" || !part.url) return null;
              return collectionItemPayload(part.url, typeof part.title === "string" ? part.title : "");
            }

            function collectionSelectedItems() {
              const preview = state.collectionPreview;
              if (!preview || typeof preview !== "object") return [];
              const parts = Array.isArray(preview.parts) ? preview.parts : [];
              if (state.collectionMode === "current") {
                const currentUrl = typeof preview.current_url === "string" ? preview.current_url : "";
                const currentPartIndex = Number(preview.current_part_index || 0);
                const currentPart = parts.find((part) => part && part.is_current)
                  || parts.find((part) => part && part.url === currentUrl)
                  || parts.find((part) => Number(part && part.part_index || 0) === currentPartIndex);
                if (currentPart) {
                  const item = collectionItemFromPart(currentPart);
                  return item ? [item] : [];
                }
                return currentUrl ? [collectionItemPayload(currentUrl, preview.title || "")] : [];
              }
              return parts
                .filter((part) => {
                  const input = document.getElementById(collectionPartInputId(Number(part.part_index || 0)));
                  return input ? input.checked : false;
                })
                .map(collectionItemFromPart)
                .filter(Boolean);
            }

            async function submitCollectionSelection() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              const items = collectionSelectedItems();
              if (!items.length) {
                setJobMessage("请选择至少一个合集视频。", true);
                return;
              }
              const data = await apiFetch("/api/jobs/batch", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ items, ...currentOptionsPayload() }),
              });
              renderQueue(data);
              setJobMessage(`已加入队列: ${items.length} 个视频。`);
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
              setJobMessage("已清除已结束的队列任务。");
            }

            async function cancelJob() {
              if (state.authExpired) {
                markAuthExpired();
                return;
              }
              try {
                const data = await apiFetch(state.followedJobId ? `/api/jobs/queue/${state.followedJobId}/cancel` : "/api/jobs/current/cancel", { method: "POST" });
                state.currentStatus = typeof data.status === "string" ? data.status : "canceling";
                updateStartButton();
                setJobMessage("正在取消任务。");
                await loadCurrentJob();
              } catch (error) {
                setJobMessage(error.message || "取消失败。", true);
              }
            }

            async function retryAction(stage, runKey, forceArticle = false) {
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
                  force_article: forceArticle,
                  allow_long_video: elements.allowLongVideo.checked,
                  format: elements.formatSelect.value,
                  require_pdf: elements.requirePdf.checked,
                }),
              });
              followJob(data.job_id);
              state.currentStatus = typeof data.status === "string" ? data.status : "queued";
              updateStartButton();
              clearFailure();
              setJobMessage(`${retryLabel(stage)}已提交。`);
              await loadCurrentJob();
            }

            function exportTitle(runKey) {
              const item = state.historyItems.find(item => item.run_key === runKey);
              return item && item.title ? item.title : "选定的视频";
            }

            function exportDownloadLink(label, href, variant = "") {
              if (typeof href !== "string" || !href) return "";
              let url;
              try { url = new URL(href, location.origin); } catch (_) { return ""; }
              const allowed = /^\\/api\\/runs\\/[A-Za-z0-9_-]+\\/runs\\/[0-9_-]+\\/files\\/nabaichuan\\.jsonl$/.test(url.pathname)
                || /^\\/api\\/exports\\/nabaichuan_batch_[0-9_]+(?:\\.jsonl|\\.report\\.json)$/.test(url.pathname);
              if (url.origin !== location.origin || !allowed) return "";
              return linkItem(label, url.pathname + url.search, variant);
            }

            function exportReasons(reasons) {
              const messages = Array.isArray(reasons)
                ? reasons.filter(reason => reason && typeof reason.message === "string").map(reason => reason.message)
                : [];
              return messages.length
                ? `<ul class="export-feedback-reasons">${messages.map(message => `<li>${escapeHtml(message)}</li>`).join("")}</ul>`
                : "<p>自动检查提示需要复查，请对照原始稿核对整理内容。</p>";
            }

            function showExportFeedback(title, body, action = null, showWarning = false) {
              const wasHidden = elements.exportFeedbackPanel.hidden;
              state.exportAction = action;
              elements.exportFeedbackPanel.hidden = false;
              elements.exportFeedback.innerHTML = `<h3>${escapeHtml(title)}</h3>${body}`;
              elements.exportIncludeButton.hidden = !action;
              elements.exportIncludeButton.textContent = action && action.label || "仍然导出并保留警告";
              elements.exportReviewNotice.hidden = !showWarning;
              updateStartButton();
              if (wasHidden) {
                elements.exportFeedbackPanel.focus({preventScroll: true});
                if (elements.exportFeedbackPanel.scrollIntoView) elements.exportFeedbackPanel.scrollIntoView({block: "nearest"});
              }
            }

            async function exportNabaichuan(runKey, includeReview = false) {
              if (state.exportBusy) return;
              if (state.authExpired) {
                markAuthExpired();
                showExportFeedback("尚未导出", "<p>当前访问已过期，请刷新页面后重试导出。</p>");
                return;
              }
              if (!runKey) {
                showExportFeedback("尚未导出", "<p>请先选择一个已有结果。</p>");
                return;
              }
              const title = exportTitle(runKey);
              state.exportBusy = true;
              showExportFeedback("正在导出", `<p>${escapeHtml(title)}</p><p>正在生成纳百川文件，完成后会在这里保留结果。</p>`);
              try {
                const data = await apiFetch(`/api/runs/${runKey}/exports/nabaichuan${includeReview ? "?include_review_required=true" : ""}`, { method: "POST" });
                const artifact = data && typeof data.artifact === "string" ? exportDownloadLink("下载纳百川 JSONL", data.artifact, "primary-action") : "";
                showExportFeedback("已导出", `<p>${escapeHtml(title)}</p><p>${includeReview ? "本次允许纳入需复查内容；已有质量警告仍保留在导出记录中。" : "纳百川文件已生成。"}</p>${artifact ? `<div class="primary-actions">${artifact}</div>` : ""}`, null, includeReview);
                await loadHistory();
              } catch (error) {
                if (error.payload && error.payload.review_required) {
                  showExportFeedback("尚未导出", `<p>${escapeHtml(title)}</p>${exportReasons(error.payload.quality && error.payload.quality.reasons)}`, {
                    kind: "single", runKey, includeReview: true, label: "仍然导出并保留警告",
                  }, true);
                } else {
                  showExportFeedback("导出未完成", `<p>${escapeHtml(title)}</p><p>${escapeHtml(error.message || "导出请求失败，请稍后重试。")}</p>`, {
                    kind: "single", runKey, includeReview, label: includeReview ? "重试导出并保留警告" : "重试导出",
                  }, includeReview);
                }
              } finally {
                state.exportBusy = false;
                updateStartButton();
              }
            }

            async function exportNabaichuanBatch(includeReview = false) {
              if (state.exportBusy) return;
              if (state.authExpired) {
                markAuthExpired();
                showExportFeedback("尚未导出", "<p>当前访问已过期，请刷新页面后重试导出。</p>");
                return;
              }
              state.exportBusy = true;
              showExportFeedback("正在批量导出", "<p>正在检查已有结果，完成后会保留导出和跳过记录。</p>");
              try {
                const data = await apiFetch(`/api/exports/nabaichuan/batch${includeReview ? "?include_review_required=true" : ""}`, { method: "POST" });
                const count = Number.isFinite(Number(data.exported_runs)) ? Number(data.exported_runs) : 0;
                const skipped = Number.isFinite(Number(data.skipped_runs)) ? Number(data.skipped_runs) : 0;
                const records = Number.isFinite(Number(data.records_written)) ? Number(data.records_written) : 0;
                const items = Array.isArray(data.items) ? data.items : [];
                const skippedItems = items.filter(item => item && item.status === "skipped");
                const reviewSkipped = skippedItems.filter(item => item.reason === "quality_review_required");
                const links = [];
                if (count > 0 && typeof data.artifact === "string") links.push(exportDownloadLink("下载批量 JSONL", data.artifact, "primary-action"));
                if (typeof data.report === "string") links.push(exportDownloadLink("下载导出报告", data.report));
                const reasons = skippedItems.length ? `<details open><summary>跳过原因（${skippedItems.length} 项）</summary><ul class="export-feedback-reasons">${skippedItems.map(item => `<li>${escapeHtml(item.run_key || "历史结果")}：${escapeHtml(item.message || (item.reason === "quality_review_required" ? "内容需要复查，默认未纳入。" : item.reason === "run_not_succeeded" ? "尚未成功完成处理。" : "当前结果无法导出，请查看导出报告。"))}</li>`).join("")}</ul></details>` : "";
                const action = !includeReview && reviewSkipped.length ? {
                  kind: "batch", includeReview: true, label: "重新导出全部结果并允许需复查内容",
                } : null;
                showExportFeedback(count > 0 ? "批量导出完成" : "尚未导出（批量）", `<p>已导出 ${count} 项、${records} 条记录；跳过 ${skipped} 项。</p>${reasons}${action ? "<p>点击后会重新检查当时全部成功结果，包括此后完成的结果；需复查内容也会保留警告导出。</p>" : ""}${links.length ? `<div class="primary-actions">${links.join("")}</div>` : ""}${includeReview ? "<p>本次允许纳入需复查内容；已有质量警告仍保留。</p>" : ""}`, action, Boolean(action) || includeReview);
              } catch (error) {
                showExportFeedback("批量导出未完成", `<p>${escapeHtml(error.message || "导出请求失败，请稍后重试。")}</p>`, {
                  kind: "batch", includeReview, label: includeReview ? "重试批量导出并保留警告" : "重试批量导出",
                }, includeReview);
              } finally {
                state.exportBusy = false;
                updateStartButton();
              }
            }

            async function copySourceUrl(sourceUrl) {
              if (!sourceUrl) return;
              if (typeof navigator === "undefined" || !navigator.clipboard || !navigator.clipboard.writeText) {
                setJobMessage("当前浏览器不支持自动复制，请手动复制链接。", true);
                return;
              }
              await navigator.clipboard.writeText(sourceUrl);
              setJobMessage("已复制视频链接。");
            }

            function init() {
              renderStageList([], "preflight", "idle");
              renderLinks({}, "");
              loadServiceStatus();
              loadConfig().catch((error) => setJobMessage(error.message || "配置读取失败。", true));
              loadHistory();
              loadCurrentJob();
              loadQueue();
              elements.consentButton.addEventListener("click", acceptConsent);
              elements.exportFeedbackClose.addEventListener("click", () => {
                if (state.exportBusy) return;
                state.exportAction = null;
                elements.exportFeedbackPanel.hidden = true;
              });
              elements.exportIncludeButton.addEventListener("click", async () => {
                const action = state.exportAction;
                if (!action || state.exportBusy || state.authExpired || !state.consentAccepted) return;
                if (action.kind === "single") await exportNabaichuan(action.runKey, action.includeReview);
                else if (action.kind === "batch") await exportNabaichuanBatch(action.includeReview);
              });
              elements.jobForm.addEventListener("submit", startJob);
              elements.cancelButton.addEventListener("click", cancelJob);
              elements.historySearch.addEventListener("input", () => {
                state.historyQuery = elements.historySearch.value || "";
                renderHistoryList();
              });
              elements.historyToggleButton.addEventListener("click", () => {
                state.historyExpanded = !state.historyExpanded;
                renderHistoryList();
              });
              [
                elements.formatSelect,
                elements.languageSelect,
                elements.forceWhisper,
                elements.requirePdf,
                elements.allowLongVideo,
              ].forEach((element) => element.addEventListener("change", updateOptionsSummary));
              elements.batchNabaichuanButton.addEventListener("click", () => {
                exportNabaichuanBatch().catch((error) => {
                  setJobMessage(error.message || "批量导出失败。", true);
                });
              });
              elements.collectionPreviewButton.addEventListener("click", () => {
                previewCollection().catch((error) => {
                  setJobMessage(error.message || "合集预览失败。", true);
                });
              });
              elements.collectionModeAll.addEventListener("click", () => setCollectionMode("all"));
              elements.collectionModeCurrent.addEventListener("click", () => setCollectionMode("current"));
              elements.collectionSubmitButton.addEventListener("click", () => {
                submitCollectionSelection().catch((error) => {
                  setJobMessage(error.message || "合集加入队列失败。", true);
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
                  setJobMessage(error.message || "清除已结束失败。", true);
                });
              });
              document.addEventListener("toggle", (event) => {
                const target = event.target;
                if (!target || !target.getAttribute || !target.classList || !target.classList.contains("action-menu")) return;
                rememberOpenMenu(target.getAttribute("data-menu-key"), Boolean(target.open));
              }, true);
              document.addEventListener("click", (event) => {
                const forceTarget = event.target && event.target.closest ? event.target.closest("[data-force-article]") : null;
                if (forceTarget) {
                  if (window.confirm("重新整理全部内容将忽略已有文章块缓存；旧成果在新版成功前保留。继续？")) retryAction("article", forceTarget.getAttribute("data-force-article"), true).catch(error => setJobMessage(error.message, true));
                  return;
                }
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
                    setJobMessage(error.message || "整理逐字稿失败。", true);
                  });
                  return;
                }
                const copyTarget = event.target && event.target.closest
                  ? event.target.closest("[data-copy-source-url]")
                  : null;
                if (copyTarget) {
                  copySourceUrl(copyTarget.getAttribute("data-copy-source-url")).catch((error) => {
                    setJobMessage(error.message || "复制链接失败。", true);
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
                loadServiceStatus();
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
