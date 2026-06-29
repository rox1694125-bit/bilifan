# Bilifan Feishu Intake P2 Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the dedicated Feishu app to Bilifan through a deterministic Hermes gateway hook, then activate a real Bilifan Hermes profile only after the profile credentials, restart scope, and smoke target are explicitly confirmed.

**Architecture:** Bilifan remains the local task engine and owns the intake API plus queue state. Hermes remains the Feishu runtime and owns webhook reception, chat authorization, profile isolation, credentials, and outbound replies. P2 adds a Bilifan project-local Hermes plugin that uses `pre_gateway_dispatch` to intercept Feishu messages with video URLs, submit the whole URL batch to `POST /api/intake/feishu`, and send one immediate acknowledgement; true completion replies stay in P3.

**Tech Stack:** Python, Typer, FastAPI, pytest, Hermes project plugin under `.hermes/plugins/`, Hermes `pre_gateway_dispatch`, Feishu adapter through Hermes gateway.

---

## Scope

In scope for P2 code:

- Add a stable Bilifan web/API token path through `BILIFAN_WEB_TOKEN`.
- Add a project-local Hermes plugin at `.hermes/plugins/bilifan_intake/`.
- Extract multiple links from one Feishu message and preserve order.
- Submit one Feishu message as one Bilifan intake batch.
- Send one immediate Feishu acknowledgement with accepted, rejected, and duplicate counts.
- Add focused unit tests for token resolution, URL extraction, payload shape, profile gating, and acknowledgement delivery.

In scope for real runtime only after explicit confirmation:

- Create or update `/Users/jack/.hermes/profiles/bilifan`.
- Decide whether the Bilifan profile uses a new Feishu app credential set or clones the existing `nabaichuan` Feishu app credentials.
- Enable the project plugin for only the Bilifan profile.
- Restart only the Bilifan web service and the Bilifan Hermes gateway.
- Run one real Feishu smoke against the confirmed app/chat/thread.

Out of scope for P2:

- No final completion watcher. That is P3.
- No Feishu card buttons.
- No Bilifan-side Feishu SDK, tenant token, app secret, or webhook handling.
- No changes to shared Hermes Feishu adapter behavior.
- No Nabaichuan file changes.
- No Cloudflare, DNS, deploy, commit, push, or external publishing changes.

## Confirmation Gate Before Runtime Activation

Do not execute the runtime activation task until the operator confirms all of these exact choices:

1. Feishu credential source:
   - Recommended: create a fresh `bilifan` Hermes profile without copying `.env`, then configure Bilifan's own Feishu app credentials there.
   - Fast path: clone from `nabaichuan`, which copies its `.env` and therefore reuses the same Feishu app identity.
2. Restart scope:
   - Restart Bilifan web tmux session `bilifan-web`.
   - Start or restart only `hermes -p bilifan gateway`.
3. Real smoke target:
   - Recommended: the operator sends a test URL to the dedicated Bilifan Feishu app, and Codex verifies logs/state plus the Feishu acknowledgement.
   - Alternative: Codex sends one exact message to one exact confirmed Feishu chat/thread. This requires the exact target and full message body immediately before sending.

## File Structure

- `src/bilifan/cli.py`: resolve `BILIFAN_WEB_TOKEN` for `bilifan serve` while preserving generated-token fallback.
- `tests/test_cli.py`: cover stable token use and blank-token rejection.
- `scripts/start-bilifan-remote-tmux.sh`: pass `BILIFAN_WEB_TOKEN` into the web tmux session without changing tunnel behavior.
- `.hermes/plugins/bilifan_intake/plugin.yaml`: Hermes plugin manifest.
- `.hermes/plugins/bilifan_intake/__init__.py`: deterministic Feishu URL intake hook.
- `tests/test_hermes_bilifan_intake_plugin.py`: pure plugin tests with fake Hermes event/gateway objects and no network.
- `docs/nabaichuan-integration.md`: add a short note that Bilifan follows the Hermes profile/plugin pattern but does not write to Nabaichuan.

