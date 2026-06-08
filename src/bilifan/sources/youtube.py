from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from bilifan.diagnostics import redact_text
from bilifan.media import (
    DOWNLOAD_TIMEOUT_SECONDS,
    MediaDownloadError,
    check_duration_match,
    ffprobe_duration_seconds,
)
from bilifan.metadata import METADATA_TIMEOUT_SECONDS, MetadataIngestError

from .base import SourceOptions, VideoRef


class YouTubeAdapter:
    platform = "youtube"

    def can_parse(self, url: str) -> bool:
        parsed = urlparse(url)
        return bool(self._video_id(parsed))

    def parse_url(self, url: str) -> VideoRef:
        parsed = urlparse(url)
        video_id = self._video_id(parsed)
        if not video_id:
            raise ValueError("Invalid YouTube video URL.")
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"
        return VideoRef(
            platform=self.platform,
            source_id=video_id,
            part_id="p1",
            canonical_url=canonical_url,
            raw_url=url,
        )

    def timestamp_url(self, ref: VideoRef, seconds: float) -> str:
        timestamp = max(0, int(seconds))
        return f"https://www.youtube.com/watch?v={ref.source_id}&t={timestamp}s"

    def output_id(self, ref: VideoRef) -> str:
        return f"YT{ref.source_id}_p1"

    def map_metadata(self, raw: dict[str, Any], *, canonical_url: str) -> dict[str, Any]:
        video_id = _first_text(raw.get("id"))
        title = _first_text(raw.get("title"))
        duration = _duration_value(raw.get("duration"))
        return {
            "platform": self.platform,
            "video_id": video_id,
            "part_index": 1,
            "input_url_sanitized": canonical_url,
            "title": title,
            "part_title": title,
            "owner_name": _first_text(raw.get("channel"), raw.get("uploader")),
            "description": _first_text(raw.get("description")),
            "tags": _text_list(raw.get("tags")),
            "cover_url": _first_text(raw.get("thumbnail")),
            "cover_path": "",
            "duration": duration,
            "parts": [
                {
                    "part_index": 1,
                    "cid": video_id,
                    "title": title,
                    "duration": duration,
                }
            ],
            "subtitles": _subtitle_tracks(
                raw.get("subtitles"),
                raw.get("automatic_captions"),
            ),
            "metadata_source": "yt-dlp",
        }

    def fetch_metadata(
        self,
        ref: VideoRef,
        run_dir: Path,
        options: SourceOptions,
        *,
        runner=subprocess.run,
    ) -> dict[str, Any]:
        if options.cookies_file is not None or options.cookies_from_browser is not None:
            raise MetadataIngestError(
                "YouTube cookies are not supported in the public-video MVP."
            )
        (run_dir / ".bilifan").mkdir(parents=True, exist_ok=True)
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--dump-single-json",
            "--skip-download",
            "--no-playlist",
            ref.canonical_url,
        ]
        try:
            result = runner(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=METADATA_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise MetadataIngestError("yt-dlp YouTube metadata timed out.") from exc
        except OSError as exc:
            raise MetadataIngestError(
                f"yt-dlp YouTube metadata failed to start: {exc}"
            ) from exc
        if result.returncode != 0:
            detail = result.stderr or result.stdout or "yt-dlp returned no error output."
            raise MetadataIngestError(
                f"yt-dlp YouTube metadata failed with exit code {result.returncode}: "
                f"{redact_text(detail)}",
                source_exit_code=result.returncode,
            )
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise MetadataIngestError(
                "yt-dlp YouTube metadata returned invalid JSON."
            ) from exc
        if not isinstance(raw, dict):
            raise MetadataIngestError(
                "yt-dlp YouTube metadata returned invalid JSON object."
            )
        metadata_path = run_dir / ".bilifan" / "youtube_metadata.json"
        metadata_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return self.map_metadata(raw, canonical_url=ref.canonical_url)

    def download_audio(
        self,
        ref: VideoRef,
        metadata: dict[str, Any],
        run_dir: Path,
        options: SourceOptions,
        *,
        downloader=subprocess.run,
        probe_runner=subprocess.run,
    ) -> dict[str, Any]:
        if options.cookies_file is not None or options.cookies_from_browser is not None:
            raise MediaDownloadError("YouTube cookies are not supported in the public-video MVP.")

        output_id = self.output_id(ref)
        cache_dir = run_dir / ".bilifan" / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        last_check: dict[str, Any] | None = None

        for attempt in range(1, 3):
            _remove_existing_audio_outputs(cache_dir, output_id)
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
                f"{output_id}.%(ext)s",
                ref.canonical_url,
            ]
            try:
                result = downloader(
                    cmd,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=DOWNLOAD_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                raise MediaDownloadError("yt-dlp YouTube audio download timed out.") from exc
            except OSError as exc:
                raise MediaDownloadError(
                    f"yt-dlp YouTube audio failed to start: {exc}"
                ) from exc
            if result.returncode != 0:
                detail = result.stderr or result.stdout or "yt-dlp returned no error output."
                raise MediaDownloadError(
                    f"yt-dlp YouTube audio failed with exit code {result.returncode}: {detail}",
                    source_exit_code=result.returncode,
                )

            audio_path = cache_dir / f"{output_id}.mp3"
            if not audio_path.is_file():
                raise MediaDownloadError(
                    "yt-dlp YouTube audio did not produce expected file: "
                    f".bilifan/cache/{output_id}.mp3"
                )
            audio_seconds = ffprobe_duration_seconds(audio_path, runner=probe_runner)
            last_check = check_duration_match(
                metadata_seconds=_duration_value(metadata.get("duration")),
                audio_seconds=audio_seconds,
                attempts=attempt,
            )
            if last_check["status"] != "duration_mismatch":
                return {
                    "audio_path": f".bilifan/cache/{output_id}.mp3",
                    "audio_source": "yt-dlp",
                    "duration_seconds": audio_seconds,
                    "duration_check": last_check,
                }

        raise MediaDownloadError(
            "audio duration differs from metadata by more than 5% after retry.",
            duration_check=last_check,
        )

    def _video_id(self, parsed) -> str:
        host = parsed.netloc.lower()
        if host == "youtu.be":
            return parsed.path.strip("/")
        if host in {"www.youtube.com", "youtube.com"} and parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [""])[0]
        return ""


