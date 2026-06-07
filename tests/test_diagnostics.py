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
            "CODEX_ACCESS_TOKEN=codex-access-secret",
            "Authorization: Bearer sk-live-secret",
            "api_key=sk-proj-openai-secret",
            "Cookie: SESSDATA=session-secret; bili_jct=csrf-secret; DedeUserID=123456",
            "output=/Volumes/mySSD/projects/bilifan/out",
            (
                "url=https://www.bilibili.com/video/BV1abcDEF12G/"
                "?p=2&spm_id_from=333.999&vd_source=tracking-secret"
            ),
        ]
    )

    redacted = redact_text(
        raw,
        home_markers=[Path("/Users/jack"), Path("/Volumes/mySSD")],
    )

    assert "/Users/jack" not in redacted
    assert "/Volumes/mySSD" not in redacted
    assert "cookies.txt" not in redacted
    assert "codex-access-secret" not in redacted
    assert "sk-live-secret" not in redacted
    assert "sk-proj-openai-secret" not in redacted
    assert "session-secret" not in redacted
    assert "csrf-secret" not in redacted
    assert "123456" not in redacted
    assert "spm_id_from" not in redacted
    assert "vd_source" not in redacted
    assert "CODEX_ACCESS_TOKEN=<redacted>" in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "SESSDATA=<redacted>" in redacted
    assert "bili_jct=<redacted>" in redacted
    assert "DedeUserID=<redacted>" in redacted
    assert "https://www.bilibili.com/video/BV1abcDEF12G?p=2" in redacted


def test_validate_artifact_paths_accepts_relative_posix_paths():
    assert validate_artifact_paths(["diagnostics.json", "assets/cover.jpg"]) == [
        "diagnostics.json",
        "assets/cover.jpg",
    ]


@pytest.mark.parametrize("path", ["/tmp/report.html", "../report.html"])
def test_validate_artifact_paths_rejects_paths_outside_run_dir(path):
    with pytest.raises(ValueError, match="artifact path"):
        validate_artifact_paths([path])


def test_write_diagnostics_writes_only_sanitized_allowlisted_json(tmp_path):
    output_path = tmp_path / "diagnostics.json"
    diagnostics = Diagnostics(
        error_type="RuntimeError",
        exit_code=1,
        stage="download",
        video_id="BV1abcDEF12G",
        part_index=2,
        duration_check="not-run",
        transcript_check="not-run",
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
        duration_check="not-run",
        transcript_check="not-run",
        artifact_paths=["../report.html"],
        sanitized_message="plain message",
        warnings=[],
    )

    with pytest.raises(ValueError, match="artifact path"):
        write_diagnostics(output_path, diagnostics)

    assert not output_path.exists()
