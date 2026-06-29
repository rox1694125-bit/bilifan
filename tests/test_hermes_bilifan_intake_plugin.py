from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path


PLUGIN_PATH = (
    Path(__file__).resolve().parents[1]
    / ".hermes"
    / "plugins"
    / "bilifan_intake"
    / "__init__.py"
)


def load_plugin():
    spec = importlib.util.spec_from_file_location(
        "bilifan_intake_test_plugin",
        PLUGIN_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
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

    payload = plugin._build_payload(
        event,
        ["https://www.bilibili.com/video/BV1xx411c7mD"],
    )

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


def test_hook_allows_non_feishu_messages(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "bilifan")
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("telegram"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {
        "action": "allow",
    }


def test_hook_allows_other_profiles(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "nabaichuan")
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {
        "action": "allow",
    }


def test_hook_allows_other_source_profiles_without_env(monkeypatch):
    plugin = load_plugin()
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_ACTIVE_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(
            platform=FakePlatform("feishu"),
            chat_id="chat",
            profile="nabaichuan",
        ),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {
        "action": "allow",
    }


def test_hook_uses_hermes_home_profile_when_env_profile_is_absent(
    monkeypatch,
    tmp_path,
):
    plugin = load_plugin()
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_ACTIVE_PROFILE", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes" / "profiles" / "bilifan"))
    submitted: list[list[str]] = []

    async def fake_process(event, gateway, urls):
        submitted.append(urls)

    monkeypatch.setattr(plugin, "_process_intake", fake_process)
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    async def run():
        result = plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway())
        await asyncio.sleep(0)
        return result

    assert asyncio.run(run()) == {"action": "skip", "reason": "bilifan_intake"}
    assert submitted == [["https://www.bilibili.com/video/BV1xx411c7mD"]]


def test_hook_allows_when_profile_context_is_missing(monkeypatch):
    plugin = load_plugin()
    monkeypatch.delenv("HERMES_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_ACTIVE_PROFILE", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {
        "action": "allow",
    }


def test_hook_allows_feishu_messages_without_urls(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("HERMES_PROFILE", "bilifan")
    event = FakeEvent(
        text="hello",
        message_id="om_123",
        source=FakeSource(platform=FakePlatform("feishu"), chat_id="chat"),
    )

    assert plugin.handle_pre_gateway_dispatch(event=event, gateway=FakeGateway()) == {
        "action": "allow",
    }


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
        text=(
            "https://www.bilibili.com/video/BV1xx411c7mD "
            "https://youtu.be/dQw4w9WgXcQ"
        ),
        message_id="om_123",
        source=FakeSource(
            platform=FakePlatform("feishu"),
            chat_id="oc_chat",
            thread_id="omt_thread",
        ),
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
            "text": (
                "已收到 3 个链接：1 个已入队，1 个不支持，1 个重复。\n"
                "任务中心：https://bilifan.buyaoting.top/"
            ),
            "kwargs": {
                "reply_to": "om_123",
                "metadata": {
                    "thread_id": "omt_thread",
                    "reply_to_message_id": "om_123",
                },
            },
        },
    ]


def test_send_ack_uses_enum_like_feishu_adapter_key(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv("BILIFAN_TASK_CENTER_URL", "https://bilifan.buyaoting.top/")
    event = FakeEvent(
        text="https://www.bilibili.com/video/BV1xx411c7mD",
        message_id="om_123",
        source=FakeSource(
            platform=FakePlatform("feishu"),
            chat_id="oc_chat",
            thread_id="omt_thread",
        ),
    )
    gateway = FakeGateway(adapter_key=FakePlatform("feishu"))

    asyncio.run(
        plugin._send_ack(
            event,
            gateway,
            {"ok": True, "accepted": [], "rejected": [], "duplicates": []},
        )
    )

    adapter = next(iter(gateway.adapters.values()))
    assert adapter.sent == [
        {
            "chat_id": "oc_chat",
            "text": "已收到 0 个链接：0 个已入队。\n任务中心：https://bilifan.buyaoting.top/",
            "kwargs": {
                "reply_to": "om_123",
                "metadata": {
                    "thread_id": "omt_thread",
                    "reply_to_message_id": "om_123",
                },
            },
        },
    ]


def test_submit_intake_uses_token_and_api_url(monkeypatch):
    plugin = load_plugin()
    monkeypatch.setenv(
        "BILIFAN_INTAKE_API_URL",
        "http://127.0.0.1:8792/api/intake/feishu",
    )
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
            "headers": {
                "Content-type": "application/json",
                "X-bilifan-token": "local-token",
            },
            "data": {"source": "feishu", "urls": ["u1"]},
            "timeout": 10,
        },
    ]


class FakePlatform:
    def __init__(self, value: str):
        self.value = value


class FakeSource:
    def __init__(
        self,
        *,
        platform,
        chat_id,
        thread_id=None,
        user_name=None,
        profile=None,
    ):
        self.platform = platform
        self.chat_id = chat_id
        self.thread_id = thread_id
        self.user_name = user_name
        self.profile = profile


class FakeEvent:
    def __init__(self, *, text, message_id, source):
        self.text = text
        self.message_id = message_id
        self.source = source


class FakeAdapter:
    def __init__(self):
        self.sent: list[dict[str, object]] = []

    async def send(self, chat_id, text, **kwargs):
        self.sent.append({"chat_id": chat_id, "text": text, "kwargs": kwargs})


class FakeGateway:
    def __init__(self, adapter_key="feishu"):
        self.adapters = {adapter_key: FakeAdapter()}
