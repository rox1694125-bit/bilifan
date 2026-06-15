from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from .bilibili import BilibiliPartRef
from .diagnostics import redact_text


Runner = Callable[..., subprocess.CompletedProcess[str]]
PlayurlFetcher = Callable[[BilibiliPartRef, dict[str, Any]], str | list[str]]
StreamDownloader = Callable[[str, BilibiliPartRef, Path], None]
DOWNLOAD_TIMEOUT_SECONDS = 60 * 60
FFPROBE_TIMEOUT_SECONDS = 60
STREAM_READ_TIMEOUT_SECONDS = 30
DURATION_TOLERANCE_RATIO = 0.05
MAX_BILIBILI_API_BYTES = 10 * 1024 * 1024
MAX_AUDIO_BYTES = 512 * 1024 * 1024
STREAM_CHUNK_SIZE = 1024 * 1024
VISIBLE_AUDIO_ARTIFACT = "media/audio.mp3"


class MediaDownloadError(RuntimeError):
    """Raised when current-P audio cannot be downloaded or verified."""

    def __init__(
        self,
        message: str,
        *,
        duration_check: dict[str, Any] | None = None,
        source_exit_code: int | None = None,
    ) -> None:
        self.sanitized_message = redact_text(message)
        self.duration_check = duration_check
        self.source_exit_code = source_exit_code
        super().__init__(self.sanitized_message)


