"""Independent release checks for user-visible guarantees across workbench surfaces."""
from bilifan.web.ui import render_app_html
from test_web_ui import _extract_inline_script, _run_node_ui_harness


def test_review_required_stays_visible_in_history_after_queue_is_cleared():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        async function fetchMock(path, options = {}) {
          if (path === "/api/config") return jsonResponse({consent:{local_processing:true},defaults:{format:"html",language:"zh"}});
          if (path === "/api/history") return jsonResponse({items:[{
            title:"A completed transcript", output_id:"BV1abcDEF12G_p1",
            run_key:"BV1abcDEF12G_p1/runs/2026-09-29_120000", status:"succeeded", stage:"render",
            transcript_source_label:"Whisper turbo",
            quality:{status:"needs_review",review_required:true,reasons:[{code:"article_numbers_changed",message:"整理数字与原稿不同"}]},
            artifacts:{transcript_html:"/api/runs/BV1abcDEF12G_p1/runs/2026-09-29_120000/files/transcript.html"}
          }],legacy_reports:[]});
          if (path === "/api/jobs/current") return jsonResponse({status:"idle",progress:[],artifacts:{}});
          if (path === "/api/jobs/queue") return jsonResponse({counts:{},items:[]});
          if (path === "/api/status") return jsonResponse({ok:true,service:"bilifan-web-ui"});
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        assert(elements["history-list"].innerHTML.includes("需复查"));
        assert(elements["history-list"].innerHTML.includes("A completed transcript"));
        assert(!elements["history-list"].innerHTML.includes("人工审核通过"));
        assert(elements["queue-list"].innerHTML.includes("暂无队列任务"));
        ''',
    )


def test_running_task_can_pause_later_dispatch_without_waiting_items():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        let paused = false;
        function queueState() {return {paused,counts:{running:1,queued:0},items:[]};}
        async function fetchMock(path, options = {}) {
          fetchCalls.push({path,method:options.method || "GET"});
          if (path === "/api/config") return jsonResponse({consent:{local_processing:true},defaults:{format:"html",language:"zh"}});
          if (path === "/api/history") return jsonResponse({items:[],legacy_reports:[]});
          if (path === "/api/jobs/current") return jsonResponse({status:"running",stage:"transcript",progress:[],artifacts:{}});
          if (path === "/api/jobs/queue") return jsonResponse(queueState());
          if (path === "/api/jobs/queue/pause") {paused=true;return jsonResponse(queueState());}
          if (path === "/api/status") return jsonResponse({ok:true,service:"bilifan-web-ui"});
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        assert.equal(elements["queue-pause-button"].disabled, false);
        await elements["queue-pause-button"].listeners.click();
        await flush();
        assert(fetchCalls.some(call => call.path === "/api/jobs/queue/pause" && call.method === "POST"));
        assert.equal(elements["queue-pause-button"].hidden, true);
        assert.equal(elements["queue-resume-button"].hidden, false);
        assert.equal(elements["start-button"].disabled, false);
        ''',
    )


_EXPORT_BOOTSTRAP = '''
  if (path === "/api/config") return jsonResponse({consent:{local_processing:true},defaults:{format:"html",language:"zh"}});
  if (path === "/api/history") return jsonResponse({items:[],legacy_reports:[]});
  if (path === "/api/jobs/current") return jsonResponse({status:"running",stage:"transcript",message:"后台任务仍在处理",progress:[],artifacts:{}});
  if (path === "/api/jobs/queue") return jsonResponse({counts:{running:1,queued:0},items:[]});
  if (path === "/api/status") return jsonResponse({ok:true,service:"bilifan-web-ui"});
'''


