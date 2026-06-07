from datetime import datetime, timezone
from stat import S_IMODE

import pytest

from bilifan.config import (
    ConsentConfig,
    NOTICE_VERSION,
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


def test_read_config_returns_default_for_malformed_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{", encoding="utf-8")

    config = read_config(config_path)

    assert config == ConsentConfig()


def test_read_config_returns_default_for_non_object_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("[]", encoding="utf-8")

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


def test_non_string_timestamp_does_not_count_as_local_processing_consent(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        (
            '{'
            f'"notice_version": "{NOTICE_VERSION}", '
            '"local_processing_notice_accepted_at": false'
            '}'
        ),
        encoding="utf-8",
    )

    config = read_config(config_path)

    assert config.local_processing_notice_accepted_at is None
    assert has_local_processing_consent(config_path) is False


def test_previous_notice_version_does_not_count_as_consent(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        (
            '{'
            '"notice_version": "2026-01-01", '
            '"local_processing_notice_accepted_at": "2026-06-08T01:15:30+00:00", '
            '"cookies_notice_accepted_at": "2026-06-08T01:16:00+00:00"'
            '}'
        ),
        encoding="utf-8",
    )

    config = read_config(config_path)

    assert config == ConsentConfig()
    assert has_local_processing_consent(config_path) is False
    assert has_cookies_consent(config_path) is False


def test_write_consent_rejects_invalid_accepted_via_without_writing_secret(tmp_path):
    config_path = tmp_path / "config" / "bilifan" / "config.json"
    now = datetime(2026, 6, 8, 1, 15, 30, tzinfo=timezone.utc)
    sensitive_value = "sk-test-sensitive-token"

    write_consent(config_path, local_processing=True, accepted_via="test", now=now)
    original_content = config_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="accepted_via"):
        write_consent(
            config_path,
            cookies=True,
            accepted_via=sensitive_value,
            now=now,
        )

    assert config_path.read_text(encoding="utf-8") == original_content
    assert sensitive_value not in config_path.read_text(encoding="utf-8")
