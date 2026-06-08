import json
import subprocess
import sys
from pathlib import Path

import pytest

import bilifan.metadata as metadata_module
from bilifan.bilibili import parse_bilibili_url
from bilifan.metadata import (
    MetadataIngestError,
    build_yt_dlp_metadata_command,
    fetch_current_part_metadata,
    metadata_from_yt_dlp_json,
)


def test_fetch_yt_dlp_uses_sanitized_url_and_keeps_cookies_out_of_metadata(tmp_path):
    raw_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=2&spm_id_from=333.999&vd_source=tracking-secret"
    )
    ref = parse_bilibili_url(raw_url)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        payload = {
            "id": ref.bvid,
            "cid": "987654",
            "title": "Top level title",
            "uploader": "Uploader",
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    result = fetch_current_part_metadata(
        ref,
        tmp_path,
        cookies_from_browser="chrome",
        cookies_file=Path("/Users/jack/Downloads/bili-cookies.txt"),
        runner=fake_run,
    )

    cmd = calls[0][0]
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--dump-single-json" in cmd
    assert "--skip-download" in cmd
    assert "--no-warnings" in cmd
    assert ref.sanitized_url in cmd
    assert raw_url not in cmd
    assert "spm_id_from" not in " ".join(cmd)
    assert "vd_source" not in " ".join(cmd)
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    assert "--cookies" in cmd
    assert "/Users/jack/Downloads/bili-cookies.txt" in cmd

    result_text = json.dumps(result, ensure_ascii=False)
    assert result["input_url_sanitized"] == ref.sanitized_url
    assert result["video_id"] == ref.bvid
    assert result["part_index"] == 2
    assert "chrome" not in result_text
    assert "bili-cookies.txt" not in result_text
    assert "/Users/jack" not in result_text


def test_build_yt_dlp_command_uses_current_python_module_entrypoint():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")

    cmd = build_yt_dlp_metadata_command(ref)

    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "yt-dlp" not in cmd[:1]


def test_metadata_from_yt_dlp_json_maps_current_part_fields():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    payload = {
        "id": ref.bvid,
        "cid": "top-level-cid",
        "title": "Collection title",
        "description": "Description text",
        "uploader": "Owner Name",
        "tags": ["tag-a", "tag-b"],
        "thumbnail": "https://i0.hdslb.com/bfs/archive/cover.jpg?token=secret",
        "duration": 618,
        "entries": [
            {
                "page": 1,
                "cid": "111",
                "part": "Part one",
                "title": "Part one title",
                "duration": 300,
            },
            {
                "page": 2,
                "cid": "222",
                "part": "Part two",
                "title": "Part two title",
                "duration": 318,
            },
        ],
        "subtitles": {
            "zh-Hans": [
                {
                    "name": "Chinese",
                    "url": "https://example.com/subtitle.srt?token=secret",
                    "ext": "srt",
                }
            ]
        },
    }

    result = metadata_from_yt_dlp_json(
        ref,
        payload,
        generated_at="2026-06-08T00:00:00+00:00",
        yt_dlp_version="2026.3.17",
        ffmpeg_version="",
        cover_path="assets/cover.jpg",
    )

    assert result["bilifan_version"] == "0.1.0"
    assert result["generated_at"] == "2026-06-08T00:00:00+00:00"
    assert result["input_url_sanitized"] == ref.sanitized_url
    assert result["video_id"] == ref.bvid
    assert result["part_index"] == 2
    assert result["cid"] == "222"
    assert result["title"] == "Collection title"
    assert result["part_title"] == "Part two"
    assert result["owner_name"] == "Owner Name"
    assert result["description"] == "Description text"
    assert result["tags"] == ["tag-a", "tag-b"]
    assert result["cover_url"] == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert result["cover_path"] == "assets/cover.jpg"
    assert result["duration"] == 318
    assert result["parts"] == [
        {"part_index": 1, "cid": "111", "title": "Part one", "duration": 300},
        {"part_index": 2, "cid": "222", "title": "Part two", "duration": 318},
    ]
    assert result["subtitles"] == [
        {
            "language": "zh-Hans",
            "name": "Chinese",
            "url": "https://example.com/subtitle.srt?token=secret",
            "ext": "srt",
        }
    ]
    assert result["yt_dlp_version"] == "2026.3.17"
    assert result["ffmpeg_version"] == ""
    assert result["provenance"] == {
        "bilifan_version": "0.1.0",
        "generated_at": "2026-06-08T00:00:00+00:00",
        "input_url_sanitized": ref.sanitized_url,
        "video_id": ref.bvid,
        "part_index": 2,
        "cid": "222",
        "metadata_attempted_source": "yt-dlp",
        "metadata_source": "yt-dlp",
        "yt_dlp_version": "2026.3.17",
        "ffmpeg_version": "",
    }
    provenance_text = json.dumps(result["provenance"], ensure_ascii=False)
    assert "token=secret" not in provenance_text
    assert "/Users/jack" not in provenance_text


def test_metadata_from_yt_dlp_json_rejects_missing_requested_part():
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    payload = {
        "title": "Collection title",
        "entries": [
            {"page": 1, "cid": "111", "part": "Part one", "duration": 300},
        ],
    }

    with pytest.raises(MetadataIngestError, match="requested part p=2"):
        metadata_from_yt_dlp_json(
            ref,
            payload,
            generated_at="2026-06-08T00:00:00+00:00",
            yt_dlp_version="2026.3.17",
            ffmpeg_version="",
            cover_path="",
        )


def test_fetch_current_part_metadata_raises_redacted_error_on_yt_dlp_failure(tmp_path):
    raw_url = (
        "https://www.bilibili.com/video/BV1abcDEF12G"
        "?p=1&vd_source=tracking-secret&token=secret-token"
    )
    ref = parse_bilibili_url(raw_url)

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            23,
            "",
            (
                "failed with --cookies-file /Users/jack/Downloads/bili-cookies.txt "
                "--cookies-from-browser chrome "
                f"for {raw_url} Cookie: SESSDATA=secret; bili_jct=token"
            ),
        )

    with pytest.raises(MetadataIngestError) as excinfo:
        fetch_current_part_metadata(
            ref,
            tmp_path,
            cookies_file=Path("/Users/jack/Downloads/bili-cookies.txt"),
            runner=fake_run,
        )

    message = str(excinfo.value)
    assert excinfo.value.source_exit_code == 23
    assert "yt-dlp failed" in message
    assert "BV1abcDEF12G?p=1" in message
    assert "vd_source" not in message
    assert "secret-token" not in message
    assert "bili-cookies.txt" not in message
    assert "chrome" not in message
    assert "/Users/jack" not in message
    assert "SESSDATA=secret" not in message


