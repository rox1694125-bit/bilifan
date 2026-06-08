import json
import subprocess
import sys
from pathlib import Path

import pytest

import bilifan.media as media_module
from bilifan.bilibili import parse_bilibili_url
from bilifan.media import (
    MediaDownloadError,
    build_ffprobe_duration_command,
    build_yt_dlp_audio_command,
    check_duration_match,
    download_current_part_audio,
    ffprobe_duration_seconds,
)


def test_build_yt_dlp_audio_command_uses_current_python_and_run_cache(tmp_path):
    ref = parse_bilibili_url(
        "https://www.bilibili.com/video/BV1abcDEF12G?p=2&vd_source=secret"
    )
    cache_dir = tmp_path / ".bilifan" / "cache"

    cmd = build_yt_dlp_audio_command(
        ref,
        cache_dir,
        cookies_from_browser="chrome",
        cookies_file=Path("/Users/jack/Downloads/bili-cookies.txt"),
    )

    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--no-playlist" in cmd
    assert "-f" in cmd
    assert "bestaudio" in cmd
    assert "bestaudio/best" not in cmd
    assert "--extract-audio" in cmd
    assert "--audio-format" in cmd
    assert "mp3" in cmd
    assert "--paths" in cmd
    assert str(cache_dir) in cmd
    assert "--output" in cmd
    assert f"{ref.output_id}.%(ext)s" in cmd
    assert ref.sanitized_url in cmd
    assert "vd_source" not in " ".join(cmd)
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    assert "--cookies" in cmd
    assert "/Users/jack/Downloads/bili-cookies.txt" in cmd


def test_ffprobe_duration_seconds_reads_json_duration():
    audio_path = Path("/tmp/audio.mp3")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"format": {"duration": "123.456"}}),
            "",
        )

    duration = ffprobe_duration_seconds(audio_path, runner=fake_run)

    assert duration == 123.456
    assert calls == [
        (
            build_ffprobe_duration_command(audio_path),
            {"check": False, "capture_output": True, "text": True, "timeout": 60},
        )
    ]


def test_check_duration_match_allows_five_percent_difference():
    result = check_duration_match(metadata_seconds=100, audio_seconds=104.9, attempts=1)

    assert result == {
        "status": "ok",
        "metadata_seconds": 100,
        "audio_seconds": 104.9,
        "difference_ratio": pytest.approx(0.049),
        "tolerance_ratio": 0.05,
        "attempts": 1,
    }


def test_check_duration_match_flags_mismatch_over_five_percent():
    result = check_duration_match(metadata_seconds=100, audio_seconds=106, attempts=2)

    assert result["status"] == "duration_mismatch"
    assert result["difference_ratio"] == pytest.approx(0.06)
    assert result["attempts"] == 2


def test_download_current_part_audio_retries_once_after_duration_mismatch(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    metadata = {"duration": 100}
    download_attempts = []
    probe_attempts = []

    def fake_download(cmd, **kwargs):
        download_attempts.append(cmd)
        (tmp_path / ".bilifan" / "cache").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".bilifan" / "cache" / f"{ref.output_id}.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_ffprobe(cmd, **kwargs):
        probe_attempts.append(cmd)
        duration = 106 if len(probe_attempts) == 1 else 100
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"format": {"duration": str(duration)}}),
            "",
        )

    result = download_current_part_audio(
        ref,
        metadata,
        tmp_path,
        downloader=fake_download,
        probe_runner=fake_ffprobe,
    )

    assert len(download_attempts) == 2
    assert len(probe_attempts) == 2
    assert result["audio_path"] == f".bilifan/cache/{ref.output_id}.mp3"
    assert result["duration_seconds"] == 100
    assert result["duration_check"]["status"] == "ok"
    assert result["duration_check"]["attempts"] == 2
    assert result["audio_source"] == "yt-dlp"