## Task 1: Stable Bilifan Web Token

**Files:**

- Modify: `src/bilifan/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write the failing tests**

Append these tests near the existing `serve` tests in `tests/test_cli.py`:

```python
def test_serve_uses_bilifan_web_token_from_env(monkeypatch):
    calls: dict[str, object] = {}

    def fail_generate_token():
        raise AssertionError("generate_token should not be called")

    def fake_create_app(*, outputs, token, open_browser, public_url=None):
        calls["create_app"] = {
            "outputs": outputs,
            "token": token,
            "open_browser": open_browser,
            "public_url": public_url,
        }
        return "app-instance"

    monkeypatch.setattr(cli, "generate_token", fail_generate_token)
    monkeypatch.setattr(cli, "create_app", fake_create_app)
    monkeypatch.setattr(cli, "_find_available_port", lambda host, preferred_port: 8765)
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.update(kwargs))

    result = runner.invoke(
        app,
        ["serve", "--no-open"],
        env={"BILIFAN_WEB_TOKEN": "stable-local-token"},
    )

    assert result.exit_code == 0
    assert calls["create_app"] == {
        "outputs": cli.Path("./outputs"),
        "token": "stable-local-token",
        "open_browser": False,
        "public_url": None,
    }


def test_serve_rejects_blank_bilifan_web_token(monkeypatch):
    calls: dict[str, object] = {}

    monkeypatch.setattr(cli, "generate_token", lambda: "generated-token")
    monkeypatch.setattr(cli, "create_app", lambda **kwargs: calls.setdefault("create_app", kwargs))

    result = runner.invoke(
        app,
        ["serve", "--no-open"],
        env={"BILIFAN_WEB_TOKEN": "   "},
    )

    assert result.exit_code == 2
    assert "BILIFAN_WEB_TOKEN must not be blank" in result.output
    assert calls == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest tests/test_cli.py::test_serve_uses_bilifan_web_token_from_env tests/test_cli.py::test_serve_rejects_blank_bilifan_web_token -q
```

Expected: FAIL because `bilifan serve` always calls `generate_token()`.

- [ ] **Step 3: Implement stable token resolution**

In `src/bilifan/cli.py`, add the import and constant:

```python
import os
```

```python
BILIFAN_WEB_TOKEN_ENV = "BILIFAN_WEB_TOKEN"
```

Add this helper before `serve()`:

```python
def _resolve_web_token() -> str:
    env_token = os.environ.get(BILIFAN_WEB_TOKEN_ENV)
    if env_token is None:
        return generate_token()
    token = env_token.strip()
    if not token:
        raise typer.BadParameter(f"{BILIFAN_WEB_TOKEN_ENV} must not be blank.")
    return token
```

Change `serve()` from:

```python
token = generate_token()
```

to:

```python
token = _resolve_web_token()
```

- [ ] **Step 4: Run focused CLI tests**

Run:

```bash
uv run pytest tests/test_cli.py::test_serve_prints_url_and_starts_uvicorn tests/test_cli.py::test_serve_uses_bilifan_web_token_from_env tests/test_cli.py::test_serve_rejects_blank_bilifan_web_token -q
```

Expected: all selected tests PASS.

## Task 2: Pass Stable Token To Remote Tmux Start

**Files:**

- Modify: `scripts/start-bilifan-remote-tmux.sh`

- [ ] **Step 1: Update the tmux web session command**

Replace the web session start block with:

```bash
if tmux has-session -t "$WEB_SESSION" 2>/dev/null; then
  echo "tmux session already running: $WEB_SESSION"