def test_fetch_current_part_metadata_falls_back_to_public_api_on_bilibili_412(
    tmp_path,
):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=2")
    calls = []

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            cmd,
            1,
            "",
            (
                "ERROR: [BiliBili] abc: Unable to download webpage: "
                "HTTP Error 412: Precondition Failed"
            ),
        )

    def fake_public_api_fetcher(received_ref):
        calls.append(received_ref)
        return {
            "view": {
                "bvid": ref.bvid,
                "cid": 999,
                "title": "API collection title",
                "desc": "API description",
                "owner": {"name": "API Owner"},
                "pic": "https://i0.hdslb.com/bfs/archive/api-cover.jpg?token=secret",
                "duration": 600,
                "pages": [
                    {"page": 1, "cid": 111, "part": "API part one", "duration": 300},
                    {"page": 2, "cid": 222, "part": "API part two", "duration": 300},
                ],
                "subtitle": {
                    "list": [
                        {
                            "lan": "zh-Hans",
                            "lan_doc": "中文",
                            "subtitle_url": "//aisubtitle.hdslb.com/subtitle.json?token=secret",
                        }
                    ]
                },
            },
            "tags": [{"tag_name": "教程"}, {"tag_name": "AI"}],
        }

    result = fetch_current_part_metadata(
        ref,
        tmp_path,
        runner=fake_run,
        public_api_fetcher=fake_public_api_fetcher,
    )

    assert calls == [ref]
    assert result["metadata_source"] == "bilibili-public-api"
    assert result["provenance"]["metadata_attempted_source"] == "yt-dlp"
    assert result["provenance"]["metadata_source"] == "bilibili-public-api"
    assert result["title"] == "API collection title"
    assert result["part_title"] == "API part two"
    assert result["owner_name"] == "API Owner"
    assert result["description"] == "API description"
    assert result["tags"] == ["教程", "AI"]
    assert result["cid"] == "222"
    assert result["duration"] == 300
    assert result["cover_url"] == "https://i0.hdslb.com/bfs/archive/api-cover.jpg"
    assert result["subtitles"] == [
        {
            "language": "zh-Hans",
            "name": "中文",
            "url": "https://aisubtitle.hdslb.com/subtitle.json?token=secret",
            "ext": "json",
        }
    ]


