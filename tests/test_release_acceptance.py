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
