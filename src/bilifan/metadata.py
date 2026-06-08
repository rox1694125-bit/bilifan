from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from . import __version__
from .bilibili import BilibiliPartRef
from .diagnostics import redact_text


Runner = Callable[..., subprocess.CompletedProcess[str]]
PublicApiFetcher = Callable[[BilibiliPartRef], dict[str, Any]]
METADATA_TIMEOUT_SECONDS = 120
COVER_DOWNLOAD_TIMEOUT_SECONDS = 20
MAX_COVER_BYTES = 5 * 1024 * 1024
MAX_BILIBILI_API_BYTES = 10 * 1024 * 1024
ALLOWED_COVER_HOST_SUFFIXES = (".hdslb.com",)


class MetadataIngestError(RuntimeError):
    """Raised when yt-dlp metadata ingest cannot produce usable JSON."""

    def __init__(self, message: str, *, source_exit_code: int | None = None) -> None:
        self.sanitized_message = redact_text(message)
        self.source_exit_code = source_exit_code
        super().__init__(self.sanitized_message)


def build_yt_dlp_metadata_command(
    ref: BilibiliPartRef,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--dump-single-json",
        "--skip-download",
        "--no-warnings",
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    if cookies_file is not None:
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(ref.sanitized_url)
    return cmd


def fetch_current_part_metadata(
    ref: BilibiliPartRef,
    run_dir: Path,
    *,
    cookies_from_browser: str | None = None,
    cookies_file: Path | None = None,
    runner: Runner = subprocess.run,
    public_api_fetcher: PublicApiFetcher | None = None,
) -> dict[str, Any]:
    cmd = build_yt_dlp_metadata_command(
        ref,
        cookies_from_browser=cookies_from_browser,
        cookies_file=cookies_file,
    )
    try:
        result = runner(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=METADATA_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise MetadataIngestError(
            f"yt-dlp timed out after {METADATA_TIMEOUT_SECONDS} seconds.",
        ) from exc
    except OSError as exc:
        raise MetadataIngestError(f"yt-dlp failed to start: {exc}") from exc
    if result.returncode != 0:
        detail = result.stderr or result.stdout or "yt-dlp returned no error output."
        if _is_bilibili_412_error(detail):
            return _fetch_public_api_metadata(
                ref,
                run_dir,
                public_api_fetcher=public_api_fetcher or fetch_bilibili_public_metadata,
            )
        raise MetadataIngestError(
            f"yt-dlp failed with exit code {result.returncode}: {detail}",
            source_exit_code=result.returncode,
        )

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        detail = result.stdout or result.stderr or "yt-dlp returned empty stdout."
        raise MetadataIngestError(
            f"yt-dlp returned invalid JSON: {detail}",
            source_exit_code=result.returncode,
        ) from exc

    cover_path = _download_cover(run_dir, _cover_url(payload))
    return metadata_from_yt_dlp_json(
        ref,
        payload,
        generated_at=datetime.now(timezone.utc).isoformat(),
        yt_dlp_version=_yt_dlp_version(),
        ffmpeg_version="",
        cover_path=cover_path,
        metadata_source="yt-dlp",
    )


def metadata_from_yt_dlp_json(
    ref: BilibiliPartRef,
    payload: dict[str, Any],
    *,
    generated_at: str,
    yt_dlp_version: str,
    ffmpeg_version: str,
    cover_path: str,
    metadata_source: str = "yt-dlp",
    metadata_attempted_source: str = "yt-dlp",
) -> dict[str, Any]:
    parts = _parts(payload, ref)
    current_part = _current_part(parts, ref.part_index)
    if _has_explicit_part_list(payload) and not current_part:
        raise MetadataIngestError(
            f"{metadata_source} metadata did not contain requested part p={ref.part_index}."
        )
    raw_current_entry = _current_entry(payload, ref.part_index)
    cid = _first_text(current_part.get("cid"), payload.get("cid"))

    return {
        "bilifan_version": __version__,
        "generated_at": generated_at,
        "input_url_sanitized": ref.sanitized_url,
        "video_id": ref.bvid,
        "part_index": ref.part_index,
        "cid": cid,
        "title": _first_text(payload.get("title"), payload.get("fulltitle")),
        "part_title": _first_text(
            _entry_title(raw_current_entry),
            current_part.get("title"),
            payload.get("part"),
            payload.get("title"),
        ),
        "owner_name": _owner_name(payload),
        "description": _first_text(payload.get("description")),
        "tags": _tags(payload),
        "cover_url": _sanitize_public_url(_cover_url(payload)),
        "cover_path": cover_path,
        "duration": _duration_for_current_part(payload, raw_current_entry),
        "parts": parts,
        "subtitles": _subtitles(payload),
        "yt_dlp_version": yt_dlp_version,
        "ffmpeg_version": ffmpeg_version,
        "metadata_source": metadata_source,
        "provenance": {
            "bilifan_version": __version__,
            "generated_at": generated_at,
            "input_url_sanitized": ref.sanitized_url,
            "video_id": ref.bvid,
            "part_index": ref.part_index,
            "cid": cid,
            "metadata_attempted_source": metadata_attempted_source,
            "metadata_source": metadata_source,
            "yt_dlp_version": yt_dlp_version,
            "ffmpeg_version": ffmpeg_version,
        },
    }


def fetch_bilibili_public_metadata(ref: BilibiliPartRef) -> dict[str, Any]:
    view_payload = _fetch_bilibili_api_json(
        f"https://api.bilibili.com/x/web-interface/view?bvid={ref.bvid}"
    )
    view_data = view_payload.get("data")
    if not isinstance(view_data, dict):
        raise MetadataIngestError("Bilibili public API returned invalid view data.")

    tags: list[dict[str, Any]] = []
    try:
        tags_payload = _fetch_bilibili_api_json(
            f"https://api.bilibili.com/x/tag/archive/tags?bvid={ref.bvid}"
        )
        raw_tags = tags_payload.get("data")
        if isinstance(raw_tags, list):
            tags = [tag for tag in raw_tags if isinstance(tag, dict)]
    except MetadataIngestError:
        tags = []

    return {"view": view_data, "tags": tags}


def metadata_from_bilibili_public_api_json(
    ref: BilibiliPartRef,
    payload: dict[str, Any],
    *,
    generated_at: str,
    yt_dlp_version: str,
    ffmpeg_version: str,
    cover_path: str,
) -> dict[str, Any]:
    view_data = payload.get("view")
    if not isinstance(view_data, dict):
        raise MetadataIngestError("Bilibili public API returned invalid view data.")

    normalized_payload = {
        "title": view_data.get("title"),
        "description": view_data.get("desc"),
        "owner": view_data.get("owner"),
        "tags": _api_tags(payload),
        "thumbnail": view_data.get("pic"),
        "duration": view_data.get("duration"),
        "cid": view_data.get("cid"),
        "pages": view_data.get("pages"),
        "subtitles": _api_subtitles(view_data),
    }
    return metadata_from_yt_dlp_json(
        ref,
        normalized_payload,
        generated_at=generated_at,
        yt_dlp_version=yt_dlp_version,
        ffmpeg_version=ffmpeg_version,
        cover_path=cover_path,
        metadata_source="bilibili-public-api",
        metadata_attempted_source="yt-dlp",
    )


def _parts(payload: dict[str, Any], ref: BilibiliPartRef) -> list[dict[str, Any]]:
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raw_entries = payload.get("pages")
    if not isinstance(raw_entries, list):
        return [
            {
                "part_index": ref.part_index,
                "cid": _first_text(payload.get("cid")),
                "title": _first_text(payload.get("part"), payload.get("title")),
                "duration": _clean_duration(payload.get("duration")),
            }
        ]

    parts: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries, start=1):
        if not isinstance(raw_entry, dict):
            continue
        part_index = _part_index(raw_entry, fallback=index)
        parts.append(
            {
                "part_index": part_index,
                "cid": _first_text(raw_entry.get("cid")),
                "title": _entry_title(raw_entry),
                "duration": _clean_duration(raw_entry.get("duration")),
            }
        )
    return parts


def _current_part(parts: list[dict[str, Any]], part_index: int) -> dict[str, Any]:
    for part in parts:
        if part.get("part_index") == part_index:
            return part
    return {}


def _has_explicit_part_list(payload: dict[str, Any]) -> bool:
    return isinstance(payload.get("entries"), list) or isinstance(payload.get("pages"), list)


def _current_entry(payload: dict[str, Any], part_index: int) -> dict[str, Any]:
    for key in ("entries", "pages"):
        raw_entries = payload.get(key)
        if not isinstance(raw_entries, list):
            continue
        for index, raw_entry in enumerate(raw_entries, start=1):
            if not isinstance(raw_entry, dict):
                continue
            if _part_index(raw_entry, fallback=index) == part_index:
                return raw_entry
    return {}


def _part_index(entry: dict[str, Any], *, fallback: int) -> int:
    for key in ("page", "part_index", "playlist_index", "episode_number"):
        value = entry.get(key)
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return fallback


def _entry_title(entry: dict[str, Any]) -> str:
    return _first_text(
        entry.get("part"),
        entry.get("title"),
        entry.get("alt_title"),
        entry.get("display_id"),
    )


def _duration_for_current_part(
    payload: dict[str, Any],
    current_entry: dict[str, Any],
) -> int | float | None:
    return _clean_duration(current_entry.get("duration"), payload.get("duration"))


def _clean_duration(*values: Any) -> int | float | None:
    for value in values:
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, int | float):
            return value
        if isinstance(value, str):
            try:
                parsed = float(value)
            except ValueError:
                continue
            return int(parsed) if parsed.is_integer() else parsed
    return None