def test_fetch_current_part_metadata_does_not_fallback_for_non_412_failures(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "ERROR: network unavailable")

    def forbidden_public_api_fetcher(received_ref):
        raise AssertionError("public API fallback should only run for Bilibili 412")

    with pytest.raises(MetadataIngestError, match="network unavailable"):
        fetch_current_part_metadata(
            ref,
            tmp_path,
            runner=fake_run,
            public_api_fetcher=forbidden_public_api_fetcher,
        )


def test_fetch_current_part_metadata_wraps_timeout_and_start_failure(tmp_path):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")

    def timeout_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=kwargs["timeout"])

    with pytest.raises(MetadataIngestError, match="timed out"):
        fetch_current_part_metadata(ref, tmp_path, runner=timeout_run)

    def start_failure_run(cmd, **kwargs):
        raise FileNotFoundError("/Users/jack/.venv/bin/yt-dlp")

    with pytest.raises(MetadataIngestError) as excinfo:
        fetch_current_part_metadata(ref, tmp_path, runner=start_failure_run)

    assert "failed to start" in str(excinfo.value)
    assert "/Users/jack" not in str(excinfo.value)


def test_cover_download_uses_sanitized_hdslb_url_timeout_and_relative_path(
    tmp_path, monkeypatch
):
    ref = parse_bilibili_url("https://www.bilibili.com/video/BV1abcDEF12G?p=1")
    opened = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            opened.append(("read_size", size))
            return b"cover-bytes"

    def fake_urlopen(url, *, timeout):
        opened.append(("urlopen", url, timeout))
        return FakeResponse()

    def fake_run(cmd, **kwargs):
        payload = {
            "id": ref.bvid,
            "title": "Title",
            "thumbnail": "https://i0.hdslb.com/bfs/archive/cover.jpg?token=secret",
        }
        return subprocess.CompletedProcess(cmd, 0, json.dumps(payload), "")

    monkeypatch.setattr(metadata_module, "urlopen", fake_urlopen)

    result = fetch_current_part_metadata(ref, tmp_path, runner=fake_run)

    assert result["cover_url"] == "https://i0.hdslb.com/bfs/archive/cover.jpg"
    assert result["cover_path"] == "assets/cover.jpg"
    assert (tmp_path / "assets" / "cover.jpg").read_bytes() == b"cover-bytes"
    assert opened == [
        (
            "urlopen",
            "https://i0.hdslb.com/bfs/archive/cover.jpg",
            metadata_module.COVER_DOWNLOAD_TIMEOUT_SECONDS,
        ),
        ("read_size", metadata_module.MAX_COVER_BYTES + 1),
    ]


def test_cover_download_rejects_non_http_and_non_hdslb_hosts(tmp_path, monkeypatch):
    opened = []

    def fake_urlopen(url, *, timeout):
        opened.append(url)
        raise AssertionError("urlopen should not be called for rejected cover URLs")

    monkeypatch.setattr(metadata_module, "urlopen", fake_urlopen)

    assert metadata_module._download_cover(tmp_path, "file:///tmp/cover.jpg") == ""
    assert (
        metadata_module._download_cover(
            tmp_path,
            "https://example.com/bfs/archive/cover.jpg?token=secret",
        )
        == ""
    )
    assert opened == []
    assert not (tmp_path / "assets" / "cover.jpg").exists()


def test_cover_download_requires_https_for_initial_and_final_urls(tmp_path, monkeypatch):
    opened = []

    def fake_urlopen(url, *, timeout):
        opened.append(url)
        raise AssertionError("urlopen should not be called for http cover URLs")

    monkeypatch.setattr(metadata_module, "urlopen", fake_urlopen)

    assert (
        metadata_module._download_cover(
            tmp_path,
            "http://i0.hdslb.com/bfs/archive/cover.jpg",
        )
        == ""
    )
    assert opened == []

    class HttpRedirectResponse:
        url = "http://i0.hdslb.com/bfs/archive/redirected.jpg"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return b"insecure-cover"

    monkeypatch.setattr(
        metadata_module,
        "urlopen",
        lambda url, *, timeout: HttpRedirectResponse(),
    )

    assert (
        metadata_module._download_cover(
            tmp_path,
            "https://i0.hdslb.com/bfs/archive/redirect.jpg",
        )
        == ""
    )
    assert not (tmp_path / "assets" / "cover.jpg").exists()


