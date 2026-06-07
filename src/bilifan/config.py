from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Mapping

NOTICE_VERSION = "2026-06-08"


@dataclass(frozen=True)
class ConsentConfig:
    schema_version: int = 1
    notice_version: str = NOTICE_VERSION
    local_processing_notice_accepted_at: str | None = None
    cookies_notice_accepted_at: str | None = None
    accepted_via: str | None = None


def default_config_path(
    *,
    env: Mapping[str, str] | None = None,
    home: str | PathLike[str] | None = None,
) -> Path:
    env_map = os.environ if env is None else env
    if env_map.get("BILIFAN_CONFIG_HOME"):
        return Path(env_map["BILIFAN_CONFIG_HOME"]) / "config.json"
    if env_map.get("XDG_CONFIG_HOME"):
        return Path(env_map["XDG_CONFIG_HOME"]) / "bilifan" / "config.json"
    home_dir = Path(home) if home is not None else Path.home()
    return home_dir / ".config" / "bilifan" / "config.json"


def read_config(path: Path) -> ConsentConfig:
    if not path.exists():
        return ConsentConfig()

    data = json.loads(path.read_text(encoding="utf-8"))
    return ConsentConfig(
        schema_version=int(data.get("schema_version", 1)),
        notice_version=str(data.get("notice_version", NOTICE_VERSION)),
        local_processing_notice_accepted_at=data.get(
            "local_processing_notice_accepted_at"
        ),
        cookies_notice_accepted_at=data.get("cookies_notice_accepted_at"),
        accepted_via=data.get("accepted_via"),
    )


def has_local_processing_consent(path: Path) -> bool:
    return read_config(path).local_processing_notice_accepted_at is not None


def has_cookies_consent(path: Path) -> bool:
    return read_config(path).cookies_notice_accepted_at is not None


def write_consent(
    path: Path,
    *,
    local_processing: bool = False,
    cookies: bool = False,
    accepted_via: str = "cli",
    now: datetime | None = None,
) -> None:
    current = read_config(path)
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)

    local_accepted_at = current.local_processing_notice_accepted_at
    cookies_accepted_at = current.cookies_notice_accepted_at
    if local_processing and local_accepted_at is None:
        local_accepted_at = timestamp
    if cookies and cookies_accepted_at is None:
        cookies_accepted_at = timestamp

    data = {
        "schema_version": 1,
        "notice_version": NOTICE_VERSION,
        "local_processing_notice_accepted_at": local_accepted_at,
        "cookies_notice_accepted_at": cookies_accepted_at,
        "accepted_via": accepted_via,
    }
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