def _owner_name(payload: dict[str, Any]) -> str:
    owner = payload.get("owner")
    if isinstance(owner, dict):
        owner_name = _first_text(owner.get("name"), owner.get("mid"))
        if owner_name:
            return owner_name
    return _first_text(
        payload.get("uploader"),
        payload.get("channel"),
        payload.get("creator"),
        payload.get("uploader_id"),
    )


def _tags(payload: dict[str, Any]) -> list[str]:
    raw_tags = payload.get("tags")
    if isinstance(raw_tags, list):
        return [_first_text(tag) for tag in raw_tags if _first_text(tag)]
    if isinstance(raw_tags, str):
        return [tag.strip() for tag in raw_tags.split(",") if tag.strip()]
    return []


def _cover_url(payload: dict[str, Any]) -> str:
    direct = _first_text(payload.get("thumbnail"), payload.get("cover"))
    if direct:
        return direct

    thumbnails = payload.get("thumbnails")
    if isinstance(thumbnails, list):
        for thumbnail in reversed(thumbnails):
            if isinstance(thumbnail, dict):
                url = _first_text(thumbnail.get("url"))
                if url:
                    return url
            else:
                url = _first_text(thumbnail)
                if url:
                    return url
    return ""


def _subtitles(payload: dict[str, Any]) -> list[dict[str, str]]:
    raw_subtitles = payload.get("subtitles")
    if not isinstance(raw_subtitles, dict):
        return []

    subtitles: list[dict[str, str]] = []
    for language, entries in raw_subtitles.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            subtitles.append(
                {
                    "language": _first_text(language),
                    "name": _first_text(entry.get("name")),
                    "url": _sanitize_public_url(_first_text(entry.get("url"))),
                    "ext": _first_text(entry.get("ext")),
                }
            )
    return subtitles