def test_cover_download_drops_oversized_response_and_swallows_network_errors(
    tmp_path, monkeypatch
):
    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return b"x" * size

    monkeypatch.setattr(metadata_module, "MAX_COVER_BYTES", 3)
    monkeypatch.setattr(metadata_module, "urlopen", lambda url, *, timeout: OversizedResponse())

    assert (
        metadata_module._download_cover(
            tmp_path,
            "https://i0.hdslb.com/bfs/archive/too-large.jpg",
        )
        == ""
    )
    assert not (tmp_path / "assets" / "cover.jpg").exists()

    def failing_urlopen(url, *, timeout):
        raise OSError("network unavailable")

    monkeypatch.setattr(metadata_module, "urlopen", failing_urlopen)

    assert (
        metadata_module._download_cover(
            tmp_path,
            "https://i0.hdslb.com/bfs/archive/error.jpg",
        )
        == ""
    )


def test_fetch_bilibili_api_json_uses_timeout_and_size_cap(monkeypatch):
    opened = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            opened.append(("read_size", size))
            return b'{"code":0,"data":{"ok":true}}'

    def fake_urlopen(request, *, timeout):
        opened.append(("urlopen", request.full_url, timeout))
        return FakeResponse()

    monkeypatch.setattr(metadata_module, "urlopen", fake_urlopen)

    result = metadata_module._fetch_bilibili_api_json(
        "https://api.bilibili.com/x/web-interface/view?bvid=BV1abcDEF12G"
    )

    assert result == {"code": 0, "data": {"ok": True}}
    assert opened == [
        (
            "urlopen",
            "https://api.bilibili.com/x/web-interface/view?bvid=BV1abcDEF12G",
            metadata_module.METADATA_TIMEOUT_SECONDS,
        ),
        ("read_size", metadata_module.MAX_BILIBILI_API_BYTES + 1),
    ]


def test_fetch_bilibili_api_json_wraps_invalid_error_and_large_responses(monkeypatch):
    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return self.body

    monkeypatch.setattr(metadata_module, "urlopen", lambda request, *, timeout: FakeResponse(b"[]"))
    with pytest.raises(MetadataIngestError, match="invalid JSON object"):
        metadata_module._fetch_bilibili_api_json("https://api.bilibili.com/x/test")

    monkeypatch.setattr(
        metadata_module,
        "urlopen",
        lambda request, *, timeout: FakeResponse(b"not-json"),
    )
    with pytest.raises(MetadataIngestError, match="invalid JSON"):
        metadata_module._fetch_bilibili_api_json("https://api.bilibili.com/x/test")

    monkeypatch.setattr(
        metadata_module,
        "urlopen",
        lambda request, *, timeout: FakeResponse(b'{"code":-400,"message":"bad request"}'),
    )
    with pytest.raises(MetadataIngestError, match="bad request"):
        metadata_module._fetch_bilibili_api_json("https://api.bilibili.com/x/test")

    monkeypatch.setattr(metadata_module, "MAX_BILIBILI_API_BYTES", 3)
    monkeypatch.setattr(
        metadata_module,
        "urlopen",
        lambda request, *, timeout: FakeResponse(b"abcd"),
    )
    with pytest.raises(MetadataIngestError, match="too large"):
        metadata_module._fetch_bilibili_api_json("https://api.bilibili.com/x/test")

def test_cover_download_rejects_redirects_to_non_hdslb_hosts(tmp_path, monkeypatch):
    class RedirectedResponse:
        url = "https://example.com/redirected-cover.jpg"

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self, size):
            return b"redirected-cover"

    monkeypatch.setattr(
        metadata_module,
        "urlopen",
        lambda url, *, timeout: RedirectedResponse(),
    )

    assert (
        metadata_module._download_cover(
            tmp_path,
            "https://i0.hdslb.com/bfs/archive/redirect.jpg",
        )
        == ""
    )
    assert not (tmp_path / "assets" / "cover.jpg").exists()