else
  WEB_TMUX_ENV=()
  if [[ -n "${BILIFAN_WEB_TOKEN:-}" ]]; then
    WEB_TMUX_ENV=(-e "BILIFAN_WEB_TOKEN=$BILIFAN_WEB_TOKEN")
  fi
  tmux new-session -d "${WEB_TMUX_ENV[@]}" -s "$WEB_SESSION" \
    "cd '$ROOT' && exec .venv/bin/python -m bilifan serve --no-open --port '$PORT' --strict-port --public-url '$PUBLIC_URL'"
  echo "started tmux session: $WEB_SESSION"
fi
```

This keeps the token out of the shell command string and injects it through tmux's session environment.

- [ ] **Step 2: Syntax-check the script**

Run:

```bash
bash -n scripts/start-bilifan-remote-tmux.sh
```

Expected: no output and exit code 0.

## Task 3: Bilifan Intake Hermes Plugin Manifest And Pure Helpers

**Files:**

- Create: `.hermes/plugins/bilifan_intake/plugin.yaml`
- Create: `.hermes/plugins/bilifan_intake/__init__.py`
- Create: `tests/test_hermes_bilifan_intake_plugin.py`

- [ ] **Step 1: Write the helper tests**

Create `tests/test_hermes_bilifan_intake_plugin.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path


PLUGIN_PATH = Path(__file__).resolve().parents[1] / ".hermes" / "plugins" / "bilifan_intake" / "__init__.py"


def load_plugin():
    spec = importlib.util.spec_from_file_location("bilifan_intake_test_plugin", PLUGIN_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_urls_preserves_order_and_strips_trailing_punctuation():
    plugin = load_plugin()

    text = (
        "first https://www.bilibili.com/video/BV1xx411c7mD, "
        "then https://youtu.be/dQw4w9WgXcQ。"
    )

    assert plugin._extract_urls(text) == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://youtu.be/dQw4w9WgXcQ",
    ]


def test_build_payload_uses_message_id_batch_and_reply_target():
    plugin = load_plugin()
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(
            platform=FakePlatform("feishu"),
            chat_id="oc_chat",
            thread_id="omt_thread",
            user_name="Jack",
        ),
    )

    payload = plugin._build_payload(event, ["https://www.bilibili.com/video/BV1xx411c7mD"])

    assert payload["source"] == "feishu"
    assert payload["external_batch_id"] == "feishu:om_123"
    assert payload["submitted_by"] == {"display_name": "Jack"}
    assert payload["reply_target"] == {
        "platform": "feishu",
        "chat_id_ref": "oc_chat",
        "thread_id_ref": "omt_thread",
        "message_id_ref": "om_123",
    }
    assert payload["urls"] == ["https://www.bilibili.com/video/BV1xx411c7mD"]
    assert payload["defaults"]["format"] == "html,pdf"


class FakePlatform:
    def __init__(self, value: str):
        self.value = value


class FakeSource:
    def __init__(self, *, platform, chat_id, thread_id=None, user_name=None):
        self.platform = platform
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.user_name = user_name


class FakeEvent:
    def __init__(self, *, text, message_id, source):
        self.text = text
        self.message_id = message_id
        self.source = source
```

- [ ] **Step 2: Run helper tests to verify they fail**

Run:

```bash
uv run pytest tests/test_hermes_bilifan_intake_plugin.py::test_extract_urls_preserves_order_and_strips_trailing_punctuation tests/test_hermes_bilifan_intake_plugin.py::test_build_payload_uses_message_id_batch_and_reply_target -q
```

Expected: FAIL because the plugin does not exist.

- [ ] **Step 3: Add plugin manifest**

Create `.hermes/plugins/bilifan_intake/plugin.yaml`:

```yaml
name: bilifan_intake
version: "0.1.0"
description: "Route Feishu video URL messages into the local Bilifan intake API."
hooks:
  - pre_gateway_dispatch
