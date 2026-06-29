from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
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
    return _named_value(platform)


def _named_value(value: Any) -> str:
    raw_value = getattr(value, "value", value)
    if raw_value is value and not isinstance(value, str):
        name = str(getattr(value, "name", "") or "").strip().lower()
        if name:
            return name
    text = str(raw_value or "").strip()
    if text:
        return text
    return str(getattr(value, "name", "") or "").strip().lower()


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
        task_center_url=(
            os.environ.get("BILIFAN_TASK_CENTER_URL") or DEFAULT_TASK_CENTER_URL
        ).strip(),
    )


def _event_profile_name(event: Any) -> str:
    source = getattr(event, "source", None)
    for attr in ("profile", "profile_name"):
        value = _named_value(getattr(source, attr, None))
        if value:
            return value
    return ""


def _profile_name_from_hermes_home(value: str | None) -> str:
    if not value:
        return ""
    path = Path(value).expanduser().resolve()
    if path.name == ".hermes":
        return "default"
    if len(path.parts) >= 2 and path.parts[-2] == "profiles":
        return path.name
    return ""


def _active_profile_name(event: Any) -> str:
    event_profile = _event_profile_name(event)
    if event_profile:
        return event_profile
    env_profile = (
        os.environ.get("HERMES_PROFILE")
        or os.environ.get("HERMES_ACTIVE_PROFILE")
        or ""
    ).strip()
    if env_profile:
        return env_profile
    return _profile_name_from_hermes_home(os.environ.get("HERMES_HOME"))


def _should_intercept(event: Any, settings: Settings) -> bool:
    active_profile = _active_profile_name(event)
    if active_profile != settings.profile:
        return False
    return _platform_value(event) == "feishu"


def _feishu_adapter(gateway: Any) -> Any:
    adapters = getattr(gateway, "adapters", {}) or {}
    adapter = adapters.get("feishu")
    if adapter is not None:
        return adapter
    for platform, candidate in adapters.items():
        if _named_value(platform) == "feishu":
            return candidate
    raise RuntimeError("Feishu adapter is not available on this gateway.")


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
        raise RuntimeError(
            f"Bilifan intake rejected the request: HTTP {exc.code} {detail}"
        ) from exc
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
    return f"{'，'.join(parts)}。\n任务中心：{_settings().task_center_url}"


def _failure_text(error: Exception) -> str:
    return f"Bilifan 暂时接收失败：{error}"


async def _send_text(event: Any, gateway: Any, text: str) -> None:
    source = getattr(event, "source", None)
    adapter = _feishu_adapter(gateway)
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
        try:
            await _send_text(event, gateway, _failure_text(exc))
        except Exception:
            pass


def handle_pre_gateway_dispatch(
    event: Any,
    gateway: Any = None,
    **kwargs,
) -> dict[str, str]:
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
