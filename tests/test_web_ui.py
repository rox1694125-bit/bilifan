from bilifan.web.ui import render_app_html


def test_render_app_html_contains_workbench_contract():
    html = render_app_html()

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


def test_render_app_html_has_no_external_http_resources():
    html = render_app_html()

    assert "http://" not in html
    assert "https://" not in html