```

- [ ] **Step 4: Add pure helper implementation**

Create `.hermes/plugins/bilifan_intake/__init__.py` with this initial content:

```python
from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_API_URL = "http://127.0.0.1:8792/api/intake/feishu"
DEFAULT_TASK_CENTER_URL = "https://bilifan.buyaoting.top/"
DEFAULT_PROFILE = "bilifan"
URL_RE = re.compile(r"https?://[^\s<>\"]+")
TRAILING_URL_PUNCTUATION = ".,;:!?，。！？；：）)]}」』、"


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
        if url:
            urls.append(url)
    return urls


def _platform_value(event: Any) -> str:
    platform = getattr(getattr(event, "source", None), "platform", "")
    return str(getattr(platform, "value", platform) or "")


def _event_user_name(event: Any) -> str | None:
    value = getattr(getattr(event, "source", None), "user_name", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_payload(event: Any, urls: list[str]) -> dict[str, Any]:
    source = getattr(event, "source", None)
    message_id = str(getattr(event, "message_id", "") or "")
    submitted_by = _event_user_name(event)
    return {
        "source": "feishu",
        "external_batch_id": f"feishu:{message_id or 'unknown'}",
        "submitted_by": {"display_name": submitted_by} if submitted_by else None,
        "reply_target": {
            "platform": "feishu",
            "chat_id_ref": getattr(source, "chat_id", None),
            "thread_id_ref": getattr(source, "thread_id", None),
            "message_id_ref": message_id or None,
        },
        "urls": urls,
        "defaults": {
            "format": "html,pdf",
            "language": "auto",
            "force_whisper": False,
            "summary_template": "学习笔记",
            "with_frames": False,
            "with_diagrams": False,
            "require_pdf": False,
            "allow_long_video": False,
        },
    }
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
uv run pytest tests/test_hermes_bilifan_intake_plugin.py::test_extract_urls_preserves_order_and_strips_trailing_punctuation tests/test_hermes_bilifan_intake_plugin.py::test_build_payload_uses_message_id_batch_and_reply_target -q
```

Expected: all selected tests PASS.

## Task 4: Hook Behavior, API Submission, And Feishu Acknowledgement

**Files:**

- Modify: `.hermes/plugins/bilifan_intake/__init__.py`
- Modify: `tests/test_hermes_bilifan_intake_plugin.py`

- [ ] **Step 1: Add fake gateway tests**

Append these tests to `tests/test_hermes_bilifan_intake_plugin.py`:

```python
import asyncio


def test_hook_allows_non_feishu_messages(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "bilifan")
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("telegram"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {"action": "allow"}


def test_hook_allows_other_profiles(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "nabaichuan")
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {"action": "allow"}


def test_hook_allows_feishu_messages_without_urls(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "bilifan")
    event = FakeEvent(
        text="hello",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {"action": "allow"}


def test_hook_submits_batch_and_sends_ack(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "bilifan")
    monkeypatch.setenv("BILIFAN_INTAKE_TOKEN", "local-token")
    monkeypatch.setenv("BILIFAN_TASK_CENTER_URL", "https://bilifan.buyaoting.top/")
    submitted: list[dict[str, object]] = []

    async def fake_process(event, gateway, urls):
        submitted.append({"event": event, "urls": urls})
        await plugin._send_ack(
            event,
            gateway,
            {
                "ok": True,
                "accepted": [{"url": "u1", "job_id": "j1", "status": "queued"}],
                "rejected": [{"url": "bad", "reason": "unsupported_url"}],
                "duplicates": [{"url": "u1", "reason": "duplicate_in_batch"}],
            },
        )

    monkeypatch.setattr(plugin, "_process_intake", fake_process)
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD https://youtu.be/dQw4w9WgXcQ",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="oc_chat", thread_id="omt_thread"),
    )
    gateway = FakeGateway()

    async def run():
        result = plugin.handle_pre_gateway_dispatch(event=event, gateway=gateway)
        await asyncio.sleep(0)
        return result

    assert asyncio.run(run()) == {"action": "skip", "reason": "bilifan_intake"}
    assert submitted[0]["urls"] == [
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://youtu.be/dQw4w9WgXcQ",
    ]
    assert gateway.adapters["feishu"].sent == [
        {
            "chat_id": "oc_chat",
            "text": "已收到 3 个链接：1 个已入队，1 个不支持，1 个重复。\\n任务中心：https://bilifan.buyaoting.top/",
            "kwargs": {
                "reply_to": "om_123",
                "metadata": {"thread_id": "omt_thread", "reply_to_message_id": "om_123"},
            },
        }
    ]


def test_submit_intake_uses_token_and_api_url(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("BILIFAN_INTAKE_API_URL", "http://127.0.0.1:8792/api/intake/feishu")
    monkeypatch.setenv("BILIFAN_INTAKE_TOKEN", "local-token")
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return None

        def read(self):
            return b'{"ok": true, "accepted": [], "rejected": [], "duplicates": []}'

    def fake_urlopen(request, timeout):
        calls.append(
            {
                "url": request.full_url,
                "headers": dict(request.header_items()),
                "data": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return FakeResponse()

    monkeypatch.setattr(plugin.urllib.request, "urlopen", fake_urlopen)

    result = plugin._submit_intake({"source": "feishu", "urls": ["u1"]})

    assert result["ok"] is True
    assert calls == [
        {
            "url": "http://127.0.0.1:8792/api/intake/feishu",
            "headers": {"Content-type": "application/json", "X-bilifan-token": "local-token"},
            "data": {"source": "feishu", "urls": ["u1"]},
            "timeout": 10,
        }
    ]


class FakeAdapter:
    def __init__(self):
        self.sent: list[dict[str, object]] = []

    async def send(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeGateway:
    def __init__(self):
        self.adapters = {"feishu": FakeAdapter()}
```

- [ ] **Step 2: Run behavior tests to verify they fail**

Run:

```bash
uv run pytest tests/test_hermes_bilifan_intake_plugin.py -q
```

Expected: FAIL because hook, submit, and send functions are not implemented yet.

- [ ] **Step 3: Implement hook, submit, acknowledgement, and registration**

Append this implementation to `.hermes/plugins/bilifan_intake/__init__.py`:

```python
@dataclass(frozen=True)
class Settings:
    profile: str
    api_url: str
    token: str
    task_center_url: str
    timeout_seconds: int = 10


def _settings() -> Settings:
    token = (
        os.environ.get("BILIFAN_INTAKE_TOKEN")
        or os.environ.get("BILIFAN_WEB_TOKEN")
        or ""
    ).strip()
    return Settings(
        profile=(os.environ.get("BILIFAN_INTAKE_PROFILE") or DEFAULT_PROFILE).strip(),
        api_url=(os.environ.get("BILIFAN_INTAKE_API_URL") or DEFAULT_API_URL).strip(),
        token=token,
        task_center_url=(os.environ.get("BILIFAN_TASK_CENTER_URL") or DEFAULT_TASK_CENTER_URL).strip(),
    )


def _active_profile_name() -> str:
    return (
        os.environ.get("HERMES_PROFILE")
        or os.environ.get("HERMES_ACTIVE_PROFILE")
        or ""
    ).strip()


def _should_intercept(event: Any, settings: Settings) -> bool:
    active_profile = _active_profile_name()
    if active_profile and active_profile != settings.profile:
        return False
    return _platform_value(event) == "feishu"


def _submit_intake(payload: dict[str, Any]) -> dict[str, Any]:
    settings = _settings()
    if not settings.token:
        raise RuntimeError("BILIFAN_INTAKE_TOKEN or BILIFAN_WEB_TOKEN is required.")

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        settings.api_url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Bilifan-Token": settings.token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=settings.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Bilifan intake rejected the request: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Bilifan intake API is not reachable: {exc.reason}") from exc


def _ack_text(result: dict[str, Any]) -> str:
    accepted_count = len(result.get("accepted") or [])
    rejected_count = len(result.get("rejected") or [])
    duplicate_count = len(result.get("duplicates") or [])
    total = accepted_count + rejected_count + duplicate_count
    parts = [f"已收到 {total} 个链接：{accepted_count} 个已入队"]
    if rejected_count:
        parts.append(f"{rejected_count} 个不支持")
    if duplicate_count:
        parts.append(f"{duplicate_count} 个重复")
    return f"{'，'.join(parts)}。\\n任务中心：{_settings().task_center_url}"


def _failure_text(error: Exception) -> str:
    return f"Bilifan 暂时接收失败：{error}"


async def _send_text(event: Any, gateway: Any, text: str) -> None:
    source = getattr(event, "source", None)
    adapter = gateway.adapters.get("feishu")
    kwargs = {
        "reply_to": getattr(event, "message_id", None),
        "metadata": {
            "thread_id": getattr(source, "thread_id", None),
            "reply_to_message_id": getattr(event, "message_id", None),
        },
    }
    await adapter.send(getattr(source, "chat_id", None), text, **kwargs)


async def _send_ack(event: Any, gateway: Any, result: dict[str, Any]) -> None:
    await _send_text(event, gateway, _ack_text(result))


async def _process_intake(event: Any, gateway: Any, urls: list[str]) -> None:
    try:
        payload = _build_payload(event, urls)
        result = await asyncio.to_thread(_submit_intake, payload)
        await _send_ack(event, gateway, result)
    except Exception as exc:
        await _send_text(event, gateway, _failure_text(exc))


def handle_pre_gateway_dispatch(event: Any, gateway: Any = None, **kwargs) -> dict[str, str]:
    settings = _settings()
    if not _should_intercept(event, settings):
        return {"action": "allow"}

    urls = _extract_urls(getattr(event, "text", "") or "")
    if not urls:
        return {"action": "allow"}

    loop = asyncio.get_running_loop()
    loop.create_task(_process_intake(event, gateway, urls))
    return {"action": "skip", "reason": "bilifan_intake"}


def register(ctx) -> None:
    ctx.register_hook("pre_gateway_dispatch", handle_pre_gateway_dispatch)
```

- [ ] **Step 4: Run plugin tests**

Run:

```bash
uv run pytest tests/test_hermes_bilifan_intake_plugin.py -q
```

Expected: all tests PASS.

## Task 5: Documentation Note

**Files:**

- Modify: `docs/nabaichuan-integration.md`

- [ ] **Step 1: Add a Bilifan/Hermes boundary note**

Append:

```markdown
## Bilifan Feishu Runtime Boundary

Bilifan follows the same Hermes-owned Feishu runtime pattern as the Nabaichuan integration, but it does not write to Nabaichuan and does not copy Nabaichuan's archive workflow.

For Bilifan, Hermes owns the Feishu app, profile, credentials, gateway hook, and outbound chat replies. Bilifan owns only the local intake API, queue, processing state, and Web UI task center.
```

- [ ] **Step 2: Confirm docs mention the boundary**

Run:

```bash
rg -n "Bilifan Feishu Runtime Boundary|Hermes owns the Feishu app" docs/nabaichuan-integration.md
```

Expected: both phrases are found.

## Task 6: Focused Verification Before Runtime Changes

**Files:**

- No new files.

- [ ] **Step 1: Run the P2 focused tests**

Run:

```bash
uv run pytest tests/test_cli.py::test_serve_prints_url_and_starts_uvicorn tests/test_cli.py::test_serve_uses_bilifan_web_token_from_env tests/test_cli.py::test_serve_rejects_blank_bilifan_web_token tests/test_hermes_bilifan_intake_plugin.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 2: Run P1 intake regression tests**

Run:

```bash
uv run pytest tests/test_web_jobs.py tests/test_queue.py -q
```

Expected: all selected tests PASS.

- [ ] **Step 3: Check current worktree before runtime activation**

Run:

```bash
git status --short
```

Expected: P2 files are visible; unrelated pre-existing dirty files are not reverted.

## Task 7: Runtime Profile Activation After Confirmation

**Files outside Bilifan workspace, requires explicit confirmation and escalated write permission:**

- Create or modify: `/Users/jack/.hermes/profiles/bilifan/profile.yaml`
- Create or modify: `/Users/jack/.hermes/profiles/bilifan/config.yaml`
- Create or modify: `/Users/jack/.hermes/profiles/bilifan/SOUL.md`
- Create or modify: `/Users/jack/.hermes/profiles/bilifan/.env`

- [ ] **Step 1: Confirm profile credential branch**

Use exactly one of these branches:

Branch A, recommended fresh Bilifan profile:

```bash
hermes profile create bilifan
```

Then set Bilifan-specific Feishu credentials through the Hermes configuration UI or the operator's existing secret-management flow. Do not paste Feishu secrets into chat logs.

Branch B, fast clone from Nabaichuan:

```bash
hermes profile create bilifan --clone-from nabaichuan
```

This copies `config.yaml`, `.env`, `SOUL.md`, and profile-local skills from `nabaichuan`. Treat it as reusing the Nabaichuan Feishu app identity until the `.env` is replaced.

- [ ] **Step 2: Configure Bilifan profile runtime**

Update `/Users/jack/.hermes/profiles/bilifan/profile.yaml` description to:

```yaml
description: "Bilifan 视频链接处理、任务入队和飞书回执专用 Hermes profile。"
description_auto: false
```

Update `/Users/jack/.hermes/profiles/bilifan/config.yaml`:

```yaml
terminal:
  cwd: /Volumes/mySSD/projects/bilifan
plugins:
  enabled:
    - image_gen/openai-codex
    - bilifan_intake
  disabled: []
```

When editing the real file, preserve all unrelated existing config keys.

- [ ] **Step 3: Set Bilifan integration environment**

Generate one local token:

```bash
export BILIFAN_GENERATED_LOCAL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Add these keys to `/Users/jack/.hermes/profiles/bilifan/.env` without printing values in logs. `BILIFAN_WEB_TOKEN` and `BILIFAN_INTAKE_TOKEN` must receive the same generated value:

```bash
python3 - <<'PY'
from pathlib import Path
import os

env_path = Path("/Users/jack/.hermes/profiles/bilifan/.env")
token = os.environ["BILIFAN_GENERATED_LOCAL_TOKEN"]
updates = {
    "HERMES_ENABLE_PROJECT_PLUGINS": "1",
    "BILIFAN_WEB_TOKEN": token,
    "BILIFAN_INTAKE_TOKEN": token,
    "BILIFAN_INTAKE_API_URL": "http://127.0.0.1:8792/api/intake/feishu",
    "BILIFAN_TASK_CENTER_URL": "https://bilifan.buyaoting.top/",
    "BILIFAN_INTAKE_PROFILE": "bilifan",
}

existing_lines = env_path.read_text().splitlines() if env_path.exists() else []
seen = set()
next_lines = []
for line in existing_lines:
    key = line.split("=", 1)[0].strip() if "=" in line else ""
    if key in updates:
        next_lines.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        next_lines.append(line)
for key, value in updates.items():
    if key not in seen:
        next_lines.append(f"{key}={value}")
env_path.write_text("\n".join(next_lines) + "\n")
print("updated bilifan profile env keys")
PY
```

If using Branch A, also configure Bilifan's own Feishu app keys in this same profile `.env` through the Hermes secret flow. If using Branch B, verify only the key names exist and never print their values.

- [ ] **Step 4: Write a Bilifan-specific SOUL**

Update `/Users/jack/.hermes/profiles/bilifan/SOUL.md` with a Bilifan-specific boundary:

```markdown
# Bilifan Hermes Profile

You are the Feishu-facing runtime profile for Bilifan.

You receive Feishu messages that contain video links, route supported links into the local Bilifan intake API, and send concise acknowledgements back to the same Feishu conversation. Bilifan's Web UI task center is the processing source of truth.

Hard boundaries:

- Do not store or expose Feishu app credentials inside Bilifan job files.
- Do not write to Nabaichuan.
- Do not change Hermes profiles, `.env`, gateway settings, memory, allowlists, or external accounts unless the operator explicitly confirms the exact change.
- Do not send proactive Feishu messages unless the operator confirms the exact target and body.
```

- [ ] **Step 5: Restart only the Bilifan services**

Restart Bilifan web after the stable token is in the environment:

```bash
scripts/bilifan-remote.sh restart
scripts/bilifan-remote.sh status
```

Start or restart only the Bilifan Hermes gateway:

```bash
hermes -p bilifan gateway status
hermes -p bilifan gateway restart
hermes -p bilifan gateway status
```

Expected:

- Bilifan local API is reachable at `http://127.0.0.1:8792/`.
- Public URL remains `https://bilifan.buyaoting.top`.
- Hermes gateway status is running for profile `bilifan`.
- No Nabaichuan gateway restart occurs.

## Task 8: Real Feishu Smoke After Runtime Activation

**Files:**

- No file changes.

- [ ] **Step 1: Operator-sent smoke, recommended**

The operator sends this exact kind of message to the dedicated Bilifan Feishu app:

```text
https://www.bilibili.com/video/BV1xx411c7mD
https://youtu.be/dQw4w9WgXcQ
```

Then verify:

```bash
scripts/bilifan-remote.sh status
```

Call Bilifan queue API with the local token from the profile environment, without printing the token:

```bash
python3 - <<'PY'
import json
import os
import urllib.request

token = os.environ["BILIFAN_WEB_TOKEN"]
request = urllib.request.Request(
    "http://127.0.0.1:8792/api/jobs/queue",
    headers={"X-Bilifan-Token": token},
)
with urllib.request.urlopen(request, timeout=10) as response:
    data = json.loads(response.read().decode("utf-8"))

jobs = data.get("jobs", [])
feishu_jobs = [job for job in jobs if (job.get("origin") or {}).get("source") == "feishu"]
print(json.dumps({"feishu_jobs": len(feishu_jobs)}, ensure_ascii=False))
PY
```

Expected:

- Feishu receives one acknowledgement with accepted/rejected/duplicate counts.
- Bilifan Web UI task center shows accepted jobs with `来自飞书`.
- Queue API reports at least one Feishu-origin job.

- [ ] **Step 2: Agent-sent smoke, only if explicitly confirmed**

If the operator wants Codex/Hermes to send the test message, collect the exact chat/thread target and exact message body immediately before sending. Do not send a generic test message to a default channel.

## Rollback

- Stop the Bilifan Hermes gateway only:

```bash
hermes -p bilifan gateway stop
```

- Disable the Bilifan project plugin by removing `bilifan_intake` from `/Users/jack/.hermes/profiles/bilifan/config.yaml` `plugins.enabled`.
- Restart the Bilifan gateway after disabling:

```bash
hermes -p bilifan gateway restart
```

- If the stable token causes access problems, remove `BILIFAN_WEB_TOKEN` and `BILIFAN_INTAKE_TOKEN` from the Bilifan profile `.env`, restart Bilifan web, and use the generated-token browser flow again.

## Acceptance

- `BILIFAN_WEB_TOKEN` lets Hermes use a stable local token without changing browser fallback behavior.
- A Feishu message with multiple URLs creates one Bilifan intake batch and one immediate acknowledgement.
- Messages without URLs still go through normal Hermes handling.
- Other Hermes profiles do not intercept Bilifan intake messages.
- No Feishu credentials are stored in Bilifan jobs.
- Runtime activation touches only the dedicated `bilifan` profile after confirmation.
- Real smoke proves the task appears in Bilifan Web UI and Feishu receives the immediate acknowledgement.
