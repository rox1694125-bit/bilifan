from datetime import datetime, timezone
from stat import S_IMODE

from bilifan.config import (
    ConsentConfig,
    default_config_path,
    has_cookies_consent,
    has_local_processing_consent,
    read_config,
    write_consent,
)


def test_read_config_returns_default_when_missing(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"

    config = read_config(config_path)

    assert config == ConsentConfig()


def test_default_config_path_uses_bilifan_config_home(tmp_path):
    config_path = default_config_path(env={"BILIFAN_CONFIG_HOME": str(tmp_path)})

    assert config_path == tmp_path / "config.json"


def test_write_local_processing_consent_persists_only_local_notice(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)

    write_consent(config_path, local_processing=True, accepted_via="test", now=now)

    config = read_config(config_path)
    assert has_local_processing_consent(config_path) is True
    assert has_cookies_consent(config_path) is False
    assert config.local_processing_notice_accepted_at == "2026-06-08T01:15:30+00:00"
    assert config.cookies_notice_accepted_at is None
    assert config.accepted_via == "test"
    assert S_IMODE(config_path.stat().st_mode) == 0o600


def test_write_cookies_consent_preserves_existing_local_notice(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"
    first = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    second = datetime(2026, 6, 8, 1, 16, 0, tzinfo=timezone.utc)

    write_consent(config_path, local_processing=True, accepted_via="test", now=first)
    write_consent(config_path, cookies=True, accepted_via="test", now=second)

    config = read_config(config_path)
    assert config.local_processing_notice_accepted_at == "2026-06-08T01:15:30+00:00"
    assert config.cookies_notice_accepted_at == "2026-06-08T01:16:00+00:00"