def test_download_current_part_audio_falls_back_to_playurl_api_on_bilibili_412(
    tmp_path,
):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")
    metadata = {"duration": 100, "cid": "123456"}
    stream_calls = []
    ffmpeg_calls = []

    def fake_download(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            "",
            "ERROR: [BiliBili] abc: HTTP Error 412: Precondition Failed",
        )

    def fake_playurl_fetcher(received_ref, received_metadata):
        assert received_ref == ref
        assert received_metadata == metadata
        return "https://upos.example.test/audio.m4s?deadline=secret"

    def fake_stream_downloader(url, received_ref, raw_path):
        stream_calls.append((url, received_ref, raw_path.name))
        raw_path.write_bytes(b"raw-audio")

    def fake_ffmpeg(cmd, **kwargs):
        ffmpeg_calls.append((cmd, kwargs))
        Path(cmd[-1]).write_bytes(b"mp3-audio")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_ffprobe(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"format": {"duration": "100"}}),
            "",
        )

    result = download_current_part_audio(
        ref,
        metadata,
        tmp_path,
        downloader=fake_download,
        probe_runner=fake_ffprobe,
        playurl_fetcher=fake_playurl_fetcher,
        stream_downloader=fake_stream_downloader,
        ffmpeg_runner=fake_ffmpeg,
    )

    assert result["audio_source"] == "bilibili-playurl-api"
    assert result["audio_path"] == f".bilifan/cache/{ref.output_id}.mp3"
    assert "deadline=secret" not in json.dumps(result)
    assert stream_calls == [
        (
            "https://upos.example.test/audio.m4s?deadline=secret",
            ref,
            f"{ref.output_id}.source.m4s",
        )
    ]
    assert str(tmp_path / ".bilifan" / "cache" / f"{ref.output_id}.source.m4s") in (
        ffmpeg_calls[0][0]
    )
    assert ffmpeg_calls[0][0][-1] == str(
        tmp_path / ".bilifan" / "cache" / f"{ref.output_id}.mp3"
    )
    assert not (tmp_path / ".bilifan" / "cache" / f"{ref.output_id}.source.m4s").exists()


def test_download_current_part_audio_raises_after_retry_mismatch(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")
    metadata = {"duration": 100}

    def fake_download(cmd, **kwargs):
        (tmp_path / ".bilifan" / "cache").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".bilifan" / "cache" / f"{ref.output_id}.mp3").write_bytes(b"audio")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def fake_ffprobe(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            0,
            json.dumps({"format": {"duration": "106"}}),
            "",
        )

    with pytest.raises(MediaDownloadError) as excinfo:
        download_current_part_audio(
            ref,
            metadata,
            tmp_path,
            downloader=fake_download,
            probe_runner=fake_ffprobe,
        )

    assert "duration differs" in str(excinfo.value)
    assert excinfo.value.duration_check["status"] == "duration_mismatch"
    assert excinfo.value.duration_check["attempts"] == 2


def test_download_current_part_audio_wraps_download_failure_without_leaks(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")

    def fake_download(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            "",
            "failed --cookies-file /Users/jack/Downloads/bili-cookies.txt",
        )

    with pytest.raises(MediaDownloadError) as excinfo:
        download_current_part_audio(
            ref,
            {"duration": 100},
            tmp_path,
            downloader=fake_download,
        )

    message = str(excinfo.value)
    assert "yt-dlp audio download failed" in message
    assert "/Users/jack" not in message
    assert "bili-cookies.txt" not in message


def test_download_current_part_audio_missing_output_uses_relative_path_in_error(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")

    def fake_download(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(MediaDownloadError) as excinfo:
        download_current_part_audio(
            ref,
            {"duration": 100},
            tmp_path,
            downloader=fake_download,
        )

    message = str(excinfo.value)
    assert f".bilifan/cache/{ref.output_id}.mp3" in message
    assert str(tmp_path) not in message


def test_fetch_bilibili_playurl_audio_url_selects_highest_bandwidth(monkeypatch):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")
    opened = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            opened.append(("read_size", size))
            return json.dumps(
                {
                    "code": 0,
                    "data": {
                        "dash": {
                            "audio": [
                                {"baseUrl": "https://low.test/audio.m4s", "bandwidth": 1},
                                {
                                    "base_url": "https://high.test/audio.m4s",
                                    "bandwidth": 9,
                                },
                            ]
                        }
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(request, *, timeout):
        opened.append(("urlopen", request.full_url, timeout))
        return FakeResponse()

    monkeypatch.setattr(media_module, "urlopen", fake_urlopen)

    url = media_module.fetch_bilibili_playurl_audio_url(ref, {"cid": "123456"})

    assert url == "https://high.test/audio.m4s"
    assert "bvid=BV1abcDEF12G" in opened[0][1]
    assert "cid=123456" in opened[0][1]
    assert opened[0][2] == media_module.DOWNLOAD_TIMEOUT_SECONDS
    assert opened[1] == ("read_size", media_module.MAX_BILIBILI_API_BYTES + 1)