def test_single_export_review_feedback_survives_polling_until_explicit_inclusion():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        let includeCalls = 0;
        let releaseExport;
        async function fetchMock(path, options = {}) {
          fetchCalls.push({path,method:options.method || "GET"});
        ''' + _EXPORT_BOOTSTRAP + '''
          if (path.endsWith("/exports/nabaichuan")) return jsonResponse({review_required:true,quality:{reasons:[{message:"数字需要复查 <img src=x onerror=alert(1)>"}]}},false,"Conflict",409);
          if (path.endsWith("/exports/nabaichuan?include_review_required=true")) {
            includeCalls++;
            return new Promise(resolve => {releaseExport = () => resolve(jsonResponse({artifact:"/api/runs/BV1abcDEF12G_p1/runs/2026-09-29_120000/files/nabaichuan.jsonl"}));});
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        window.confirm = () => {throw new Error("native confirm must not be used for exports");};
        await exportNabaichuan("BV1abcDEF12G_p1/runs/2026-09-29_120000");
        assert(elements["export-feedback"].innerHTML.includes("尚未导出"));
        assert(elements["export-feedback"].innerHTML.includes("数字需要复查"));
        assert(!elements["export-feedback"].innerHTML.includes("<img"));
        assert.equal(elements["export-include-button"].hidden, false);
        assert.equal(elements["export-include-button"].textContent, "仍然导出并保留警告");
        assert.equal(elements["export-review-notice"].hidden, false);
        assert.equal(includeCalls, 0);
        const feedback = elements["export-feedback"].innerHTML;
        await loadCurrentJob(); await loadQueue(); await loadHistory(); await flush();
        assert.equal(elements["export-feedback"].innerHTML, feedback);
        assert.equal(elements["export-feedback-panel"].hidden, false);
        const pending = elements["export-include-button"].listeners.click();
        await flush();
        assert.equal(elements["export-include-button"].disabled, true);
        await elements["export-include-button"].listeners.click();
        assert.equal(includeCalls, 1);
        releaseExport(); await pending; await flush();
        assert(elements["export-feedback"].innerHTML.includes("已导出"));
        assert(elements["export-feedback"].innerHTML.includes("下载纳百川 JSONL"));
        assert(elements["export-feedback"].innerHTML.includes('/files/nabaichuan.jsonl?token=test-token'));
        assert.equal(elements["export-include-button"].hidden, true);
        assert.equal(elements["export-review-notice"].hidden, false);
        assert(!elements["job-message"].textContent.includes("token="));
        assert(!fetchCalls.some(call => call.path.startsWith("/api/exports/nabaichuan/batch")));
        await elements["export-feedback-close"].listeners.click();
        await loadCurrentJob(); await flush();
        assert.equal(elements["export-feedback-panel"].hidden, true);
        ''',
    )


def test_batch_export_displays_skips_report_and_requires_its_own_explicit_override():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        let includeCalls = 0;
        async function fetchMock(path, options = {}) {
          fetchCalls.push({path,method:options.method || "GET"});
        ''' + _EXPORT_BOOTSTRAP + '''
          if (path === "/api/exports/nabaichuan/batch") return jsonResponse({exported_runs:1,records_written:4,skipped_runs:2,
            artifact:"/api/exports/nabaichuan_batch_20260929_120000.jsonl",report:"/api/exports/nabaichuan_batch_20260929_120000.report.json",
            items:[{status:"skipped",run_key:"review-one",reason:"quality_review_required",message:"数字需复查"},{status:"skipped",run_key:"failed-two",reason:"run_not_succeeded"}]});
          if (path === "/api/exports/nabaichuan/batch?include_review_required=true") {
            includeCalls++;
            // Another review-required result completed while this feedback stayed open.
            return jsonResponse({exported_runs:3,records_written:12,skipped_runs:1,
              artifact:"/api/exports/nabaichuan_batch_20260929_120001.jsonl",report:"/api/exports/nabaichuan_batch_20260929_120001.report.json",
              items:[{status:"skipped",run_key:"failed-two",reason:"run_not_succeeded"}]});
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        window.confirm = () => {throw new Error("native confirm must not be used for exports");};
        await elements["batch-nabaichuan-button"].listeners.click(); await flush();
        assert.equal(includeCalls, 0);
        assert(elements["export-feedback"].innerHTML.includes("已导出 1 项、4 条记录；跳过 2 项"));
        assert(elements["export-feedback"].innerHTML.includes("数字需复查"));
        assert(elements["export-feedback"].innerHTML.includes("尚未成功完成处理"));
        assert(elements["export-feedback"].innerHTML.includes("下载导出报告"));
        assert(elements["export-feedback"].innerHTML.includes("下载批量 JSONL"));
        assert.equal(elements["export-include-button"].textContent, "重新导出全部结果并允许需复查内容");
        assert(elements["export-feedback"].innerHTML.includes("包括此后完成的结果"));
        const feedback = elements["export-feedback"].innerHTML;
        await loadCurrentJob(); await loadQueue(); await loadHistory(); await flush();
        assert.equal(elements["export-feedback"].innerHTML, feedback);
        await elements["export-include-button"].listeners.click(); await flush();
        assert.equal(includeCalls, 1);
        assert(elements["export-feedback"].innerHTML.includes("已导出 3 项、12 条记录；跳过 1 项"));
        assert.equal(elements["export-include-button"].hidden, true);
        assert.equal(elements["export-review-notice"].hidden, false);
        ''',
    )


def test_export_errors_keep_retry_visible_without_implying_quality_override():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        let requests = 0;
        async function fetchMock(path, options = {}) {
          fetchCalls.push({path,method:options.method || "GET"});
        ''' + _EXPORT_BOOTSTRAP + '''
          if (path.endsWith("/exports/nabaichuan")) {
            requests++;
            return jsonResponse({detail:"当前任务未成功，无法导出。"},false,"Conflict",409);
          }
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        await exportNabaichuan("BV1abcDEF12G_p1/runs/2026-09-29_120000");
        assert(elements["export-feedback"].innerHTML.includes("导出未完成"));
        assert(elements["export-feedback"].innerHTML.includes("当前任务未成功"));
        assert.equal(elements["export-include-button"].textContent, "重试导出");
        assert.equal(elements["export-review-notice"].hidden, true);
        const feedback = elements["export-feedback"].innerHTML;
        await loadCurrentJob(); await flush();
        assert.equal(elements["export-feedback"].innerHTML, feedback);
        await elements["export-include-button"].listeners.click(); await flush();
        assert.equal(requests, 2);
        assert(!fetchCalls.some(call => call.path.includes("include_review_required")));
        ''',
    )


def test_export_feedback_does_not_render_untrusted_download_protocol():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        async function fetchMock(path, options = {}) {
        ''' + _EXPORT_BOOTSTRAP + '''
          if (path.endsWith("/exports/nabaichuan")) return jsonResponse({artifact:"javascript:javascript:alert(1)"});
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        await exportNabaichuan("BV1abcDEF12G_p1/runs/2026-09-29_120000");
        assert(!elements["export-feedback"].innerHTML.includes("javascript:"));
        assert(!elements["export-feedback"].innerHTML.includes("href="));
        ''',
    )


def test_same_run_retry_refreshes_history_once_for_the_new_successful_task():
    _run_node_ui_harness(
        _extract_inline_script(render_app_html()),
        fetch_logic='''
        let phase = "original_done";
        let historyRequests = 0;
        const runKey = "BV1sameTEST_p1/runs/2026-09-29_120000";
        async function fetchMock(path, options = {}) {
          if (path === "/api/config") return jsonResponse({consent:{local_processing:true},defaults:{format:"html",language:"zh"}});
          if (path === "/api/history") {
            historyRequests++;
            return jsonResponse({items:[{run_key:runKey,title:"同一份逐字稿",status:"succeeded",artifacts:{},
              quality:phase === "retry_done" ? {status:"clean",review_required:false,reasons:[]} :
                {status:"needs_review",review_required:true,reasons:[{message:"旧版内容需要核对"}]}}],legacy_reports:[]});
          }
          if (path === "/api/jobs/current") return jsonResponse({
            job_id:phase === "original_done" ? "original-job" : "retry-job",
            run_key:runKey, status:phase === "retry_running" ? "running" : "succeeded",
            finished_at:phase === "original_done" ? "2026-09-29T12:00:00Z" : phase === "retry_done" ? "2026-09-29T12:05:00Z" : null,
            stage:phase === "retry_running" ? "summarization" : "render", progress:[],artifacts:{}});
          if (path === "/api/jobs/queue") return jsonResponse({counts:{},items:[]});
          if (path === "/api/status") return jsonResponse({ok:true,service:"bilifan-web-ui"});
          throw new Error(`unexpected fetch ${path}`);
        }
        ''',
        assertions='''
        assert(elements["history-list"].innerHTML.includes("质量：需复查"));
        const beforeRetry = historyRequests;
        phase = "retry_running";
        await loadCurrentJob(); await flush();
        assert.equal(historyRequests, beforeRetry);
        phase = "retry_done";
        await loadCurrentJob(); await flush();
        assert(elements["history-list"].innerHTML.includes("自动检查未发现明显异常"));
        assert(!elements["history-list"].innerHTML.includes("质量：需复查"));
        assert.equal(historyRequests, beforeRetry + 1);
        for (let poll = 0; poll < 3; poll++) {await loadCurrentJob(); await flush();}
        assert.equal(historyRequests, beforeRetry + 1);
        ''',
    )