def _fetch_public_api_metadata(
    ref: BilibiliPartRef,
    run_dir: Path,
    *,
    public_api_fetcher: PublicApiFetcher,
) -> dict[str, Any]:
    payload = public_api_fetcher(ref)
    view_data = payload.get("view")
    cover_url = _first_text(view_data.get("pic")) if isinstance(view_data, dict) else ""
    cover_path = _download_cover(run_dir, cover_url)
    return metadata_from_bilibili_public_api_json(
        ref,
        payload,
        generated_at=datetime.now(timezone.utc).isoformat(),
        yt_dlp_version=_yt_dlp_version(),
        ffmpeg_version="",
        cover_path=cover_path,
    )


def _fetch_bilibili_api_json(url: str) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.bilibili.com",
        },
    )
    try:
        with urlopen(request, timeout=METADATA_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_BILIBILI_API_BYTES + 1)
    except (OSError, URLError, ValueError) as exc:
        raise MetadataIngestError(f"Bilibili public API request failed: {exc}") from exc

    if len(raw) > MAX_BILIBILI_API_BYTES:
        raise MetadataIngestError("Bilibili public API response was too large.")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetadataIngestError("Bilibili public API returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise MetadataIngestError("Bilibili public API returned invalid JSON object.")

    if payload.get("code") != 0:
        message = _first_text(payload.get("message"), payload.get("msg"))
        raise MetadataIngestError(f"Bilibili public API returned error: {message}")
    return payload


def _api_tags(payload: dict[str, Any]) -> list[str]:
    raw_tags = payload.get("tags")
    if not isinstance(raw_tags, list):
        return []
    return [
        _first_text(tag.get("tag_name"))
        for tag in raw_tags
        if isinstance(tag, dict) and _first_text(tag.get("tag_name"))
    ]


def _api_subtitles(view_data: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    raw_subtitle = view_data.get("subtitle")
    if not isinstance(raw_subtitle, dict):
        return {}
    raw_entries = raw_subtitle.get("list")
    if not isinstance(raw_entries, list):
        return {}

    subtitles: dict[str, list[dict[str, str]]] = {}
    for entry in raw_entries:
        if not isinstance(entry, dict):
            continue
        language = _first_text(entry.get("lan"), entry.get("language"))
        subtitle_url = _first_text(entry.get("subtitle_url"), entry.get("url"))
        if not language or not subtitle_url:
            continue
        subtitles.setdefault(language, []).append(
            {
                "name": _first_text(entry.get("lan_doc"), entry.get("name")),
                "url": subtitle_url,
                "ext": _subtitle_extension(subtitle_url),
            }
        )
    return subtitles


def _subtitle_extension(url: str) -> str:
    path = urlparse(_normalize_url_scheme(url)).path
    suffix = Path(path).suffix.lstrip(".")
    return suffix or "json"


def _download_cover(run_dir: Path, cover_url: str) -> str:
    safe_cover_url = _sanitize_public_url(cover_url)
    if (
        not safe_cover_url
        or not _is_https_url(safe_cover_url)
        or not _is_allowed_cover_url(safe_cover_url)
    ):
        return ""

    cover_path = run_dir / "assets" / "cover.jpg"
    try:
        cover_path.parent.mkdir(parents=True, exist_ok=True)
        with urlopen(safe_cover_url, timeout=COVER_DOWNLOAD_TIMEOUT_SECONDS) as response:
            final_url = _response_url(response) or safe_cover_url
            safe_final_url = _sanitize_public_url(final_url)
            if (
                not safe_final_url
                or not _is_https_url(safe_final_url)
                or not _is_allowed_cover_url(safe_final_url)
            ):
                return ""
            data = response.read(MAX_COVER_BYTES + 1)
        if len(data) > MAX_COVER_BYTES:
            return ""
        cover_path.write_bytes(data)
    except (OSError, URLError, ValueError):
        return ""
    return "assets/cover.jpg"


def _sanitize_public_url(raw_url: str) -> str:
    raw_url = _normalize_url_scheme(raw_url)
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _normalize_url_scheme(raw_url: str) -> str:
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    return raw_url


def _is_allowed_cover_url(raw_url: str) -> bool:
    host = urlparse(raw_url).hostname or ""
    return any(
        host == suffix.removeprefix(".") or host.endswith(suffix)
        for suffix in ALLOWED_COVER_HOST_SUFFIXES
    )


def _is_https_url(raw_url: str) -> bool:
    return urlparse(raw_url).scheme == "https"


def _response_url(response: Any) -> str:
    geturl = getattr(response, "geturl", None)
    if callable(geturl):
        return _first_text(geturl())
    return _first_text(getattr(response, "url", ""))


def _is_bilibili_412_error(text: str) -> bool:
    return "BiliBili" in text and "HTTP Error 412" in text


def _yt_dlp_version() -> str:
    try:
        import yt_dlp.version
    except Exception:
        return ""
    return _first_text(getattr(yt_dlp.version, "__version__", ""))


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            return value
        if isinstance(value, int | float):
            return str(value)
    return ""
