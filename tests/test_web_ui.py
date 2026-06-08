from bilifan.web.ui import render_app_html


def test_render_app_html_contains_workbench_contract():
    html = render_app_html()

    required_strings = [
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


def test_render_app_html_has_no_external_http_resources():
    html = render_app_html()

    assert "http://" not in html
    assert "https://" not in html