def parse_youtube_vtt(content: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    for block in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            -1,
        )
        if timing_index < 0:
            continue
        timing = lines[timing_index]
        start_raw, end_raw = [
            part.strip().split(" ")[0] for part in timing.split("-->", 1)
        ]
        text_lines = [
            line
            for line in lines[timing_index + 1 :]
            if not line.startswith(("NOTE", "STYLE"))
        ]
        text = " ".join(text_lines).strip()
        if not text:
            continue
        segments.append(
            {
                "start": _parse_vtt_time(start_raw),
                "end": _parse_vtt_time(end_raw),
                "text": redact_text(text, max_length=None),
            }
        )
    return segments


def _parse_vtt_time(value: str) -> float:
    parts = value.split(":")
    seconds = float(parts[-1])
    minutes = int(parts[-2]) if len(parts) >= 2 else 0
    hours = int(parts[-3]) if len(parts) >= 3 else 0
    return hours * 3600 + minutes * 60 + seconds


def _subtitle_tracks(subtitles: Any, automatic: Any) -> list[dict[str, str]]:
    tracks: list[dict[str, str]] = []
    for source_name, source in (("manual", subtitles), ("automatic", automatic)):
        if not isinstance(source, dict):
            continue
        for language, entries in source.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                url = _first_text(entry.get("url"))
                ext = _first_text(entry.get("ext"))
                if not url or ext.lower() != "vtt":
                    continue
                tracks.append(
                    {
                        "language": _first_text(language),
                        "url": url,
                        "ext": ext,
                        "source": source_name,
                    }
                )
    return tracks


def _remove_existing_audio_outputs(cache_dir: Path, output_id: str) -> None:
    for path in cache_dir.glob(f"{output_id}.*"):
        if path.is_file():
            path.unlink()


def _duration_value(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value for text in [_first_text(item)] if text]


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str):
            return redact_text(value, max_length=None)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return str(value)
    return ""
