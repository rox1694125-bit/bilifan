import json

from typer.testing import CliRunner

import bilifan.cli as cli
from bilifan.cli import app
from bilifan.media import MediaDownloadError
from bilifan.metadata import MetadataIngestError


runner = CliRunner()
URL = "https://www.bilibili.com/video/BV1abcDEF12G?p=2&spm_id_from=333.999"
REAL_BILIBILI_URLS = [
    (
        "https://www.bilibili.com/video/BV14kVE6eEtC"
        "?spm_id_from=333.788.player.player_end_recommend"
        "&vd_source=39fc5b438dea96faea88e7841fb3d0ca"
        "&trackid=web_related_0.router-related-2589621-kz84p.1780846547972.446",
        "BV14kVE6eEtC_p1",
    ),
    (
        "https://www.bilibili.com/video/BV1xuVC6AEbg/?spm_id_from=333.1391.0.0",
        "BV1xuVC6AEbg_p1",
    ),
    (
        "https://www.bilibili.com/video/BV1ETEF6VEHu/?spm_id_from=333.1391.0.0",
        "BV1ETEF6VEHu_p1",
    ),
]


def _install_fake_metadata_fetch(monkeypatch, *, title="Mock metadata title"):
    calls = []

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        calls.append(
            {
                "ref": ref,
                "run_dir": run_dir,
                "cookies_from_browser": cookies_from_browser,
                "cookies_file": cookies_file,
            }
        )
        return {
            "bilifan_version": "0.1.0",
            "generated_at": "2026-06-08T00:00:00+00:00",
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": "123456",
            "title": title,
            "part_title": title,
            "owner_name": "Mock Owner",
            "description": "",
            "tags": [],
            "cover_url": "",
            "cover_path": "",
            "duration": 0,
            "parts": [],
            "subtitles": [],
            "yt_dlp_version": "mock",
            "ffmpeg_version": "",
        }

    monkeypatch.setattr(cli, "fetch_current_part_metadata", fake_fetch_current_part_metadata)
    return calls


def _install_fake_audio_download(monkeypatch, *, duration_seconds=0):
    calls = []

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        calls.append(
            {
                "ref": ref,
                "metadata": metadata,
                "run_dir": run_dir,
                "cookies_from_browser": cookies_from_browser,
                "cookies_file": cookies_file,
            }
        )
        audio_path = f".bilifan/cache/{ref.output_id}.mp3"
        (run_dir / audio_path).parent.mkdir(parents=True, exist_ok=True)
        (run_dir / audio_path).write_bytes(b"audio")
        return {
            "audio_path": audio_path,
            "duration_seconds": duration_seconds,
            "duration_check": {
                "status": "ok",
                "metadata_seconds": metadata.get("duration"),
                "audio_seconds": duration_seconds,
                "difference_ratio": 0,
                "tolerance_ratio": 0.05,
                "attempts": 1,
            },
        }

    monkeypatch.setattr(cli, "download_current_part_audio", fake_download_current_part_audio)
    return calls


def test_cli_help_lists_summarize_command():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "summarize" in result.output


