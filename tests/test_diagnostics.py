import json
from pathlib import Path

import pytest

from bilifan.diagnostics import (
    Diagnostics,
    redact_text,
    validate_artifact_paths,
    write_diagnostics,
)


def test_redact_text_removes_sensitive_values_and_canonicalizes_bilibili_urls():
    raw = "\n".join(
        [
            "cookie_file=/Users/jack/.config/bilifan/cookies.txt",
            "load cookies from /Users/jack/Downloads/bili-cookies.txt",
            "CODEX_ACCESS_TOKEN=codex-access-secret",
            "OPENAI_API_KEY=openai-secret",
            "CODEX_API_KEY: codex-api-secret",
            "Authorization: Bearer sk-live-secret",
            "api_key=sk-proj-openai-secret",
            "jwt=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature",
            (
                "Cookie: SESSDATA=session-secret; bili_jct=csrf-secret; "
                "DedeUserID=123456; buvid3=buvid-secret; sid=sid-secret; "
                "b_nut=nut-secret; _uuid=uuid-secret; CURRENT_FNVAL=fnval-secret"
            ),
            "trace=/Users/alice/project/log.txt",
            "output=/Volumes/mySSD/projects/bilifan/out",
            "cache=/Volumes/external/cache/file.txt",
            "shell=~/Downloads/raw.txt",
            "extra=/private/workspace/secret.txt",
            (
                "url=https://www.bilibili.com/video/BV1abcDEF12G/"
                "?p=2&spm_id_from=333.999&vd_source=tracking-secret"
            ),
        ]
    )

    redacted = redact_text(
        raw,
        home_markers=[Path("/private/workspace")],
    )

    assert "/Users/jack" not in redacted
    assert "/Users/alice" not in redacted
    assert "/Volumes/mySSD" not in redacted
    assert "/Volumes/external" not in redacted
    assert "~/Downloads" not in redacted
    assert "/private/workspace" not in redacted
    assert "cookies.txt" not in redacted
    assert "bili-cookies.txt" not in redacted
    assert "codex-access-secret" not in redacted
    assert "openai-secret" not in redacted
    assert "codex-api-secret" not in redacted
    assert "sk-live-secret" not in redacted
    assert "sk-proj-openai-secret" not in redacted
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert "session-secret" not in redacted
    assert "csrf-secret" not in redacted
    assert "123456" not in redacted
    assert "buvid-secret" not in redacted
    assert "sid-secret" not in redacted
    assert "nut-secret" not in redacted
    assert "uuid-secret" not in redacted
    assert "fnval-secret" not in redacted
    assert "spm_id_from" not in redacted
    assert "vd_source" not in redacted
    assert "CODEX_ACCESS_TOKEN=<redacted>" in redacted
    assert "OPENAI_API_KEY=<redacted>" in redacted
    assert "CODEX_API_KEY: <redacted>" in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "SESSDATA=<redacted>" in redacted
    assert "bili_jct=<redacted>" in redacted
    assert "DedeUserID=<redacted>" in redacted
    assert "buvid3=<redacted>" in redacted
    assert "sid=<redacted>" in redacted
    assert "b_nut=<redacted>" in redacted
    assert "_uuid=<redacted>" in redacted
    assert "CURRENT_FNVAL=<redacted>" in redacted
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2" in redacted


def test_redact_text_removes_bare_cookie_file_names_and_relative_paths():
    redacted = redact_text(
        "bili-cookies.txt ./bili-cookies.txt ../bili-cookies.txt "
        "/tmp/bili-cookies.txt C:\\Users\\jack\\cookies.txt cookies.txt "
        "--cookies-file /tmp/auth.txt cookies file /tmp/other-auth.txt"
    )

    assert "bili-cookies.txt" not in redacted
    assert "cookies.txt" not in redacted
    assert "auth.txt" not in redacted
    assert "other-auth.txt" not in redacted
    assert "/tmp" not in redacted
    assert "C:\\Users" not in redacted
    assert "./" not in redacted
    assert "../" not in redacted


def test_validate_artifact_paths_accepts_relative_posix_paths():
    assert validate_artifact_paths(["diagnostics.json", "assets/cover.jpg"]) == [
        "diagnostics.json",
        "assets/cover.jpg",
    ]