def build_yt_dlp_audio_command(
    ref: BilibiliPartRef,
    cache_dir: Path,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--no-playlist",
        "-f",
        "bestaudio",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--audio-quality",
        "0",
        "--paths",
        str(cache_dir),
        "--output",
        f"{ref.output_id}.%(ext)s",
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    if cookies_file is not None:
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(ref.sanitized_url)
    return cmd


def build_ffprobe_duration_command(audio_path: Path) -> list[str]:
    return [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]


def ffprobe_duration_seconds(
    audio_path: Path,
    *,
    runner: Runner = subprocess.run,
) -> float:
    cmd = build_ffprobe_duration_command(audio_path)
    try:
        result = runner(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaDownloadError(
            f"ffprobe timed out after {FFPROBE_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise MediaDownloadError(f"ffprobe failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr or result.stdout or "ffprobe returned no error output."
        raise MediaDownloadError(
            f"ffprobe failed with exit code {result.returncode}: {detail}",
            source_exit_code=result.returncode,
        )

    try:
        payload = json.loads(result.stdout)
        raw_duration = payload["format"]["duration"]
        duration = float(raw_duration)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaDownloadError("ffprobe returned invalid duration JSON.") from exc

    if duration <= 0:
        raise MediaDownloadError("ffprobe returned a non-positive audio duration.")
    return duration


def check_duration_match(
    *,
    metadata_seconds: int | float | None,
    audio_seconds: int | float,
    attempts: int,
) -> dict[str, Any]:
    if (
        metadata_seconds is None
        or isinstance(metadata_seconds, bool)
        or metadata_seconds <= 0
        or audio_seconds <= 0
    ):
        return {
            "status": "skipped",
            "metadata_seconds": metadata_seconds,
            "audio_seconds": audio_seconds,
            "difference_ratio": None,
            "tolerance_ratio": DURATION_TOLERANCE_RATIO,
            "attempts": attempts,
        }

    difference_ratio = abs(float(audio_seconds) - float(metadata_seconds)) / float(
        metadata_seconds
    )
    status = (
        "ok"
        if difference_ratio <= DURATION_TOLERANCE_RATIO
        else "duration_mismatch"
    )
    return {
        "status": status,
        "metadata_seconds": metadata_seconds,
        "audio_seconds": audio_seconds,
        "difference_ratio": difference_ratio,
        "tolerance_ratio": DURATION_TOLERANCE_RATIO,
        "attempts": attempts,
    }


def download_current_part_audio(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    run_dir: Path,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    downloader: Runner = subprocess.run,
    probe_runner: Runner = subprocess.run,
    playurl_fetcher: PlayurlFetcher | None = None,
    stream_downloader: StreamDownloader | None = None,
    ffmpeg_runner: Runner = subprocess.run,
) -> dict[str, Any]:
    cache_dir = run_dir / ".bilifan" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    metadata_duration = _metadata_duration(metadata)
    last_check: dict[str, Any] | None = None

    for attempt in range(1, 3):
        _remove_existing_audio_outputs(cache_dir, ref.output_id)
        audio_source = _run_audio_download(
            ref,
            metadata,
            cache_dir,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            downloader=downloader,
            playurl_fetcher=playurl_fetcher or fetch_bilibili_playurl_audio_urls,
            stream_downloader=stream_downloader or download_bilibili_audio_stream,
            ffmpeg_runner=ffmpeg_runner,
        )
        audio_path = cache_dir / f"{ref.output_id}.mp3"
        if not audio_path.is_file():
            raise MediaDownloadError(
                "yt-dlp audio download did not produce expected file: "
                f"{_relative_audio_path(ref)}"
            )

        audio_seconds = ffprobe_duration_seconds(audio_path, runner=probe_runner)
        last_check = check_duration_match(
            metadata_seconds=metadata_duration,
            audio_seconds=audio_seconds,
            attempts=attempt,
        )
        if last_check["status"] != "duration_mismatch":
            return {
                "audio_path": _relative_audio_path(ref),
                "audio_source": audio_source,
                "duration_seconds": audio_seconds,
                "duration_check": last_check,
            }

    if _metadata_cid(metadata):
        try:
            return _run_playurl_audio_download_with_duration_check(
                ref,
                metadata,
                cache_dir,
                metadata_duration=metadata_duration,
                attempts=3,
                probe_runner=probe_runner,
                playurl_fetcher=playurl_fetcher or fetch_bilibili_playurl_audio_urls,
                stream_downloader=stream_downloader or download_bilibili_audio_stream,
                ffmpeg_runner=ffmpeg_runner,
            )
        except MediaDownloadError as exc:
            if exc.duration_check is not None:
                raise
            raise MediaDownloadError(
                "audio duration differs from metadata by more than 5% after retry; "
                f"playurl fallback also failed: {exc}",
                duration_check=last_check,
                source_exit_code=exc.source_exit_code,
            ) from exc

    raise MediaDownloadError(
        "audio duration differs from metadata by more than 5% after retry.",
        duration_check=last_check,
    )


def _run_audio_download(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    cache_dir: Path,
    *,
    cookies_from_browser: str | None,
    cookies_file: Path | None,
    downloader: Runner,
    playurl_fetcher: PlayurlFetcher,
    stream_downloader: StreamDownloader,
    ffmpeg_runner: Runner,
) -> str:
    cmd = build_yt_dlp_audio_command(
        ref,
        cache_dir,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    try:
        result = downloader(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaDownloadError(
            f"yt-dlp audio download timed out after {DOWNLOAD_TIMEOUT_SECONDS} seconds."
        ) from exc
    except OSError as exc:
        raise MediaDownloadError(f"yt-dlp audio download failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr or result.stdout or "yt-dlp returned no error output."
        if _is_bilibili_412_error(detail):
            return _run_playurl_audio_download(
                ref,
                metadata,
                cache_dir,
                playurl_fetcher=playurl_fetcher,
                stream_downloader=stream_downloader,
                ffmpeg_runner=ffmpeg_runner,
            )
        raise MediaDownloadError(
            f"yt-dlp audio download failed with exit code {result.returncode}: {detail}",
            source_exit_code=result.returncode,
        )
    return "yt-dlp"


def fetch_bilibili_playurl_audio_url(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
) -> str:
    return fetch_bilibili_playurl_audio_urls(ref, metadata)[0]


def fetch_bilibili_playurl_audio_urls(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
) -> list[str]:
    cid = _metadata_cid(metadata)
    if not cid:
        raise MediaDownloadError("Bilibili playurl fallback requires current-P cid.")

    url = (
        "https://api.bilibili.com/x/player/playurl"
        f"?bvid={quote(ref.bvid)}&cid={quote(cid)}&fnval=16&fourk=1"
    )
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": ref.sanitized_url,
        },
    )
    try:
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BILIBILI_API_BYTES + 1)
    except (OSError, URLError, ValueError) as exc:
        raise MediaDownloadError(f"Bilibili playurl API request failed: {exc}") from exc

    if len(raw) > MAX_BILIBILI_API_BYTES:
        raise MediaDownloadError("Bilibili playurl API response was too large.")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MediaDownloadError("Bilibili playurl API returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise MediaDownloadError("Bilibili playurl API returned invalid JSON object.")
    if payload.get("code") != 0:
        raise MediaDownloadError(
            f"Bilibili playurl API returned error: {_first_text(payload.get('message'))}"
        )

    audio_entries = _playurl_audio_entries(payload)
    if not audio_entries:
        raise MediaDownloadError("Bilibili playurl API returned no audio streams.")
    selected = max(audio_entries, key=lambda entry: _numeric_value(entry.get("bandwidth")))
    audio_urls = _playurl_audio_candidate_urls(selected)
    if not audio_urls:
        raise MediaDownloadError("Bilibili playurl API returned an invalid audio URL.")
    return audio_urls


def download_bilibili_audio_stream(
    audio_url: str,
    ref: BilibiliPartRef,
    raw_audio_path: Path,
) -> None:
    if not _is_https_url(audio_url):
        raise MediaDownloadError("Bilibili audio stream URL must be HTTPS.")
    request = Request(
        audio_url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": ref.sanitized_url,
        },
    )
    raw_audio_path.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with urlopen(request, timeout=STREAM_READ_TIMEOUT_SECONDS) as response:
            with raw_audio_path.open("wb") as output:
                while True:
                    chunk = response.read(STREAM_CHUNK_SIZE)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_AUDIO_BYTES:
                        raise MediaDownloadError("Bilibili audio stream was too large.")
                    output.write(chunk)
    except MediaDownloadError:
        raise
    except (OSError, URLError, ValueError) as exc:
        raise MediaDownloadError(
            "Bilibili audio stream download failed: "
            f"{exc.__class__.__name__}: {exc}"
        ) from exc

    if total <= 0:
        raise MediaDownloadError("Bilibili audio stream was empty.")


def build_ffmpeg_convert_command(raw_audio_path: Path, mp3_path: Path) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-i",
        str(raw_audio_path),
        "-vn",
        "-acodec",
        "libmp3lame",
        "-q:a",
        "0",
        str(mp3_path),
    ]


def convert_audio_to_mp3(
    raw_audio_path: Path,
    mp3_path: Path,
    *,
    runner: Runner = subprocess.run,
) -> None:
    cmd = build_ffmpeg_convert_command(raw_audio_path, mp3_path)
    try:
        result = runner(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaDownloadError("ffmpeg audio conversion timed out.") from exc
    except OSError as exc:
        raise MediaDownloadError(f"ffmpeg failed to start: {exc}") from exc

    if result.returncode != 0:
        detail = result.stderr or result.stdout or "ffmpeg returned no error output."
        raise MediaDownloadError(
            f"ffmpeg audio conversion failed with exit code {result.returncode}: {detail}",
            source_exit_code=result.returncode,
        )


def publish_audio_artifact(run_dir: Path, media: dict[str, Any]) -> str:
    raw_path = media.get("audio_path")
    if not isinstance(raw_path, str) or not raw_path:
        raise MediaDownloadError("Cannot publish audio artifact without audio_path.")
    if "\\" in raw_path or raw_path.startswith("/") or ".." in Path(raw_path).parts:
        raise MediaDownloadError("Cannot publish unsafe audio artifact path.")

    source_path = (run_dir / raw_path).resolve(strict=False)
    resolved_run_dir = run_dir.resolve(strict=False)
    if not source_path.is_relative_to(resolved_run_dir):
        raise MediaDownloadError("Cannot publish audio artifact outside run directory.")
    if not source_path.is_file():
        raise MediaDownloadError("Cannot publish missing audio artifact.")

    target_path = run_dir / VISIBLE_AUDIO_ARTIFACT
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)
    return VISIBLE_AUDIO_ARTIFACT


def _run_playurl_audio_download(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    cache_dir: Path,
    *,
    playurl_fetcher: PlayurlFetcher,
    stream_downloader: StreamDownloader,
    ffmpeg_runner: Runner,
) -> str:
    raw_audio_path = cache_dir / f"{ref.output_id}.source.m4s"
    mp3_path = cache_dir / f"{ref.output_id}.mp3"
    audio_urls = _normalize_audio_urls(playurl_fetcher(ref, metadata))
    last_error: MediaDownloadError | None = None
    for audio_url in audio_urls:
        try:
            stream_downloader(audio_url, ref, raw_audio_path)
            convert_audio_to_mp3(raw_audio_path, mp3_path, runner=ffmpeg_runner)
            last_error = None
            return "bilibili-playurl-api"
        except MediaDownloadError as exc:
            last_error = exc
        finally:
            if raw_audio_path.exists():
                raw_audio_path.unlink()
            if last_error is not None and mp3_path.exists():
                mp3_path.unlink()
    if last_error is not None:
        raise MediaDownloadError(
            "Bilibili audio stream download failed for all playurl candidates: "
            f"{last_error}"
        ) from last_error
    raise MediaDownloadError("Bilibili playurl API returned no usable audio URLs.")


def _run_playurl_audio_download_with_duration_check(
    ref: BilibiliPartRef,
    metadata: dict[str, Any],
    cache_dir: Path,
    *,
    metadata_duration: int | float | None,
    attempts: int,
    probe_runner: Runner,
    playurl_fetcher: PlayurlFetcher,
    stream_downloader: StreamDownloader,
    ffmpeg_runner: Runner,
) -> dict[str, Any]:
    _remove_existing_audio_outputs(cache_dir, ref.output_id)
    audio_source = _run_playurl_audio_download(
        ref,
        metadata,
        cache_dir,
        playurl_fetcher=playurl_fetcher,
        stream_downloader=stream_downloader,
        ffmpeg_runner=ffmpeg_runner,
    )
    audio_path = cache_dir / f"{ref.output_id}.mp3"
    if not audio_path.is_file():
        raise MediaDownloadError(
            "Bilibili playurl fallback did not produce expected file: "
            f"{_relative_audio_path(ref)}"
        )

    audio_seconds = ffprobe_duration_seconds(audio_path, runner=probe_runner)
    duration_check = check_duration_match(
        metadata_seconds=metadata_duration,
        audio_seconds=audio_seconds,
        attempts=attempts,
    )
    if duration_check["status"] == "duration_mismatch":
        raise MediaDownloadError(
            "audio duration differs from metadata after yt-dlp retry and playurl "
            "fallback.",
            duration_check=duration_check,
        )
    return {
        "audio_path": _relative_audio_path(ref),
        "audio_source": audio_source,
        "duration_seconds": audio_seconds,
        "duration_check": duration_check,
    }


def _metadata_duration(metadata: dict[str, Any]) -> int | float | None:
    duration = metadata.get("duration")
    if isinstance(duration, bool) or duration is None:
        return None
    if isinstance(duration, int | float):
        return duration
    if isinstance(duration, str):
        try:
            parsed = float(duration)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _metadata_cid(metadata: dict[str, Any]) -> str:
    return _first_text(metadata.get("cid"))


def _remove_existing_audio_outputs(cache_dir: Path, output_id: str) -> None:
    for path in cache_dir.glob(f"{output_id}.*"):
        if path.is_file():
            path.unlink()


def _relative_audio_path(ref: BilibiliPartRef) -> str:
    return f".bilifan/cache/{ref.output_id}.mp3"


def _playurl_audio_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    dash = data.get("dash")
    if not isinstance(dash, dict):
        return []
    audio_entries = dash.get("audio")
    if not isinstance(audio_entries, list):
        return []
    return [entry for entry in audio_entries if isinstance(entry, dict)]


def _playurl_audio_candidate_urls(entry: dict[str, Any]) -> list[str]:
    raw_candidates: list[Any] = [
        entry.get("baseUrl"),
        entry.get("base_url"),
    ]
    for key in ("backupUrl", "backup_url"):
        backup = entry.get(key)
        if isinstance(backup, list):
            raw_candidates.extend(backup)
        else:
            raw_candidates.append(backup)

    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in raw_candidates:
        url = _first_text(raw_url)
        if not _is_https_url(url) or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def _normalize_audio_urls(value: str | list[str]) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []

    urls: list[str] = []
    seen: set[str] = set()
    for raw_url in values:
        url = _first_text(raw_url)
        if not _is_https_url(url) or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def _numeric_value(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0
    return 0


def _is_https_url(raw_url: str) -> bool:
    return urlparse(raw_url).scheme == "https"


def _is_bilibili_412_error(text: str) -> bool:
    return "BiliBili" in text and "HTTP Error 412" in text


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return ""