def test_summarize_declines_local_processing_consent_without_writing_config(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        ["summarize", URL, "--out", str(outputs)],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "local processing consent" in result.output
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_writes_metadata_json_with_yes_flag(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch, title="CLI metadata title")
    _install_fake_audio_download(monkeypatch)

    result = runner.invoke(
        app,
        ["summarize", URL, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "Prepared Bilifan run:" in result.output
    assert "BV1abcDEF12G_p2/runs/" in result.output
    assert str(outputs) not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))
    metadata = json.loads((run_dir / "metadata.json").read_text(encoding="utf-8"))

    assert run_dir.is_dir()
    assert diagnostics["error_type"] is None
    assert diagnostics["exit_code"] == 0
    assert diagnostics["stage"] == "media"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["duration_check"]["status"] == "ok"
    assert diagnostics["transcript_check"] is None
    assert diagnostics["artifact_paths"] == [
        "diagnostics.json",
        "metadata.json",
        ".bilifan/cache/BV1abcDEF12G_p2.mp3",
    ]
    assert diagnostics["warnings"] == ["media_only"]
    assert metadata["input_url_sanitized"] == (
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2"
    )
    assert metadata["video_id"] == "BV1abcDEF12G"
    assert metadata["part_index"] == 2
    assert metadata["title"] == "CLI metadata title"
    assert (config_home / "config.json").exists()


def test_summarize_accepts_mvp_public_flags_before_later_stages(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--format",
            "html,pdf",
            "--transcriber",
            "auto",
            "--force-whisper",
            "--llm-provider",
            "codex-exec",
            "--llm-model",
            "gpt-5.5",
            "--require-pdf",
            "--allow-long-video",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    assert "No such option" not in result.output
    assert "Prepared Bilifan run:" in result.output


def test_summarize_prepares_runs_for_real_bilibili_urls(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)

    for url, output_id in REAL_BILIBILI_URLS:
        result = runner.invoke(
            app,
            ["summarize", url, "--yes-i-understand", "--out", str(outputs)],
            env={"BILIFAN_CONFIG_HOME": str(config_home)},
        )

        assert result.exit_code == 0
        assert f"{output_id}/runs/" in result.output
        assert "spm_id_from" not in result.output
        assert "vd_source" not in result.output
        assert "trackid" not in result.output

        video_dir = outputs / output_id
        latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
        diagnostics_path = video_dir / latest["run_dir"] / "diagnostics.json"
        diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8"))
        bvid, part = output_id.rsplit("_p", 1)

        assert latest["input_url_sanitized"] == (
            f"https://www.bilibili.com/video/{bvid}?p={part}"
        )
        assert diagnostics["video_id"] == bvid
        assert diagnostics["part_index"] == int(part)
        assert diagnostics["stage"] == "media"


def test_summarize_records_cookie_notice_without_storing_cookie_file_name(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    calls = _install_fake_metadata_fetch(monkeypatch)
    _install_fake_audio_download(monkeypatch)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 0
    config_text = (config_home / "config.json").read_text(encoding="utf-8")
    assert "local_processing_notice_accepted_at" in config_text
    assert "cookies_notice_accepted_at" in config_text
    assert "bili-cookies.txt" not in config_text
    assert "/Users/jack" not in config_text
    assert calls[0]["cookies_file"].as_posix() == "/Users/jack/Downloads/bili-cookies.txt"
    assert "bili-cookies.txt" not in result.output
    assert "/Users/jack" not in result.output


def test_summarize_invalid_url_writes_sanitized_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    invalid_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G/extra"
        "?p=2&vd_source=tracking-secret"
    )

    result = runner.invoke(
        app,
        ["summarize", invalid_url, "--yes-i-understand", "--out", str(outputs)],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    error_runs = list((outputs / "_errors" / "runs").iterdir())
    assert len(error_runs) == 1

    diagnostics = json.loads(
        (error_runs[0] / "diagnostics.json").read_text(encoding="utf-8")
    )
    assert diagnostics["error_type"] == "InputError"
    assert diagnostics["exit_code"] == 2
    assert diagnostics["stage"] == "preflight"
    assert diagnostics["video_id"] == ""
    assert diagnostics["part_index"] == 0
    assert "vd_source" not in diagnostics["sanitized_message"]


def test_summarize_invalid_url_requires_consent_before_writing_error_run(tmp_path):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--out",
            str(outputs),
        ],
        input="n\n",
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "Continue?" in result.output
    assert not (config_home / "config.json").exists()
    assert not outputs.exists()


def test_summarize_invalid_url_retries_error_run_collision_without_leaking_path(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    original_create_error_run = cli.create_error_run
    calls = 0

    def fake_create_error_run(out_dir, *, now=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise FileExistsError("/Users/jack/outputs/_errors/runs/collision")
        return original_create_error_run(out_dir, now=now)

    monkeypatch.setattr(cli, "create_error_run", fake_create_error_run)

    result = runner.invoke(
        app,
        [
            "summarize",
            "https://example.com/nope?vd_source=tracking-secret",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert calls == 2
    assert "/Users/jack" not in result.output
    assert "collision" not in result.output
    assert len(list((outputs / "_errors" / "runs").glob("*/diagnostics.json"))) == 1


def test_summarize_metadata_failure_writes_sanitized_diagnostics_without_leaks(
    tmp_path, monkeypatch
):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=2&vd_source=tracking-secret&token=secret-token"
    )

    def fake_fetch_current_part_metadata(
        ref,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        raise MetadataIngestError(
            "yt-dlp failed for "
            f"{url} with --cookies-file /Users/jack/Downloads/bili-cookies.txt "
            "Cookie: SESSDATA=secret"
        )

    monkeypatch.setattr(cli, "fetch_current_part_metadata", fake_fetch_current_part_metadata)

    result = runner.invoke(
        app,
        [
            "summarize",
            url,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "yt-dlp failed" in result.output
    assert "vd_source" not in result.output
    assert "secret-token" not in result.output
    assert "bili-cookies.txt" not in result.output
    assert "/Users/jack" not in result.output
    assert "SESSDATA=secret" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert not (run_dir / "metadata.json").exists()
    assert diagnostics["error_type"] == "MetadataIngestError"
    assert diagnostics["exit_code"] == 1
    assert diagnostics["stage"] == "metadata"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["artifact_paths"] == ["diagnostics.json"]
    assert "vd_source" not in diagnostics["sanitized_message"]
    assert "secret-token" not in diagnostics["sanitized_message"]
    assert "bili-cookies.txt" not in diagnostics["sanitized_message"]
    assert "/Users/jack" not in diagnostics["sanitized_message"]


def test_summarize_audio_failure_writes_diagnostics_after_metadata(tmp_path, monkeypatch):
    config_home = tmp_path / "config-home"
    outputs = tmp_path / "outputs"
    _install_fake_metadata_fetch(monkeypatch)

    def fake_download_current_part_audio(
        ref,
        metadata,
        run_dir,
        *,
        cookies_from_browser=None,
        cookies_file=None,
    ):
        raise MediaDownloadError(
            "audio duration differs from metadata for "
            "https://www.bilibili.com/video/BV1abcDEF12G?p=2&vd_source=secret "
            "--cookies-file /Users/jack/Downloads/bili-cookies.txt",
            duration_check={
                "status": "duration_mismatch",
                "metadata_seconds": 100,
                "audio_seconds": 106,
                "difference_ratio": 0.06,
                "tolerance_ratio": 0.05,
                "attempts": 2,
            },
        )

    monkeypatch.setattr(cli, "download_current_part_audio", fake_download_current_part_audio)

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--cookies-file",
            "/Users/jack/Downloads/bili-cookies.txt",
            "--yes-i-understand",
            "--out",
            str(outputs),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 1
    assert "duration differs" in result.output
    assert "vd_source" not in result.output
    assert "/Users/jack" not in result.output
    assert "bili-cookies.txt" not in result.output

    video_dir = outputs / "BV1abcDEF12G_p2"
    latest = json.loads((video_dir / "latest.json").read_text(encoding="utf-8"))
    run_dir = video_dir / latest["run_dir"]
    diagnostics = json.loads((run_dir / "diagnostics.json").read_text(encoding="utf-8"))

    assert (run_dir / "metadata.json").is_file()
    assert diagnostics["error_type"] == "MediaDownloadError"
    assert diagnostics["exit_code"] == 1
    assert diagnostics["stage"] == "media"
    assert diagnostics["video_id"] == "BV1abcDEF12G"
    assert diagnostics["part_index"] == 2
    assert diagnostics["duration_check"]["status"] == "duration_mismatch"
    assert diagnostics["artifact_paths"] == ["diagnostics.json", "metadata.json"]
    assert "vd_source" not in diagnostics["sanitized_message"]
    assert "/Users/jack" not in diagnostics["sanitized_message"]
    assert "bili-cookies.txt" not in diagnostics["sanitized_message"]


def test_summarize_debug_log_is_reserved_for_later_slice(tmp_path):
    config_home = tmp_path / "config-home"

    result = runner.invoke(
        app,
        [
            "summarize",
            URL,
            "--debug-log",
            "--yes-i-understand",
            "--out",
            str(tmp_path / "outputs"),
        ],
        env={"BILIFAN_CONFIG_HOME": str(config_home)},
    )

    assert result.exit_code == 2
    assert "--debug-log is reserved for a later slice" in result.output