@pytest.mark.parametrize(
    "path",
    ["/tmp/report.html", "../report.html", "C:/Users/jack/report.html", "~/report.html"],
)
def test_validate_artifact_paths_rejects_paths_outside_run_dir(path):
    with pytest.raises(ValueError, match="artifact path"):
        validate_artifact_paths([path])


def test_validate_artifact_paths_rejects_non_list_container():
    with pytest.raises(ValueError, match="artifact paths"):
        validate_artifact_paths("diagnostics.json")  # type: ignore[arg-type]


def test_write_diagnostics_writes_only_sanitized_allowlisted_json(tmp_path):
    output_path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type="RuntimeError",
        exit_code=1,
        stage="download",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check={"status": "failed", "expected_seconds": 120.5},
        transcript_check=None,
        artifact_paths=["diagnostics.json", "assets/cover.jpg"],
        sanitized_message=(
            "CODEX_ACCESS_TOKEN=codex-access-secret "
            "Authorization: Bearer sk-live-secret "
            "https://www.bilibili.com/video/BV1abcDEF12G/?p=2"
            "&spm_id_from=333.999&vd_source=tracking-secret"
        ),
        warnings=["cookie_file=/Users/jack/.config/bilifan/cookies.txt"],
    )
    object.__setattr__(diagnostics, "unexpected_secret", "sk-not-allowlisted")

    write_diagnostics(output_path, diagnostics)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert list(data) == [
        "error_type",
        "exit_code",
        "stage",
        "video_id",
        "part_index",
        "duration_check",
        "transcript_check",
        "artifact_paths",
        "sanitized_message",
        "warnings",
    ]
    assert data["artifact_paths"] == ["diagnostics.json", "assets/cover.jpg"]
    assert data["duration_check"] == {"status": "failed", "expected_seconds": 120.5}
    assert data["transcript_check"] is None
    assert "CODEX_ACCESS_TOKEN=<redacted>" in data["sanitized_message"]
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2" in data["sanitized_message"]
    serialized = output_path.read_text(encoding="utf-8")
    assert "codex-access-secret" not in serialized
    assert "sk-live-secret" not in serialized
    assert "sk-not-allowlisted" not in serialized
    assert "spm_id_from" not in serialized
    assert "vd_source" not in serialized
    assert "/Users/jack" not in serialized


def test_write_diagnostics_rejects_unsafe_artifact_paths(tmp_path):
    output_path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type="RuntimeError",
        exit_code=1,
        stage="download",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check=None,
        transcript_check=None,
        artifact_paths=["../report.html"],
        sanitized_message="plain message",
        warnings=[],
    )

    with pytest.raises(ValueError, match="artifact path"):
        write_diagnostics(output_path, diagnostics)

    assert not output_path.exists()


def test_write_diagnostics_preserves_nullable_error_type_and_check_objects(tmp_path):
    output_path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type=None,
        exit_code=0,
        stage="complete",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check=None,
        transcript_check={"status": "ok", "segments": 42},
        artifact_paths=["diagnostics.json"],
        sanitized_message="ok",
        warnings=[],
    )

    write_diagnostics(output_path, diagnostics)

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["error_type"] is None
    assert data["duration_check"] is None
    assert data["transcript_check"] == {"status": "ok", "segments": 42}


def test_write_diagnostics_sanitizes_nested_keys_and_non_json_values(tmp_path):
    output_path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type=None,
        exit_code=0,
        stage="complete",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check={
            "CODEX_ACCESS_TOKEN=key-secret": Path("/Users/jack/raw.txt"),
            "Cookie: b_nut=nut-secret": ["ok", Path("/Volumes/mySSD/raw.txt")],
        },
        transcript_check={"set_value": {Path("/Users/jack/a.txt")}},
        artifact_paths=["diagnostics.json"],
        sanitized_message="ok",
        warnings=[],
    )

    write_diagnostics(output_path, diagnostics)

    serialized = output_path.read_text(encoding="utf-8")
    assert "key-secret" not in serialized
    assert "nut-secret" not in serialized
    assert "/Users/jack" not in serialized
    assert "/Volumes/mySSD" not in serialized

    data = json.loads(serialized)
    assert "CODEX_ACCESS_TOKEN=<redacted>" in data["duration_check"]
    assert "Cookie: b_nut=<redacted>" in data["duration_check"]
